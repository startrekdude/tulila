"""The entry points of Tulila Server.

Tulila Server has three entry points: one is used by the service manager to start
Tulila Server and the others implement the functionality of Tulila Server's
command-line administrative tools.

All three entry points expect to be run as Tulila Server's dedicated service user;
it's up to the installer to _actually_ make that happen. They work on the same data
(various files in the service user's home directory), but not at the same time:
the administrative tools cannot be used when the server is running (this is enforced
by the wrapper scripts; see bin/).

The two administrative tools are:
  - create_users, to create new users.
  - export_scores, to export high scores (e.g., for grading).
The administrative tools are documented further in the associated function docstrings
and in Tulila's PDF documentation (whenever I get around to writing that).
"""

import atexit
import csv
import importlib.resources
import os.path

from argparse import ArgumentParser
from functools import partial
from io import TextIOWrapper
from os import environ, getpid, urandom
from os.path import expanduser
from random import choice
from socket import socket
from string import digits
from sys import stderr, stdout
from uuid import UUID

import aiohttp_jinja2
import venvcache

from aiohttp.web import run_app, Application
from argon2 import PasswordHasher
from jinja2 import FileSystemLoader
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ._authentication import init_authentication
from ._challenges import challenges, init_challenges, read_name_id_map
from ._csrf_protection import add_csrf_token_to_jinja, init_csrf_protection
from ._database import create_database_engine, init_database, User, Submission
from ._egg import init_egg
from ._graphviz import discard_unused_graphs
from ._routes import init_routes
from ._submissions import init_submissions

from typing import Final


__all__ = (
	"start",
	"create_users",
	"export_scores",
)


# Get the path to the resources directory, which contains Jinja2
# templates and static assets for Tulila Server.
#
# This is complicated because Python supports importing packages from
# zip files, and indeed has comprehensive extension hooks for the
# import system, so there's no particular guarantee the directory we
# want is on disk already (though it will be in 99% of cases).
#
# For this reason importlib.resources.path returns a context manager
# that will extract the desired directory to a temporary path and then
# return that (and delete it after use). I would like the directory to be
# available for the entire lifetime of the program and the following is
# how you spell that when using context managers.
# 99% of the time this code is a no-op and the directory on disk will be used
_ctx = importlib.resources.path(__package__, "rsrc")
_RSRC_PATH: Final = str(_ctx.__enter__())
atexit.register(partial(_ctx.__exit__, None, None, None))
del _ctx


def start() -> None:
	"""Start Tulila Server.
	
	This is run under the service manager (*only systemd is supported) and
	serves Tulila Server on the passed-in socket, or 127.0.0.1:10617 if no
	socket is passed in. Sockets are passed-in via systemd socket activation.
	"""
	venvcache.set_directory(expanduser("~/venvcache"))
	
	# Limit the size of POST requests to make DOS harder
	# The route that accepts submissions uses a configurable limit (16k by default)
	app = Application(client_max_size=1024)
	
	init_database(app)
	init_csrf_protection(app)
	init_authentication(app)
	init_challenges(app)
	init_routes(app)
	init_egg(app)
	init_submissions(app)
	
	aiohttp_jinja2.setup(
        app,
		context_processors=[add_csrf_token_to_jinja, aiohttp_jinja2.request_processor],
        loader=FileSystemLoader(os.path.join(_RSRC_PATH, "templates")),
		autoescape=False,
    )
	
	app.router.add_static("/", os.path.join(_RSRC_PATH, "assets"))
	
	for chal in app[challenges]:
		for agent in chal.agents:
			venvcache.mark_venv_used(agent.deps)
	venvcache.clean()
	
	discard_unused_graphs(app[challenges].challenges)
	
	if environ.get("LISTEN_PID", None) == str(getpid()):
		run_app(app, sock=socket(fileno=3))
	else:
		run_app(app, host="127.0.0.1", port=10617)


def create_users() -> None:
	"""Create Tulila Server users.
	
	The number of users to create is given as a command-line argument.
	
	All users will be given a randomly generated username in the style of
	"Adjective-Noun000" and a securely randomly generated password that is
	the string representation of a UUID.
	
	There is no way to customize the generated users; if they are intended
	to be used by real people, the identity mapping must be stored elsewhere.
	Tulila Server is explicitly designed to process absolutely no PII.
	
	The created users will be output as (username, password) pairs in CSV
	format to standard out.
	"""
	parser = ArgumentParser(description="Create Tulila users.")
	parser.add_argument("num_users", type=int, help="number of users to create")
	args = parser.parse_args()
	
	num_users: int = args.num_users
	if num_users < 0:
		print("cannot create a negative number of users", file=stderr)
		return
	
	with importlib.resources.open_text(__package__, "rsrc/adjectives.txt") as f:
		adjectives = f.read().splitlines()
	
	with importlib.resources.open_text(__package__, "rsrc/nouns.txt") as f:
		nouns = f.read().splitlines()
	
	ph = PasswordHasher()
	engine = create_database_engine()
	
	with Session(engine) as session, session.begin() as f:
		if isinstance(stdout, TextIOWrapper):
			# Turn off universal newlines on stdout; the CSV module handles its own
			# newlines and they should not be mangled further
			stdout.reconfigure(newline="")
		
		writer = csv.writer(stdout)
		
		for _ in range(num_users):
			# The username uses a PRNG that is not cryptographically secure
			username = (
				  choice(adjectives).capitalize()
				+ "-"
				+ choice(nouns).capitalize()
				+ choice(digits)
				+ choice(digits)
				+ choice(digits)
			)
			
			# The password uses a PRNG that _is_ cryptographically secure
			password = str(UUID(bytes=urandom(16)))
			
			user = User(username, ph.hash(password))
			session.add(user)
			writer.writerow((username, password))


def export_scores() -> None:
	"""Export the highest score of each user on each challenge.
	
	Triples (username, challenge_name, score) will be written to standard out
	in CSV format (in no particular order).
	
	If the highest score a user has received on a challenge is 0 (or null,
	caused by an internal error), it will not be included in the output.
	
	No mechanism is provided to subset the data - all user/challenge pairs
	for which a high score exists will be output.
	"""
	parser = ArgumentParser(description="Export scores from Tulila.")
	parser.add_argument("--include-zeros", action="store_true", help="include scores of zero")
	args = parser.parse_args()
	include_zeros: bool = args.include_zeros
	
	engine = create_database_engine()
	id_name_map = {id: name for name, id in read_name_id_map().items()}
	
	with Session(engine) as session:
		if isinstance(stdout, TextIOWrapper):
			# Turn off universal newlines on stdout; the CSV module handles its own
			# newlines and they should not be mangled further
			stdout.reconfigure(newline="")
		
		writer = csv.writer(stdout)
		result = session.execute(
			select(
				Submission.user_id,
				Submission.challenge_id,
				func.max(Submission.score).label("high_score")
			)
			.group_by(Submission.challenge_id, Submission.user_id)
		)
		
		for row in result:
			user_id, challenge_id, score = row._t
			
			if not score:  # 0, _or_ None due to an internal error
				if include_zeros:
					score = 0.0
				else: continue
			
			user = session.get(User, user_id)
			assert user is not None
			
			writer.writerow((user.username, id_name_map[challenge_id], score))

"""Respond appropriately to challenge- and submission- related HTTP requests.

This is the "outer shell" of Tulila Server---it contains the handlers for all
the HTTP routes implementing Tulila Server's functionality.
(Note that authentication and CSRF protection, which are not functionality specific to
 Tulila Server, are implemented elsewhere.)
 
All of the HTTP routes that make Tulila Server what it is are handled here. This includes
routes for:
  - Viewing the list of challenges
  - Viewing a single challenge and submissions to it
  - Creating a new submission to a challenge
  - Viewing live events from a pending submission
  - Viewing a previous submission to a challenge

Naturally, this relies heavily on the other modules of Tulila Server to implement
most of the functionality. This is best considered a shell---formatting and parsing data
to and from the representation used by the client.

Even though most of the "core" functionality of Tulila Server is implemented elsewhere,
this module is still certainly key as without it, there'd be no way to _interact_ with
any of that functionality.

In terms of external API, this module is very simple: it exports a single method,
init_routes, that adds all the routes to a passed-in Application object.
"""

from __future__ import annotations

import json

from contextlib import suppress
from dataclasses import dataclass
from uuid import UUID
from weakref import WeakSet

from aiohttp import WSCloseCode, WSMessageTypeError
from aiohttp.web import (
	json_response,
	AppKey,
	Application,
	HTTPBadRequest,
	HTTPNotFound,
	Response,
	Request,
	RouteTableDef,
	StreamResponse,
	WebSocketResponse,
)
from aiohttp_jinja2 import render_template, template
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter
from sqlalchemy import select, func
from sqlalchemy.orm import undefer_group, Session

from . import _graphviz as graphviz

from ._authentication import requires_authentication, who
from ._challenges import challenges, Challenges
from ._config import SUBMISSION_SIZE_LIMIT
from ._database import database, Submission
from ._submissions import submission_manager, PendingSubmission

from collections.abc import Mapping, MutableMapping, MutableSequence
from typing import Optional



__all__ = (
	"init_routes",
)


_routes = RouteTableDef()


@_routes.get("/")
@requires_authentication
@template("list_challenges.jinja")
async def _list_challenges(request: Request) -> Mapping[str, Challenges | Mapping[int, float]]:
	"""View the list of challenges, broken down by category.
	
	The generated page will also include the user's highest score for each
	challenge, iff they have made any submissions.
	"""
	with Session(request.app[database]) as session:
		high_scores = {
			# The use of _t below is required for this to type-check successfully.
			# Absent that constraint, this could be written:
			# row.challenge_id: row.high_score or 0.0
			row._t[0]: row._t[1] or 0.0
			for row in session.execute(
				select(Submission.challenge_id, func.max(Submission.score).label("high_score"))
				.where(Submission.user == who(request))
				.group_by(Submission.challenge_id)
			)
		}
	
	return {"challenges": request.app[challenges], "high_scores": high_scores}


def _syntax_highlight(code: str) -> str:
	"""Syntax-highlight Python code; return the generated HTML."""
	return highlight(code, get_lexer_by_name("py"), HtmlFormatter(style="xcode", noclasses=True))


@dataclass(frozen=True)
class _OtherAgent:
	"""Glue type that holds an agent's name and syntax-highlighted code.
	
	Used by the template engine to populate the list of other agents;
	required as the agent class itself does not contain syntax-highlighted
	code.
	"""
	name       : str
	code_html  : str


@_routes.get(r"/challenge/{id:\d+}")
@requires_authentication
async def _show_challenge(request: Request) -> Response:
	"""View a challenge.
	
	All users may view every challenge (i.e., there are no access restrictions).
	
	The generated page will include a list of the user's retained submissions
	to the challenge.
	"""
	id = int(request.match_info["id"])
	if not (challenge := request.app[challenges].by_id.get(id, None)):
		return HTTPNotFound()
	
	user = who(request)
	submissions: MutableSequence[Submission | PendingSubmission] = []
	
	if (sub := request.app[submission_manager].pending_by_user.get(user.id, None)) and sub.challenge_id == id:
		submissions.append(sub)
	
	with Session(request.app[database]) as session:
		complete_submissions = session.scalars(
			select(Submission)
			.where(Submission.user == user)
			.where(Submission.challenge_id == id)
			.order_by(Submission.queued_at.desc())
		)
		submissions.extend(complete_submissions)
	
	context = {
		"challenge": challenge,
		"submissions": submissions,
		"graph_svg": await graphviz.render(challenge),
		"other_agents": [
			_OtherAgent(a.name, _syntax_highlight(a.code)) for a in challenge.agents
			if a.show_code is True and a.code is not None
		],
	}
	return render_template("challenge.jinja", request, context)



type _JsonValue = \
	None | bool | str | float | int | MutableSequence[_JsonValue] | MutableMapping[str, _JsonValue]

@_routes.post(r"/challenge/{id:\d+}/submit")
@requires_authentication
async def _submit(request: Request) -> Response:
	"""Create a new submission and queue it for evaluation.
	
	The submission should be sent as an authenticated request to a URL containing
	the challenge ID. The request body should be JSON and have a field named
	"code" containing the code of the submission.
	
	The ID of the new submission will be returned if the submission is created
	successfully; an error message will be returned if not.
	
	Like any POST request, this is CSRF protected by _csrf_protection.
	"""
	# We accept larger request bodies for this path only
	# (see _config for details on tuning this)
	request = request.clone(client_max_size=SUBMISSION_SIZE_LIMIT)
	
	id = int(request.match_info["id"])
	if not (challenge := request.app[challenges].by_id.get(id, None)):
		return HTTPNotFound()
	
	try:
		data: _JsonValue = json.loads(await request.text())
	except ValueError:
		return HTTPBadRequest()
	
	if not isinstance(data, Mapping) or not isinstance((code := data.get("code", None)), str):
		return HTTPBadRequest()
	
	try:
		submission = await request.app[submission_manager].submit(who(request), challenge, code)
	except RuntimeError as e:
		return Response(status=409, text=(str(e).capitalize() + "!"))
	
	response_data = {"id": submission.id.hex}
	return json_response(response_data, status=201)


@_routes.get(r"/challenge/{challenge_id:\d+}/submission/{submission_id:[0-9a-f]{32}}")
@requires_authentication
async def _show_submission(request: Request) -> Response:
	"""View a submission.
	
	The submission may be pending or evaluated.
	Users may only view their own submissions.
	"""
	challenge_id = int(request.match_info["challenge_id"])
	if not (challenge := request.app[challenges].by_id.get(challenge_id, None)):
		return HTTPNotFound()
	
	submission_id = UUID(request.match_info["submission_id"])
	submission: Optional[Submission | PendingSubmission] = \
		request.app[submission_manager].pending_by_id.get(submission_id, None)
	
	if not submission:  # not pending - check the database?
		with Session(request.app[database]) as session:
			submission = session.scalar(
				select(Submission).where(Submission.id == submission_id).options(undefer_group("full"))
			)
	
	if not submission or submission.challenge_id != challenge.id or submission.user_id != who(request).id:
		return HTTPNotFound()
	
	pending = isinstance(submission, PendingSubmission)
	context = {
		"submission": submission,
		"pending"   : pending,
		"challenge" : request.app[challenges].by_id[submission.challenge_id],
		"code_html" : _syntax_highlight(submission.code),
	} | (
		{"started_at": request.app[submission_manager].start_times.get(submission_id, None)}
		if pending else {}
	)
	
	return render_template("submission.jinja", request, context)


@_routes.get(r"/challenge/{challenge_id:\d+}/submission/{submission_id:[0-9a-f]{32}}/is_complete")
@requires_authentication
async def _is_submission_complete(request: Request) -> Response:
	"""Indicate if a submission is evaluated or not.
	
	Internally, this is not a property of the submission object---rather,
	it's an indication of if the given ID corresponds to a pending
	submission tracked by the submission manager or a saved submission
	in the database.
	"""
	challenge_id = int(request.match_info["challenge_id"])
	if not (challenge := request.app[challenges].by_id.get(challenge_id, None)):
		return HTTPNotFound()
	
	submission_id = UUID(request.match_info["submission_id"])
	
	if pending_sub := request.app[submission_manager].pending_by_id.get(submission_id, None):
		# Be sure not to give out any information about another user's submission
		if pending_sub.challenge_id == challenge.id and pending_sub.user_id == who(request).id:
			response_data = {"is_complete": False}
			return json_response(response_data)
		else: return HTTPNotFound()
	
	with Session(request.app[database]) as session:
		submission = session.get(Submission, submission_id)
	
	if submission and submission.challenge_id == challenge.id and submission.user_id == who(request).id:
		response_data = {"is_complete": True}
		return json_response(response_data)
	
	return HTTPNotFound()


# It is necessary for us to keep track of any open WebSockets so they
# can be gracefully closed when the server is shut down---aiohttp does
# not do this by itself! This follows a pattern in the docs
# (https://docs.aiohttp.org/en/stable/web_advanced.html)
_websockets: AppKey[WeakSet[WebSocketResponse]] = AppKey("_websockets")

async def _cleanup_websockets(app: Application) -> None:
	"""Gracefully close any outstanding WebSockets.
	
	This is called by aiohttp when the server is shutting down.
	"""
	sockets = app[_websockets]
	for ws in set(sockets):
		await ws.close(code=WSCloseCode.GOING_AWAY)


@_routes.get(r"/challenge/{challenge_id:\d+}/submission/{submission_id:[0-9a-f]{32}}/events")
@requires_authentication
async def _live_event_socket(request: Request) -> StreamResponse:
	"""Setup a WebSocket to receive events from a pending submission.
	
	This method creates the WebSocket and registers it with the submission
	manager---it does not send any events itself.
	"""
	challenge_id = int(request.match_info["challenge_id"])
	if not (challenge := request.app[challenges].by_id.get(challenge_id, None)):
		return HTTPNotFound()
	
	submission_id = UUID(request.match_info["submission_id"])
	# This route is only valid for pending submissions; no need to check for a saved one
	submission = request.app[submission_manager].pending_by_id.get(submission_id, None)
	
	if not submission or submission.challenge_id != challenge.id or submission.user_id != who(request).id:
		return HTTPNotFound()
	
	ws = WebSocketResponse()
	await ws.prepare(request)
	
	request.app[_websockets].add(ws)
	try:
		await request.app[submission_manager].register_socket(submission_id, ws)
		
		# We do not expect to receive any messages on the socket (it's ->client only)
		# If we receive a message, we consider it an error and close the socket.
		# So why have the receive_str call at all? It's required by aiohttp to keep
		# the socket open and to handle the other end closing the socket.
		with suppress(WSMessageTypeError):
			await ws.receive_str()
		await ws.close(code=WSCloseCode.UNSUPPORTED_DATA)
	finally:
		request.app[submission_manager].deregister_socket(submission_id, ws)
		request.app[_websockets].discard(ws)
	
	return ws


def init_routes(app: Application) -> None:
	"""Add Tulila Server's routes to the given application.
	
	Additionally, associate a weak set with the given application to keep
	track of open WebSockets and register a function that gracefully closes
	any WebSockets that remain open to run when the server shuts down.
	
	(That part of the functionality would probably have to live elsewhere
	 if any other module used WebSockets. They do not, so it's fine here.)
	"""
	app[_websockets] = WeakSet()
	app.on_shutdown.append(_cleanup_websockets)
	app.add_routes(_routes)

"""Store objects, rather than rows, in the database.

This is the "nerve center" of Tulila Server's ORM (object-relational mapper) use.
It is responsible for creating models (i.e., types backed by a database) and for setting
up the ORM (which is SQLAlchemy). It depends on the type annotation map defined by _types
to teach the ORM how to store and load custom types used by Tulila Server.

Only two models are defined: User and Submission. These each correspond to a table (and
an instance corresponds to a row).

The function to create a database engine and initialize it for use with the models also
lives here. A SQLite database located at ~/tulila_server.db is always used (and is created
if it does not exist).

As the HTTP REST layer exposes both complete and pending submissions as the same type of
object---despite the fact that this is not the case internally---the Submission model uses
a long random UUID as the ID rather than the more typical sequential numeric ID to enable
saving pending submissions, once complete, without breaking URLs. The User model also uses
a UUID for consistency.
"""

from __future__ import annotations

import sys

from datetime import datetime
from os.path import expanduser, isfile
from uuid import uuid4, UUID

from aiohttp.web import AppKey, Application
from sqlalchemy import create_engine, Engine, ForeignKey
from sqlalchemy.orm import mapped_column, registry, relationship, Mapped
from tulila import ExitReason

from .._challenges import ChallengeWithMetadata as Challenge

from ._types import LogLine, TYPE_ANNOTATION_MAP

from collections.abc import Sequence
from typing import Optional


__all__ = (
	"User",
	"Submission",
	"create_database_engine",
	"database",
	"init_database",
)


# TYPE_ANNOTATION_MAP comes from _types and sets up custom types for use with SQLAlchemy
_registry = registry(type_annotation_map=TYPE_ANNOTATION_MAP)


@_registry.mapped
class User:
	"""Represent a user.
	
	From the database's perspective, the password hash is an opaque string.
	(It is, in practice, an Argon2id hash. But that's _authentication's concern!)
	"""
	__tablename__ = "user"
	
	id           : Mapped[UUID] = mapped_column(primary_key=True)
	username     : Mapped[str] = mapped_column(unique=True)
	password_hash: Mapped[str]
	
	submissions  : Mapped[list[Submission]] = relationship(back_populates="user")
	
	def __init__(self, username: str, password_hash: str):
		"""Create a user with the specified username and password hash.
		
		A random UUID is generated to use as the new user's ID.
		"""
		self.id = uuid4()
		self.username = username
		self.password_hash = password_hash
	
	def __repr__(self) -> str:
		"""Return a string representation of this user."""
		return f"User(id={self.id!r}, username={self.username!r})"
	
	def __eq__(self, other: object) -> bool:
		"""Test if this user is equal to another object."""
		if not isinstance(other, User):
			return NotImplemented
		return self.id == other.id


@_registry.mapped
class Submission:
	"""Represent a submission that has been evaluated.
	
	Submissions that have not yet been evaluated are represented by the PendingSubmission
	type defined in the _submissions module. (The REST API exposes these as if they were
	the same type of object, but internally they are not.)
	
	Submissions have many attributes, organized into the following logical groupings:
	  - Basic attributes that any submission, even pending, must have (user, challenge, code).
	  - The times at which various stages of submission processing completed.
	  - The result of the submission's evaluation.
	  - The log associated with the submission.
	
	Certain large attributes that are not always required are deferred to save memory.
	"""
	
	__tablename__ = "submission"
	
	id                  : Mapped[UUID] = mapped_column(primary_key=True)
	user_id             : Mapped[UUID] = mapped_column(ForeignKey(User.id))
	challenge_id        : Mapped[int]
	code                : Mapped[str] = mapped_column(deferred=True, deferred_group="full")
	
	queued_at           : Mapped[datetime]
	started_at          : Mapped[datetime]
	finished_at         : Mapped[datetime]
	
	internal_error      : Mapped[bool]
	score               : Mapped[Optional[float]]
	exit_reason         : Mapped[Optional[ExitReason]]
	time                : Mapped[Optional[float]]
	approximate_cpu_time: Mapped[Optional[float]]
	
	log                 : Mapped[Sequence[LogLine]] = mapped_column(deferred=True, deferred_group="full")
	did_truncate        : Mapped[bool] = mapped_column(deferred=True, deferred_group="full")
	
	user                : Mapped[User] = relationship(back_populates="submissions")
	
	def __init__(self, *,
		id: UUID,
		user: User,
		challenge: Challenge,
		code: str,
		queued_at: datetime,
		started_at: datetime,
		finished_at: datetime,
		internal_error: bool,
		score: Optional[float],
		exit_reason: Optional[ExitReason],
		time: Optional[float],
		approximate_cpu_time: Optional[float],
		log: Sequence[LogLine],
		did_truncate: bool,
	):
		"""Create a submission object."""
		self.id = id
		self.user = user
		self.challenge_id = challenge.id
		self.code = code
		self.queued_at = queued_at
		self.started_at = started_at
		self.finished_at = finished_at
		self.internal_error = internal_error
		self.score = score
		self.exit_reason = exit_reason
		self.time = time
		self.approximate_cpu_time = approximate_cpu_time
		self.log = log
		self.did_truncate = did_truncate


def create_database_engine() -> Engine:
	"""Create a database engine and connect it to the database.
	
	SQLite, backed by the file ~/tulila_server.db, is always used.
	
	The database will be migrated (~ structure will be created) if
	it does not exist or if the undocumented parameter "--migrate"
	is passed on the command line. This parameter is intended for
	development use only - to force a migration in production,
	delete the database file!
	"""
	db_path = expanduser("~/tulila_server.db")
	engine  = create_engine("sqlite:///" + db_path)
	
	if not isfile(db_path) or any(s == "--migrate" for s in sys.argv):
		_registry.metadata.drop_all(engine)
		_registry.metadata.create_all(engine)
	
	return engine


database: AppKey[Engine] = AppKey("database")

def init_database(app: Application) -> None:
	"""Setup database functionality for the given Application."""
	app[database] = create_database_engine()

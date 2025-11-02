"""Transparently persist objects in a database.

This is Tulila Server's database layer; it is broadly responsible for setting
up the database and models for the use of the rest of Tulila Server.

It is divided into two modules:
  - _models contains the ORM models and database initialization code.
  - _types defines a "type annotation map" that teaches SQLAlchemy how to persist
    certain custom objects in a database cell; this is used by _models. It also
    defines the LogLine type, which is re-exported for further consumption.

Further documentation is present in each module.
"""

from ._models import create_database_engine, database, init_database, Submission, User
from ._types import LogLine, LogLineDict

__all__ = (
	"create_database_engine",
	"database",
	"init_database",
	"Submission",
	"User",
	"LogLine",
	"LogLineDict",
)

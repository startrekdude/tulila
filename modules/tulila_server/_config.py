"""Read Tulila Server's configuration from environment variables or use default values.

This module defines constants used by the rest of Tulila Server and populates them
from environment variables. The challenge search path _must_ be specified in an
environment variable; all other values have sensible defaults.

This module exists both to avoid code duplication (_get_int need only be defined here)
and to avoid cluttering up the more important modules with configuration code.

Each constant is documented by a preceding comment.
"""

from os import environ, pathsep

from collections.abc import Sequence
from typing import Final


__all__ = (
	"CHALLENGE_PATHS",
	"CONCURRENT_SUBMISSION_LIMIT_OVERRIDE",
	"SUBMISSION_SIZE_LIMIT",
	"LOG_SIZE_LIMIT",
)


# The paths in which to search for challenges, separated by pathsep
# (Since Tulila only supports Linux, pathsep is always ":". But no
#  sense hardcoding when you don't have to.)
path_var_name = "TULILA_SERVER_CHALLENGE_PATH"
if path_var_name not in environ:
	raise RuntimeError(f"{path_var_name} is unset")
CHALLENGE_PATHS: Final[Sequence[str]] = environ[path_var_name].split(pathsep)
del path_var_name


def _get_int(name: str, default: int) -> int:
	"""Retrieve an integer specified in an environment variable or the default."""
	if name not in environ:
		return default
	try:
		return int(environ[name])
	except ValueError:
		return default


# Override the default calculation for the number of submissions that may run concurrently
# The calculation lives in _submissions; -1 means no override
CONCURRENT_SUBMISSION_LIMIT_OVERRIDE: Final = _get_int("TULILA_SERVER_CONCURRENT_SUBMISSION_LIMIT", -1)

# The maximum size of a submission in bytes
SUBMISSION_SIZE_LIMIT: Final = _get_int("TULILA_SERVER_SUBMISSION_SIZE_LIMIT", 16384)

# The limit on the size of a submission's log in bytes; if adding an entry would
# exceed this limit, log entries will be removed starting from the oldest until
# that is no longer the case
LOG_SIZE_LIMIT: Final = _get_int("TULILA_SERVER_LOG_SIZE_LIMIT", 128 * 1024)


del _get_int

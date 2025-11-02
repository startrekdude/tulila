"""Configure Tulila using default settings or environment variables.

This module defines constants used by the rest ot Tulila and populates them with
either a default value or a value taken from an environment variable. The defaults
are intended to be suitable for most use-cases; nevertheless, this module contains
the mechanism to override them.

Each constant is documented by a preceding comment.
"""

from os import environ

from typing import Final


__all__ = (
	"VM_LIMIT",
	"LINE_LENGTH_LIMIT",
)


def _get_int(name: str, default: int) -> int:
	"""Retrieve an integer specified in an environment variable or the default."""
	if name not in environ:
		return default
	try:
		return int(environ[name])
	except ValueError:
		return default


# Agent processes may allocate at most this many bytes of virtual memory
VM_LIMIT: Final = _get_int("TULILA_VM_LIMIT", 64*1024*1024)

# Lines longer than the limit printed by agent processes will not be processed
LINE_LENGTH_LIMIT: Final = _get_int("TULILA_LINE_LENGTH_LIMIT", 2024)


del _get_int

"""Teach SQLAlchemy about custom types used by Tulila Server.

This module contains SQLAlchemy type decorators that teach SQLAlchemy how to store
and load some custom types to/from the database. These are:
  - _UTCDateTime, forcing datetime columns to be in UTC.
  - _SerializedLogLines, converting a submission log to/from bytes. Submission
    logs are loaded "all-or-nothing", so this approach offers the best performance.
Rather than exporting these types from this module directly, a complete SQLAlchemy
type annotation map is provided for use by _models.

The definition of the LogLine type lives here as well, mainly for lack of a better
place to put it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from io import BytesIO
from itertools import batched
from struct import pack, unpack

import pyzstd as zstd

from sqlalchemy import DateTime, Dialect, LargeBinary, TypeDecorator
from tulila import DebugPrint, Diagnostic, Event

from collections.abc import Callable, Mapping, Sequence
from typing import cast, Any, Final, Optional, TypedDict


__all__ = (
	"LogLine",
	"LogLineDict",
	"TYPE_ANNOTATION_MAP",
)


type _SQLAlchemyValue = Optional[Any]


class _UTCDateTime(TypeDecorator[datetime]):
	"""Force datetimes stored in a database to be UTC.
	
	Most databases do not support timezone-aware datetimes, so you can only get
	naïve datetimes out of them. This isn't too bad if you only put naïve
	datetimes in, but if you put a timezone-aware datetime in all bets are off
	as to what you'll get out later. It might be converted, or not, who knows?
	
	This is obviously very error-prone. The modern advice for Python, which this
	package follows, is to exclusively use timezone-aware datetimes.
	
	This class corrects the impedance mismatch by insisting that all datetimes
	to be stored are timezone-aware UTC and adds the UTC timezone to naïve datetimes
	retrieved from the database before exposing them to client code.
	"""
	impl = DateTime
	cache_ok = True
	
	def process_result_value(self, value: _SQLAlchemyValue, dialect: Dialect) -> Optional[datetime]:
		"""Add the UTC timezone to a naïve datetime retrieved from the database.
		
		Null values are passed through unchanged.
		"""
		if value is None:
			return None
		assert isinstance(value, datetime)
		return value.replace(tzinfo=timezone.utc)
	
	def process_bind_param(self, value: Optional[datetime], dialect: Dialect) -> Optional[datetime]:
		"""Ensure a datetime about to be stored in the database has the UTC timezone."""
		if value and value.tzinfo and value.tzinfo != timezone.utc:
			raise ValueError("may only insert UTC datetimes into this column")
		return value


# We make _lots_ of these - set slots=True to save memory
@dataclass(frozen=True, slots=True, kw_only=True)
class LogLine:
	"""Represent a line in a Tulila submission log.
	
	This type corresponds to either a DebugPrint or Diagnostic event
	(depending on whether is_diagnostic is true or not); other event
	types (only created if trace=True) cannot be represented with
	this type. Tulila Server exclusively uses trace=False.
	"""
	timestamp    : float
	is_diagnostic: bool
	agent_name   : str
	line         : str
	
	def as_dict(self) -> LogLineDict:
		"""Return a dictionary representation of this log line."""
		return {
			"timestamp"    : self.timestamp,
			"is_diagnostic": self.is_diagnostic,
			"agent_name"   : self.agent_name,
			"line"         : self.line,
		}
	
	@staticmethod
	def from_event(event: Event) -> LogLine:
		"""Construct a log line from a Tulila event.
		
		Only DebugPrint and Diagnostic events are supported.
		"""
		if isinstance(event.event, DebugPrint):
			is_diagnostic = False
			line = event.event.line
		elif isinstance(event.event, Diagnostic):
			is_diagnostic = True
			line = event.event.warning
		else:
			raise ValueError(
				f"event of type {type(event.event).__name__} not supported, must be DebugPrint or Diagnostic"
			)
		
		return LogLine(
			timestamp     = event.timestamp,
			is_diagnostic = is_diagnostic,
			agent_name    = event.event.agent_name,
			line          = line,
		)


class LogLineDict(TypedDict):
	"""Represent a dictionary that contains the fields of a LogLine.
	
	This type is never used at runtime and is defined only for the benefit
	of the type-checker.
	"""
	timestamp    : float
	is_diagnostic: bool
	agent_name   : str
	line         : str


def _unpack_float(s: bytes) -> float:
	"""Deserialize a 32-bit float from bytes.
	
	The input must be exactly 4 bytes.
	
	The primary purpose of this method is to provide a way of deserializing floats
	that the type-checker is happy with - it doesn't know how to type unpack(), so
	casts are required. And, whenever casts are required, it's better to put them
	in a small method that's "obviously correct."
	"""
	return cast(tuple[float], unpack(">f", s))[0]


class _SerializedLogLines(TypeDecorator[Sequence[LogLine]]):
	"""Serialize and/or deserialize a submission log.
	
	This class teaches SQLAlchemy how to convert a submission log to/from bytes so
	it can be stored in the database.
	
	A custom serialization format is used:
	  - First, the number of log lines is written as a 32-bit unsigned integer.
	  - Log lines are serialized in groups of 8, each starting with a "types byte".
	    The bits in this byte indicate whether each of the following log lines is a
	    diagnostic or debug print - 1 means diagnostic, 0 means debug print.
	  - Each log line is serialized as follows:
	    - The timestamp is serialized as a 32-bit float.
	    - The agent name is serialized as a null=terminated UTF-8 string.
	    - The line is serialized as a null-terminated UTF-8 string.
	After a submission log is converted to bytes in this manner, it is compressed
	with zstd (a fast compression algorithm published by Meta) before being stored;
	this is especially valuable as agent names tend to be repeated quite a bit.
	
	All values for which endianness is relevant are stored in big-endian.
	"""
	
	impl = LargeBinary
	# We explicitly do not specify cache_ok=True so as not to rely on zstd being deterministic.
	# [In practice, it is deterministic _for the same version_. Regardless, cache_ok=True would
	#  not help with performance here - it's not like we ever select on _an entire log_ :)]
	
	def process_bind_param(self, value: Optional[Sequence[LogLine]], dialect: Dialect) -> Optional[bytes]:
		"""Serialize a submission log into bytes.
		
		Null values are passed through unchanged.
		"""
		if value is None:
			return None
		
		buf = BytesIO()
		buf.write(len(value).to_bytes(4))
		
		null_byte = b"\x00"
		
		for batch in batched(value, 8):
			# Create the "types byte", indicating whether each of the following lines is
			# a debug print or a diagnostic. The MSB corresponds to the type of the
			# log line immediately following the types byte, and so on until the LSB
			# corresponds to the type of the last log line in this group of 8.
			# 
			# The final batch may have less than 8 lines; in this case, unused bits will
			# be 0.
			types = 0
			for line in batch:
				types <<= 1
				types  |= line.is_diagnostic
			types <<= 8 - len(batch)
			buf.write(types.to_bytes(1))
			
			for line in batch:
				buf.write(pack(">f", line.timestamp))
				buf.write(line.agent_name.encode())
				buf.write(null_byte)
				buf.write(line.line.encode())
				buf.write(null_byte)
		
		result = buf.getvalue()
		buf.close()  # Eagerly free the memory used by the buffer
		return zstd.compress(result)
	
	def process_result_value(self, value: _SQLAlchemyValue, dialect: Dialect) -> Optional[Sequence[LogLine]]:
		"""Deserialize a submission log from bytes.
		
		Null values are passed through unchanged.
		"""
		if value is None:
			return None
		assert isinstance(value, bytes)
		
		buf    = BytesIO(zstd.decompress(value))
		total  = int.from_bytes(buf.read(4))
		count  = 0
		result = []
		
		# Read a null-terminated string (in one line because I'm so clever)
		read_str: Callable[[], str] = lambda: b"".join(iter(partial(buf.read, 1), b"\x00")).decode()
		
		while count < total:
			# Invariant: the _highest_ bit of types always represents the type
			# of the next log line to be read. This is true when types is read,
			# and must be maintained thereafter as log lines are read.
			types = int.from_bytes(buf.read(1))
			
			for _ in range(8):
				result.append(LogLine(
					timestamp     = _unpack_float(buf.read(4)),
					is_diagnostic = bool(types & 128),
					agent_name    = read_str(),
					line          = read_str(),
				))
				types = (types << 1) & 0xff
				count += 1
				
				if count == total: break
		
		return result


type TypeAnnotationMapType = Mapping[Any, TypeDecorator[Any]]

TYPE_ANNOTATION_MAP: Final[TypeAnnotationMapType] = {
	datetime         : _UTCDateTime(),
	Sequence[LogLine]: _SerializedLogLines(),
}

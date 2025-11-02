"""Parse requests made by agents to the simulator.

This module provides services that parse a request from an agent and pull out parts
of it in a nice, strongly-typed manner. If the request is malformed, an error will
be raised and the simulator will stop processing the request. Requests from agents
are received as strings (that are hopefully valid JSON describing a request).

The mypy directive `allow-any-expr` is in effect for this module, as it deals with
unstructured data. As this module presents typed data to callers, they may be
type checked with `disallow-any-expr`; this is the main motivation for separating this
code into a separate module (i.e., only weaken the type-checker for the smallest amount
of code possible).

In addition to request parsing & validation, this module tracks the agent that issued
a request and provides a utility function to issue diagnostics pertaining to this agent.
"""

from __future__ import annotations

import json

from json import JSONDecodeError

from ._types import Diagnostic, MessageData, Solutions

from collections.abc import MutableMapping
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # avoid circular import chain
	from ._core import Simulation


__all__ = (
	"InvalidRequest",
	"Request",
)


class InvalidRequest(Exception):
	"""Indicate that a request is invalid and cannot be processed further."""
	pass


class Request:
	"""Parse and represent a request from an agent.
	
	This class is given the request line from the agent, the agent name, and
	a reference to the Simulation. The request must be a valid JSON object
	or an InvalidRequest error will be raised.
	
	Methods are provided to get fields from the request as various types
	(string, dict, etc.) - if no such field exists or the field is the
	wrong type an error will be raised and the request will not be
	processed further.
	
	The request is not validated upfront, but is instead validated through
	the use of these methods; in this way calling code can, e.g., request
	different fields based on the value of the request_type field. This also
	simplifies the structure of calling code (rather than "validate -> process",
	it's just "process" and invalid values will automagically end the
	processing of the request early.)
	"""
	
	def __init__(self, request: str, agent_name: str, sim: Simulation):
		"""Parse a request from an agent."""
		self.agent_name = agent_name
		self.sim = sim
		
		try:
			o = json.loads(request)
		except JSONDecodeError:
			raise InvalidRequest() from None
		if not isinstance(o, dict):
			raise InvalidRequest()
		
		self.request = o
	
	async def diagnostic(self, msg: str) -> None:
		"""Indicate that an error or warning was encountered processing this request."""
		await self.sim._push_event(Diagnostic(self.agent_name, msg))
	
	async def _verify_key(self, key: str) -> None:
		"""Verify that a key is present in the request and raise if not."""
		if key not in self.request:
			await self.diagnostic(f"missing {key}")
			raise InvalidRequest()
	
	async def get_str(self, key: str, *, default: Optional[str] = None) -> str:
		"""Return a string value from the request by key (or a default value)."""
		await self._verify_key(key)
		val = self.request[key]
		
		# Note that we use the default value not when the key is not present,
		# but when the key is present and the associated value is None.
		# This matches the request-sending code in tulila-agent-loader.
		# (It would be easy enough to use the default value when the key is
		#  missing, but I control the request-sending code and prefer being
		#  strict. Agents should not send requests except through that code.)
		if default is not None and val is None:
			return default
			
		if not isinstance(val, str):
			await self.diagnostic(f"{key}: expected str, got {type(val).__name__}")
			raise InvalidRequest()
		return val
	
	async def _get_dict(self, key: str) -> MutableMapping[Any, Any]:
		"""Return a dict value from the request by key."""
		await self._verify_key(key)
		val = self.request[key]
		if not isinstance(val, dict):
			await self.diagnostic(f"{key}: expected dict, got {type(val).__name__}")
			raise InvalidRequest()
		return val
	
	async def get_data(self) -> MessageData:
		"""Return this request's message data.
		
		This is meaningful for requests that include a message (e.g., send).
		"""
		return await self._get_dict("data")
	
	async def get_solutions(self) -> Solutions:
		"""Validate and return the solutions in this request.
		
		This is meaningful for requests that include solutions (e.g., set_solutions).
		
		The solutions must consist of a mapping between strings and floats; integers
		will be converted to floats rather than causing an error.
		"""
		o = await self._get_dict("solutions")
		for key in o:
			# The following is excluded from code-coverage as it is unreachable due
			# to the fact that JSON keys are always strings. It is kept anyways
			# as this method's contract with the type-checker indicates it returns
			# a mapping with only string keys.
			if not isinstance(key, str):  # pragma: no cover
				await self.diagnostic("all solutions must be strings")
				raise InvalidRequest()
				
			val = o[key]
			if isinstance(val, int):
				o[key] = val = float(val)
			if not isinstance(val, float):
				await self.diagnostic("all solution scores must be numeric")
				raise InvalidRequest()
		return o

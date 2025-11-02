"""Types used by the Tulila Simulator.

This module defines types used by the Tulila Simulator:
  - The event types included in the simulator event queue.
  - The Message type and related (representing a message sent between agents).
  - The type representing a simulation's Result.
  
All exported types except MessageContext are public (i.e., intended to be exposed to client code).
(MessageContext is intended for use by _core only; everything else is re-exported in __init__)

This is a separate module both for better code organization and to
break a circular dependency chain between _core and _request_parsing.
"""

from __future__ import annotations

import json

from asyncio import StreamWriter
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from collections.abc import Mapping
from typing import Any, Literal, Optional, TypedDict


__all__ = (
	"DebugPrint",
	"Diagnostic",
	"Send",
	"Receive",
	"InterceptModify",
	"InterceptDrop",
	"Solve",
	"Solutions",
	"SetSolutions",
	"EventType",
	"Event",
	"MessageData",
	"MessageContext",
	"Message",
	"ExitReason",
	"Result",
)


@dataclass(frozen=True)
class DebugPrint:
	"""Represent a debug message printed by an agent."""
	agent_name: str
	line      : str

@dataclass(frozen=True)
class Diagnostic:
	"""Represent a warning or error arising from an agent's behaviour."""
	agent_name: str
	warning   : str

@dataclass(frozen=True)
class Send:
	"""Indicate that an agent has sent a message."""
	agent_name: str
	message   : Message

@dataclass(frozen=True)
class Receive:
	"""Indicate that an agent has received a message."""
	agent_name: str
	message   : Message

@dataclass(frozen=True)
class InterceptModify:
	"""Indicate that an agent that previously intercepted a message has modified it.
	
	The message field contains the new message.
	"""
	agent_name: str
	message   : Message

@dataclass(frozen=True)
class InterceptDrop:
	"""Indicate that an agent that previously intercepted a message has dropped it."""
	agent_name  : str
	network_name: str

@dataclass(frozen=True)
class Solve:
	"""Indicate that an agent has attempted to solve the challenge."""
	agent_name: str
	s         : str
	successful: bool
	score     : Optional[float]

type Solutions = Mapping[str, float]

@dataclass(frozen=True)
class SetSolutions:
	"""Indicate that an agent has added or removed solutions."""
	agent_name: str
	solutions : Solutions


type EventType = (
	  DebugPrint
	| Diagnostic
	| Send
	| Receive
	| InterceptModify
	| InterceptDrop
	| Solve
	| SetSolutions
)

class Event(NamedTuple):
	"""Represent an event that occurred during a Tulila simulation."""
	timestamp: float
	event    : EventType


type MessageData = Mapping[Any, Any]
type MessageContext = Literal["direct", "monitor", "intercept"]

class _MessageDict(TypedDict):
	"""Represent a JSON object containing a message in the form it will be sent to an agent.
	
	This is an implementation detail to help Message._launch typecheck successfully.
	"""
	sender   : str
	recipient: str
	network  : str
	data     : MessageData
	context  : MessageContext

@dataclass(frozen=True)
class Message:
	"""Represent a message sent between agents."""
	sender   : str
	recipient: str
	network  : str
	data     : MessageData
	
	async def _deliver(self, context: MessageContext, stream: StreamWriter) -> None:
		"""Deliver the message to an agent using a given StreamWriter.
		
		The context indicates why the message is being delivered to this particular agent.
		"""
		self_as_dict: _MessageDict = {
			"sender"   : self.sender,
			"recipient": self.recipient,
			"network"  : self.network,
			"data"     : self.data,
			"context"  : context,
		}
		stream.write(json.dumps(self_as_dict).encode() + b"\n")
		await stream.drain()


class ExitReason(Enum):
	"""Indicate why a Tulila simulation exited.
	
	Note that a simulation will only exit early on a successful solve with a score of 1.0.
	Therefore, a simulation that exited with, e.g., AGENT_FINISHED may have a score above 0.
	"""
	AGENT_FINISHED           = 1
	SOLVED                   = 2
	EXCEEDED_REAL_TIME_LIMIT = 3
	EXCEEDED_CPU_TIME_LIMIT  = 4


@dataclass(frozen=True)
class Result:
	"""Represent the result of a Tulila simulation."""
	exit_reason         : ExitReason
	score               : float
	time                : float
	approximate_cpu_time: float

"""Simulate an interaction between agents over networks.

This package contains the core Tulila Simulator and related types (event, message, etc.).
It is split into the following three modules:
  - _types, defining types created or used by the simulator
  - _request_parsng, package-private utilities intended to help the simulator parse requests
     from agents. This module is type-checked with `allow-any-expr`.
  - _core, the core simulation logic.
The split is intended to improve code organization and minimize the amount of code type-checked
with the weaker `allow-any-expr` setting. All three modules are extensively documented in their
own files.

The Simulation class is intended to be used by Challenge.launch() only, and is not exposed
publicly. All of the other types---representing intermediate or final results generated as
part of a simulation---are exposed publicly.
"""

from ._core import Simulation
from ._types import (
	DebugPrint,
	Diagnostic,
	Event,
	EventType,
	ExitReason,
	InterceptDrop,
	InterceptModify,
	Message,
	MessageData,
	Receive,
	Result,
	Send,
	SetSolutions,
	Solutions,
	Solve,
)


__all__ = (
	"Simulation",
	"DebugPrint",
	"Diagnostic",
	"Event",
	"EventType",
	"ExitReason",
	"InterceptDrop",
	"InterceptModify",
	"Message",
	"MessageData",
	"Receive",
	"Result",
	"Send",
	"SetSolutions",
	"Solutions",
	"Solve",
)

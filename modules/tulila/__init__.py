"""Evaluate challenges built with agents, networks, protocols, and messages.

Welcome to Tulila - a framework for building and evaluating challenges in which agents, networks,
protocols, and messages are a first-class concept. Tulila is built to address a perceived
deficiency in auto-grading tools I've used in the past---see my honours project proposal for more
details.

A Tulila challenge consists of a collection of agents that communicate using structured messages
over one or more networks. It is most easily defined using a JSON5 file that describes the
objects and references .py files with the agent code. Agents may be given elevated privileges on
certain networks (monitor, intercept, and spoof) --- this simulates a person-in-the-middle
adversary model (and is documented further in the Network class). In a Tulila challenge, one
agent is defined without associated code; this code is provided by the challenge recipient and
is called the "solution" (though it might not receive full marks). A challenge simulation has a
set of solution strings that are most typically set by a privileged agent, though one can also be
statically defined in the challenge file. The challenge recipient is scored based on which solution
string their agent manages to submit (if any).

This module is further subdivided as follows:
  - _agent contains the code supporting Tulila agents, including sandboxing support code.
  - _config contains default values for some internal configuration used by Tulila, and a
    mechanism to override them using environment variables.
  - _loader contains the code that loads challenges from a JSON5 file.
  - _simulation contains the code that runs the simulation. It is quite complex and is tested
    extensively.
  - _types contains the code defining and validating Challenge and Network objects.
"""

from ._agent import Agent
from ._loader import load_challenge, load_challenges
from ._simulation import (
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
from ._types import OrderedSet, Challenge, Metadata, Network

__all__ = (
	"Agent",
	"load_challenge",
	"load_challenges",
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
	"Challenge",
	"Metadata",
	"Network",
	"OrderedSet",
)

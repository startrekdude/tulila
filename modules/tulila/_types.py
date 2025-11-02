"""Types representing concepts in Tulila's domain model.

This module defines the Network and Challenge types, two of the three types that
make a Tulila challenge (the third, Agent, lives alongside the agent launch code).

This module also defines the Metadata and OrderedSet types, which are used for
type-checking.

This module's pupose is mostly just to model data so it has very little behaviour.
However, it does contain validation routines for the objects and the method used
by external API consumers to launch a simulation (though the simulation engine
itself is implemented elsewhere).

Most API consumers would want to load these types from a JSON5 file rather than
instantiate them directly; the routines for this are defined in _loader.
"""

from __future__ import annotations

import dataclasses

from asyncio import Queue
from dataclasses import dataclass, field
from functools import cached_property

from ._agent import Agent
from ._simulation import Event, Result, Simulation

from collections.abc import Collection, Iterable, Mapping, Reversible, Set, Sequence
from typing import overload, Any, Optional, Protocol


__all__ = (
	"Metadata",
	"Network",
	"Challenge",
	"OrderedSet",
)


# Metadata associated with an Agent, Network, or Challenge
# Not used by the Tulila Core at all - just provided to hold any
# extra fields that might be defined in the JSON5
type Metadata = Mapping[str, Any]


@dataclass(frozen=True, kw_only=True)
class Network:
	"""Represent a Tulila network: a named set of agents that may communicate.
	
	Certain agents may be given special privileges on a network. These are:
	  - Monitor: the agent will receive messages not addressed to it.
	  - Interceptor: the agent may modify or drop sent messages before they
	    reach their recipient.
	  - Spoofer: the agent may send messages that name another agent as sender.
	
	All monitors, interceptors, and spoofers must also be members and all
	interceptors must also be spoofers. Multiple intereptors may exist; in this
	case they are ordered and each given a chance to intercept messages in turn.
	
	The logic that routes messages is located in the Simulation class, to which
	this class is just data. Very little behaviour is implemented here.
	
	Agents may communicate with agents on a different network if they are linked
	by an agent that sits on both networks and is coded to forward messages.
	
	This class and its fields are logically immutable. Modifying any of the fields
	of this class via mutable references retained from before it was instantiated
	is unsafe and _will_ lead to undefined behaviour. 
	"""
	name        : str
	members     : Set[str]
	monitors    : Set[str]
	interceptors: OrderedSet[str]
	spoofers    : Set[str]
	metadata    : Metadata = field(default_factory=dict)
	
	def __post_init__(self) -> None:
		"""Validate a newly created network."""
		if not self.name:
			raise ValueError("name must not be empty")
		
		if self.name.startswith("*"):
			raise ValueError("name may not start with '*'")
		
		if len(self.members) < 2:
			raise ValueError("network must have at least two members")
		
		if not self.monitors <= self.members:
			raise ValueError("all monitors must be members")
		
		if not self.interceptors <= self.members:
			raise ValueError("all interceptors must be members")
		
		if not self.spoofers <= self.members:
			raise ValueError("all spoofers must be members")
		
		if not self.interceptors <= self.spoofers:
			raise ValueError("all interceptors must be spoofers")


@dataclass(frozen=True, kw_only=True)
class Challenge:
	"""Represent a Tulila challenge.
	
	A challenge consists of:
	  - A name
	  - A collection of agents
	  - A collection of networks
	  - A real time limit
	  - A CPU time limit
	  - An optional hardcoded solution
	    (Use of this is discouraged - it's better to code an agent that sets a
	     different solution each challenge run.)
	  - Optional metadata.
	
	This class validates that information for consistency and stores it.
	It also provides the .launch() method to launch a Simulation (which is
	implemented elsewhere).
	
	Many invariants are validated by this class---too many to document here
	(see __post_init__). However, one notable invariant is that each Challenge
	must have exactly one agent without code - this code is provided by the
	recipient of the challenge as a parameter to .launch().
	
	This class and its fields are logically immutable. Modifying any of the fields
	of this class via mutable references retained from before it was instantiated
	is unsafe and _will_ lead to undefined behaviour. 
	"""
	name          : str
	agents        : Collection[Agent]
	networks      : Collection[Network]
	time_limit    : float
	cpu_time_limit: float
	solution      : Optional[str] = None
	metadata      : Metadata = field(default_factory=dict)
	
	def __post_init__(self) -> None:
		"""Validate a newly created challenge."""
		if not self.name:
			raise ValueError("name must not be empty")
		
		if self.time_limit <= 0:
			raise ValueError("time limit must be strictly positive")
		
		if self.cpu_time_limit <= 0:
			raise ValueError("cpu time limit must be strictly positive")
		
		if len(self.agents) < 2:
			raise ValueError("challenge must have at least two agents")
		
		if not self.networks:
			raise ValueError("challenge must have at least one network")
		
		agent_names   = set(agent.name   for agent   in self.agents)
		network_names = set(network.name for network in self.networks)
		
		if len(agent_names) < len(self.agents):
			raise ValueError("all agents must have a unique name")
		
		if len(network_names) < len(self.networks):
			raise ValueError("all networks must have a unique name")
		
		for network in self.networks:
			if not network.members <= agent_names:
				raise ValueError(f"network {network.name!r} contains an agent that does not exist")
		
		if sum(1 for agent in self.agents if agent.code is None) != 1:
			raise ValueError("exactly one agent must be missing code")
		
		agents_in_networks = set().union(*(network.members for network in self.networks))
		if not agent_names <= agents_in_networks:
			raise ValueError("all agents must be in at least one network")
	
	async def launch(self, code: str, *, event_queue: Optional[Queue[Event]] = None, trace : bool = False) -> Result:
		"""Launch a simulation of a challenge using the provided code.
		
		Optionally, an event queue may be given to which simulation events will be added.
		This can be used to aid in debugging a challenge or solution.
		
		Setting trace to True will result in more (sometimes many more) events being
		added to the event queue.
		
		There is no mechanism provided to filter events to only those relevant to a specific
		agent; if desired, this may be implemented by the caller.
		
		The actual implementation of this mostly lives in _simulation.
		"""
		if event_queue is None and trace:
			raise RuntimeError("enabling trace mode is only meaningful if an event queue is given")
		
		# Complete the agent with the missing code
		# Note how neither this challenge nor any objects within are directly modified;
		# instead, copies are created.
		completed_agents = list(self.agents)
		for i in range(len(completed_agents)):
			if completed_agents[i].code is None:
				completed_agents[i] = dataclasses.replace(completed_agents[i], code=code)
		
		# Make a copy of this object
		completed_challenge = dataclasses.replace(self)
		
		# The following is an example of "she who makes the rules may also break them."
		# In the external API, a Challenge always has exactly one Agent without code.
		# Interally, however, I saw no point in defining another type of "CompleteChallenge"
		# object without that constraint.
		# So: the Simulation class accepts a Challenge where _all_ the Agents have code.
		# Such objects are invalid according to the rules of the external API but, then,
		# they're never exposed externally! (and neither is the Simulation class)
		# The object.__setattr__ incantation is used to set an attribute on a frozen
		# dataclass while avoiding __post_init__ validation.
		object.__setattr__(completed_challenge, "agents", completed_agents)
		
		# Launch the simulation, return the result
		sim = Simulation(completed_challenge)
		return await sim.launch(event_queue, trace)
	
	@cached_property
	def networks_by_name(self) -> Mapping[str, Network]:
		"""Return a mapping of network names to the corresponding objects."""
		return {net.name: net for net in self.networks}
	
	@cached_property
	def agents_by_name(self) -> Mapping[str, Agent]:
		"""Return a mapping of agent names to the corresponding objects."""
		return {agent.name: agent for agent in self.agents}


class OrderedSet[T](Reversible[T], Collection[T], Protocol):
	"""Represent an ordered set (approximately the intersection of a Sequence and Set).
	
	This Protocol is used by the type-checker to verify if a type meets the
	requirements to be considered an ordered set, which is intended to be the
	intersection of the Set[T] and Sequence[T] types (though it can't quite be
	defined like that as those are ABCs, not Protocols).
	
	Note that this does not define a _mutable_ ordered set; such a protocol
	would, following the conventions of collections.abc, be called MutableOrderedSet.
	(The un-prefixed versions are always immutable).
	
	In Tulila, this Protocol is used to type the interceptors of a Network:
	an immutable ordered set of agent names.
	
	One implementation of this protocol (used by Tulila, see _loader) is
	ordered_set.OrderedSet (yes, same name). This type is not used directly
	in Network both to avoid tying it to one particular implementation and
	because that type is mutable; all of Network is intended to be immutable,
	and this property is important for correctness!
	"""
	
	@overload
	def __getitem__(self, index: slice[int, int, int]) -> Sequence[T]: ...
	@overload
	def __getitem__(self, index: int) -> T: ...
	
	def index(self, key: T) -> int: ...
	def count(self, value: Any) -> int: ...
	
	def __le__(self, other: Set[Any]) -> bool: ...
	def __lt__(self, other: Set[Any]) -> bool: ...
	def __gt__(self, other: Set[Any]) -> bool: ...
	def __ge__(self, other: Set[Any]) -> bool: ...
	def __and__(self, other: Set[Any]) -> Set[T]: ...
	def __or__(self, other: Set[T]) -> Set[T]: ...
	def __sub__(self, other: Set[Any]) -> Set[T]: ...
	def __xor__(self, other: Set[T]) -> Set[T]: ...
	def __eq__(self, other: object) -> bool: ...
	
	def isdisjoint(self, other: Iterable[Any]) -> bool: ...

"""The core simulation logic for Tulila.

This module handles running a simulation of a challenge from beginning to end
(though the specific details around launching agents are handled in _agent).
Its responsibilities include:
  - Correctly routing messages between agents, including broadcast messages,
    spoofing (when permitted), and network monitors and interceptors.
  - Keeping track of solutions and responding to solve requests.
  - Enforcing the real- and cpu-time limits set in the challenge.
  - Generating sufficient logging information to allow challenge authors and
    recipients to debug their work.

This module is the _only_ module that communicates with agents, once launched,
which it does over their standard in and out. As such, it is exposed to, and
must perform complex actions on, unstructured and _untrusted_ data. Special
care is taken to validate all aspects of an agent's request before acting on it.

This module (as well as _types and _request_parsing) is comprehensively tested
with a goal of 100% code and branch coverage. (This is unique among Tulila's
components---elsewhere, I find type-checking and unit-testing sufficient---
and reflects this module's unique role and exposure.)

When possible, simple straight-line code is used. With that said, if the
functionality supported here was non-insignificantly more complex, it
would be a better approach to build many more abstractions for which correctness
can be more easily "proven". (This would easily 3x the code size.)

Note, for posterity, that I am not concerned about agents _escaping_ their
sandbox through a flaw in this module---there's nothing that even rhymes with
"filesystem access" or "code excution" exposed. Nevertheless, it is important to
me that agents are not able to crash the simulation or, through a logic bug,
solve it illegitimately.

Ultimately, this solves a messy problem with lots of global state and where
none of the inputs can be trusted. Such fun!
"""

from __future__ import annotations

import asyncio

from asyncio import create_task, CancelledError, StreamReader, Queue, FIRST_COMPLETED
from collections import defaultdict, deque
from contextlib import suppress
from os import sysconf
from time import time

from .._agent import PipedProcess, ProcessProtocol
from .._config import LINE_LENGTH_LIMIT

from ._request_parsing import InvalidRequest, Request
from ._types import (
	DebugPrint,
	Diagnostic,
	Event,
	EventType,
	ExitReason,
	InterceptDrop,
	InterceptModify,
	Message,
	Receive,
	Result,
	Send,
	SetSolutions,
	Solve,
)

from collections.abc import AsyncIterator, Collection, Mapping, MutableMapping
from typing import cast, Final, Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # avoid circular import
	from .._types import Challenge, Network


__all__ = (
	"Simulation",
)


_BROADCAST: Final = "*"
_TRACE_EVENT_TYPES: Final = (Send, Receive, InterceptModify, InterceptDrop, Solve, SetSolutions)
_CLK_TCK: Final = sysconf("SC_CLK_TCK")


def _proc_cpu_time(proc: ProcessProtocol) -> float:
	"""Measure the total CPU time used by a process so far in seconds."""
	with open(f"/proc/{proc.pid}/stat") as f:
		stats = f.read().split()
	
	# 13 and 14 are user time and system time, respectively
	return (int(stats[13]) + int(stats[14])) / _CLK_TCK


class Simulation:
	"""Execute a simulation of the given Challenge and return the result, including the score.
	
	All agents in the Challenge are expected to have associated code before starting the
	simulation.
	
	This class represents an ongoing simulation of the interactions between agents over
	networks as defined by the passed-in Challenge. The .launch() method starts the simulation.
	
	The final result, including the score, will be returned by the .launch() method and more
	detailed information re. what's going on in the simulation can be obtained by passing in an
	optional event queue. Even more information will be sent if trace=True.
	
	The responsibilities of this class include starting all the agents (though details of this
	are handled in _agent), handling requests from agents, passing messages between agents,
	monitoring real- and CPU-time usage, tearing down the simulation when it is complete, and
	returning a result.
	
	Simulation objects should be used for at most one simulation run; they are not safe to re-use.
	"""
	
	def __init__(self, challenge: Challenge):
		"""Initialize (but do not launch) a Simulation for the provided Challenge."""
		self._chal = challenge
		
		# Queues, associated with each agent by name, of the network names of messages
		# that have been passed to said agent to intercept
		self._intercept_queues: Mapping[str, deque[str]] = defaultdict(deque)
		
		self._exit_reason: Optional[ExitReason] = None
		self._solutions: MutableMapping[str, float] = {}
		self._score = 0.0
		
		if self._chal.solution:
			self._solutions[self._chal.solution] = 1.0
	
	async def _handle_request(self, req: Request) -> None:
		"""Handle a request from an agent."""
		request_type = await req.get_str("request_type")
		if request_type == "send":
			if self._intercept_queues[req.agent_name]:
				await self._handle_intercept(req)
			else:
				await self._handle_send_request(req)
		elif request_type == "drop":
			if self._intercept_queues[req.agent_name]:
				network_name = self._intercept_queues[req.agent_name].popleft()
				await self._push_event(InterceptDrop(req.agent_name, network_name))
			else:
				await req.diagnostic("no intercepted message to drop")
		elif request_type == "set_solutions":
			await self._handle_set_solutions(req)
		elif request_type == "solve":
			await self._handle_solve(req)
		else:
			await req.diagnostic(f"unknown request type: {request_type}")
	
	async def _handle_send_request(self, req: Request) -> None:
		"""Handle a request from an agent to send a message."""
		# Read in the parameters sent by the agent
		sender       = await req.get_str("sender", default=req.agent_name)
		recipient    = await req.get_str("recipient")
		network_name = await req.get_str("network")
		data         = await req.get_data()
		
		# A given send request may result in more than one actual message being sent if, e.g.,
		# _BROADCAST is used as the network or recipient. First, we figure out on which networks
		# we will send a message.
		if network_name == _BROADCAST:
			if recipient == _BROADCAST:
				networks: Collection[Network] = self._chal.networks
			else:
				networks = [net for net in self._chal.networks if recipient in net.members]
		else:
			# If a network name is specified, make sure it's a real network
			networks = (self._chal.networks_by_name[network_name],) \
			           if network_name in self._chal.networks_by_name else ()
		
		if not networks:
			await req.diagnostic("no matching networks")
			return
		
		for network in networks:
			if sender != req.agent_name and req.agent_name not in network.spoofers:
				await req.diagnostic(f"may not spoof identity on network {network.name}")
				continue
			
			recipients = (recipient,) if recipient != _BROADCAST else network.members
			for next_recipient in recipients:
				# This check has the side effect of making sure the recipient exists at all
				if next_recipient not in network.members:
					await req.diagnostic(f"{next_recipient} is not on network {network.name}")
					continue
				
				msg = Message(sender, next_recipient, network.name, data)
				await self._push_event(Send(req.agent_name, msg))
				
				# Before any message is delivered, every interceptor on the network must weigh in
				await self._handle_next_intercept(msg)
	
	async def _handle_next_intercept(self, msg: Message, from_agent: Optional[str] = None) -> None:
		"""Send a message to the next interceptor on the network, if any.
		
		from_agent is the previous interceptor, if any.
		If there are no more interceptors on the network, deliver the message.
		"""
		network = self._chal.networks_by_name[msg.network]
		next_interceptor_index = network.interceptors.index(from_agent) + 1 \
		                         if from_agent is not None else 0
		if next_interceptor_index >= len(network.interceptors):
			await self._deliver(msg)
		else:
			next_interceptor = network.interceptors[next_interceptor_index]
			self._intercept_queues[next_interceptor].append(msg.network)
			await msg._deliver("intercept", self._procs[next_interceptor].stdin)
	
	async def _handle_intercept(self, req: Request) -> None:
		"""Handle an interceptor's modification of a message."""
		sender       = await req.get_str("sender", default=req.agent_name)
		recipient    = await req.get_str("recipient")
		network_name = await req.get_str("network")
		data         = await req.get_data()
		
		expect_network = self._intercept_queues[req.agent_name].popleft()
		
		if network_name != expect_network:
			await req.diagnostic("may not change network of intercepted message")
			return
		
		if recipient == _BROADCAST:
			# As all interceptors are also spoofers, they may _manually_ modify an
			# intercepted message to be broadcast. We do not assist them in this
			# transformation, though.
			await req.diagnostic("may not modify an intercepted message to be broadcast")
			return
		
		# This check also verifies that the recipient exists
		if recipient not in self._chal.networks_by_name[network_name].members:
			await req.diagnostic(f"{recipient} is not on network {network_name}")
			return
		
		msg = Message(sender, recipient, network_name, data)
		await self._push_event(InterceptModify(req.agent_name, msg))
		
		# Multiple interceptors may exist; allow the next (if any) to weigh in
		await self._handle_next_intercept(msg, req.agent_name)
	
	async def _deliver(self, msg: Message) -> None:
		"""Deliver a message to the agent to which it is addressed.
		
		CC the message to any monitors on the same network.
		"""
		await self._push_event(Receive(msg.recipient, msg))
		await msg._deliver("direct", self._procs[msg.recipient].stdin)
		
		for agent_name in self._chal.networks_by_name[msg.network].monitors:
			if agent_name != msg.recipient:
				await self._push_event(Receive(agent_name, msg))
				await msg._deliver("monitor", self._procs[agent_name].stdin)
	
	async def _handle_solve(self, req: Request) -> None:
		"""Evaluate an attempt by an agent to solve the challenge."""
		# If the challenge is already completely solved, we ignore the solve request.
		# The simulation will shut down as soon as asyncio realizes _solved is triggered.
		if self._score == 1:
			return
		
		s = await req.get_str("s")
		if s not in self._solutions:
			await self._push_event(Solve(req.agent_name, s, False, None))
			await req.diagnostic(f"{s!r}: not a solution")
			return
			
		self._score = self._solutions[s]
		await self._push_event(Solve(req.agent_name, s, True, self._score))
		
		# Only if the challenge is fully solved (score = 1, max) do we exit early
		if self._score == 1:
			self._exit_reason = ExitReason.SOLVED
			self._solved.set()  # trigger an early exit
	
	async def _handle_set_solutions(self, req: Request) -> None:
		"""Add or remove solutions to this challenge run.
		
		A request by an agent without permission will be rejected.
		"""
		if not self._chal.agents_by_name[req.agent_name].may_set_solution:
			await req.diagnostic("may not set solutions")
			return
		
		solutions = await req.get_solutions()
		await self._push_event(SetSolutions(req.agent_name, solutions))
		for s, score in solutions.items():
			if not (0 <= score <= 1):
				await req.diagnostic("solution score must be between 0 and 1")
				continue
			
			if score == 0:
				# For a score of 0, remove a solution if it exists
				# Do not raise a error/diagnostic if it does not
				self._solutions.pop(s, None)
			else:
				self._solutions[s] = score
	
	async def _safe_lines(self, agent_name: str, what: Literal["stdout", "stderr"]) -> AsyncIterator[str]:
		"""Iterate over lines from an agent's standard out or error that are safe to process.
		
		End when an empty string is read (i.e., EOF is reached).
		
		A line is considered unsafe to process if it exceeds the LINE_LENGTH_LIMIT; this
		is a potential DOS vector. In this case, a diagnostic will be generated for the agent.
		"""
		stream = cast(StreamReader, getattr(self._procs[agent_name], what))
		while (line := await stream.readline()):
			if len(line) <= LINE_LENGTH_LIMIT:
				if line[-1:] == b"\n": line = line[:-1]
				yield line.decode(errors="replace")
			else:
				await self._push_event(
					Diagnostic(agent_name, f"line of length {len(line)} exceeds maximum of {LINE_LENGTH_LIMIT}")
				)
	
	async def _monitor_agent_stderr(self, agent_name: str) -> None:
		"""Receive lines from an agent's standard error and generate DebugPrint events."""
		async for line in self._safe_lines(agent_name, "stderr"):
			await self._push_event(DebugPrint(agent_name, line))
	
	async def _monitor_agent_stdout(self, agent_name: str) -> None:
		"""Process requests from an agent (sent over its standard out)."""
		async for line in self._safe_lines(agent_name, "stdout"):
			with suppress(InvalidRequest):
				await self._handle_request(Request(line, agent_name, self))
	
	async def _monitor_cpu_usage(self) -> None:
		"""Periodically monitor the CPU usage of the simulation and end it if it exceeds the limit.
		
		The CPU usage of the simulation is the sum of the CPU usage of its agent processes.
		This value is both returned as part of the simulation's result and used to enforce the limit.
		"""
		while True:
			await asyncio.sleep(0.25)
			
			try:
				self._cpu_time = sum(_proc_cpu_time(proc) for proc in self._procs.values())
			# If any of the agents have ended, the simulation is complete.
			# The only reasonable thing for this task to do is end early and effectively
			# cancel itself. (Note that this behaviour is not required for correctness:
			# all tasks will be cancelled when _launch realizes an agent has ended.)
			# Excluded from code coverage as it is impossible to trigger reliably.
			except FileNotFoundError:  # pragma: no cover
				return
			
			if self._cpu_time > self._chal.cpu_time_limit:
				self._exit_reason = self._exit_reason or ExitReason.EXCEEDED_CPU_TIME_LIMIT
				return
	
	async def _watchdog(self) -> None:
		"""Exit if the challenge's time limit is reached."""
		await asyncio.sleep(self._chal.time_limit)
		self._exit_reason = self._exit_reason or ExitReason.EXCEEDED_REAL_TIME_LIMIT
	
	async def _push_event(self, event: EventType) -> None:
		"""Pushes an event onto the event queue.
		
		Does nothing if there is no event queue.
		Only pushes "trace" events if trace is true.
		
		Events will be associated with a timestamp (relative to simulation start).
		"""
		if self._event_queue and (self._trace or not isinstance(event, _TRACE_EVENT_TYPES)):
			await self._event_queue.put(Event(time() - self._sim_start, event))

	async def launch(self, event_queue: Optional[Queue[Event]] = None, trace: bool = False) -> Result:
		"""Launch the simulation and return the result.
		
		Optionally, set up an event queue and enable trace mode.
		"""
		self._event_queue = event_queue
		self._trace = trace
		self._sim_start = time()
		self._cpu_time = 0.0
		self._solved = asyncio.Event()
		
		self._procs: Mapping[str, PipedProcess] = {agent.name: await agent._launch() for agent in self._chal.agents}
		tasks = (
			  [create_task(self._monitor_agent_stderr(agent.name)) for agent in self._chal.agents]
			+ [create_task(self._monitor_agent_stdout(agent.name)) for agent in self._chal.agents]
			+ [create_task(self._monitor_cpu_usage())]
			+ [create_task(self._watchdog())]
			+ [create_task(self._solved.wait())]  # end the simulation if _solved is triggered
		)
		
		# asyncio.wait does not throw CancelledError. So why are we catching it?
		# The asyncio _runtime_ will raise CancelledError at the earliest opportunity if
		# this task---i.e., launch itself---is cancelled. We must catch it so we can clean up---
		# specifically, it is important that we kill agent processes and cancel all our subtasks.
		cancelled = None
		try:
			# The simulation ends as soon as _any_ of the tasks completes; any looping is handled
			# internal to these tasks
			await asyncio.wait(tasks, return_when=FIRST_COMPLETED)
		except CancelledError as e:  # pragma: no cover
			cancelled = e
		
		# Make very sure the processes die and are waited for, we don't want
		# to leave zombies! In particular, do this before awaiting tasks as they
		# may raise an Exception (well...they shouldn't...but you never know!).
		for proc in self._procs.values():
			if proc.returncode is None:
				proc.kill()
			
			try:
				await proc.wait()
			except CancelledError as e:  # pragma: no cover
				if not cancelled: cancelled = e
		
		excs = []
		for task in tasks:
			if not task.done():
				task.cancel()
			
			try:
				# ConnectionError indicates a broken pipe, which is expected as we've
				# already killed the agent processes at this point
				with suppress(CancelledError, ConnectionError):
					await task
			# Excluded from coverage as I don't know of a way to make any of the tasks crash
			# [If I did, I'd fix it :-)]
			except Exception as e:  # pragma: no cover
				excs.append(e)
		
		# If we were cancelled, exit immediately after cleaning up
		if cancelled:  # pragma: no cover
			raise cancelled from None
		
		if excs:  # pragma: no cover
			raise ExceptionGroup("errors encountered tearing down simulation", excs)
		
		# The "default" exit reason is an agent finished
		self._exit_reason = self._exit_reason or ExitReason.AGENT_FINISHED
		return Result(self._exit_reason, self._score, time() - self._sim_start, self._cpu_time)

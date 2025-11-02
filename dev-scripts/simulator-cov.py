"""Ensure the Tulila Simulator works as intended.

This script performs automatic testing of all elements of the Tulila Simulator,
comparing actual results to expected results to demonstrate correct functionality.

This script is run under coverage.py ("coverage run") with a goal of achieving
100% code and branch coverage for the Tulila Simulator core (tulila._simulation).
At time of writing, it achieves this goal. Future changes to the Tulila Simulator
should update this file accordingly, both to keep 100% coverage and to ensure new
functionality or bug fixes work as expected.

I chose to test the Tulila Simulator in this particularly extensive way as it is
the only part of the Tulila Core that is exposed directly to data provided by the
challenge _recipient_ (in contrast to the challenge _author_). The challenge author
is expected to both be competent and have shell access to the Tulila server---it is
expected that they might go through a few rounds of "edit challenge file" > "run" >
"see exception" > "fix challenge file" when developing a challenge and, if an actual
bug is found during this process, they are in a position to fix it. In contrast, the
challenge recipient has no real ability to fix bugs, so bugs in the Tulila Simulator
are particularly frustrating and could break the recipient's flow if they need to bug
someone to get it fixed.

Additionally, bugs in the Tulila Simulator could result in accepting illegitimate
solutions to challenges. Note, though, that I am not worried that bugs in the Tulila
Simulator could result in a sandbox escape---the agent sandbox is a different
component that I have a high level of confidence in and there's simply no
functionality exposed by the simulator that could cause a sandbox breach. It's not
like "trusted" agents are able to interact with the filesystem or launch processes
and the simulator is one buggy permission check away from allowing a sandbox
breach---no agents can do that, and the simulator doesn't have any code that would
do that to expose.

For the reasons outlined above, I consider bugs in the Tulila Simulator to be
particularly impactful and, as such, use this script under coverage testing to gain
a high level of confidence that the simulator works as intended. In short: if the
JSON5 parsing code is buggy, that's really no big deal, but the simulator itself
needs to be rock solid.
"""

import asyncio

from asyncio import create_task, CancelledError, Queue, FIRST_COMPLETED
from contextlib import suppress
from itertools import zip_longest
from sys import maxsize
from textwrap import dedent

from ordered_set import OrderedSet
from termcolor import cprint
from tulila import (
	Agent,
	Challenge,
	DebugPrint,
	Diagnostic,
	ExitReason,
	InterceptDrop,
	Network,
	Message,
	Receive,
	Send,
	SetSolutions,
	Solve,
)


class ExpectResult:
	"""Verify that a simulation result has the expected attributes.
	
	This class as well as the ExpectEvents class below are used to verify a test
	completed successfully (or not, as the case may be).
	
	The test harness will call .verify() with the pertinent information and it
	will return either None for success or an error message for failure.
	"""
	
	def __init__(self, exit_reason=None, score=None):
		self.exit_reason = exit_reason
		self.score = score
	
	def verify(self, result):
		if self.exit_reason and result.exit_reason != self.exit_reason:
			return f"incorrect exit reason: expected {self.exit_reason}, got {result.exit_reason}"
		if self.score and result.score != self.score:
			return f"incorrect score: expected {self.score}, got {result.score}"
		return None


class Event:
	"""Represent an event that a simulation is expected to generate.
	
	If ExpectEvents is used with this class, it will verify that the type and
	all attributes given match the event that was actually generated.
	"""
	
	def __init__(self, type, **kwargs):
		self.type = type
		self.attrs = kwargs


class NoEvent:
	"""Represent that an expected event was not generated or that no event was expected."""
	pass


class ExpectEvents:
	"""Verify that a simulation generated the expected events.
	
	This class accepts a list of events, which can be either bare event types
	or instances of the Event class above. After the simulation is complete,
	the actual events generated are verified to have the expected type and
	attributes (if present; attributes are optional).
	"""
	
	def __init__(self, events):
		self.events = events
	
	def verify(self, events):
		for i, (actual, expected) in enumerate(zip_longest(events, self.events, fillvalue=NoEvent()), 1):
			if isinstance(expected, Event):
				if type(actual) != expected.type:
					return f"event {i}: expected {expected.type.__name__}, got {type(actual).__name__}"
				
				for k, v in expected.attrs.items():
					if getattr(actual, k) != v:
						return f"event {i}: expected {k}={v}, got {getattr(actual, k)}"
			elif type(actual) != expected:
				expected_name = "NoEvent" if isinstance(expected, NoEvent) else expected.__name__
				return f"event {i}: expected {expected_name}, got {type(actual).__name__}"
		return None


test_num     = 0
tests_passed = 0

async def run_test(chal, code, *verifiers, trace=False):
	"""Run a challenge to completion and verify it generates the expected results.
	
	Additionally, display what test is being run, the results of the simulation
	(including events), and whether the test passed or failed.
	
	Updates the test_num and tests_passed global variables accordingly.
	"""
	global test_num, tests_passed
	test_num += 1
	
	cprint(f"Running test #{test_num}: {chal.name}...", attrs=["bold"], end="")
	if trace:
		cprint(" [trace]", "light_magenta")
	else:
		print()
	
	queue = Queue()
	events = []  # Keep track of the events that were generated for later verification
	
	# At all times, keep track of the task representing completion and the task
	# that gets the next event from the queue (which is re-created as required)
	done_task  = create_task(chal.launch(code, event_queue=queue, trace=trace))
	event_task = create_task(queue.get())
	
	while True:
		done, pending = await asyncio.wait([done_task, event_task], return_when=FIRST_COMPLETED)
		for task in done:
			if task is event_task:
				event = (await task).event
				print(f" {event!r}")
				events.append(event)
				event_task = create_task(queue.get())
				
			if task is done_task:
				event_task.cancel()
				with suppress(CancelledError):
					await event_task
				result = await task
				print(f" {result!r}")
				break
		
		# Exit the outer loop iff the inner loop breaks (i.e., the simulation is complete)
		else: continue
		break
	
	for verifier in verifiers:
		if isinstance(verifier, ExpectResult):
			error = verifier.verify(result)
		elif isinstance(verifier, ExpectEvents):
			error = verifier.verify(events)
		else: assert False
		
		if error is not None:
			cprint("FAILED: ", "red", attrs=["bold"], end="")
			cprint(f"{error}\n", "red")
			return
	
	cprint("PASSED\n", "green")
	tests_passed += 1


async def main():
	"""Run a series of tests for the Tulila Simulator and print the results.
	
	The tests are designed to give 100% code and branch coverage of the core
	simulator. This increases confidence that the Tulila Simulator functions
	as designed.
	"""
	# Shorthands to create agents, networks, and challenges with sane defaults
	# Saves on typing when defining the tests to run!
	def A(name, code, may_set_solution=False, deps=None):
		if deps is None:
			deps = []
		return Agent(
			name=name,
			code=code,
			may_set_solution=may_set_solution,
			deps=deps
		)
	def N(name, members, monitors=None, interceptors=None, spoofers=None):
		if monitors is None:
			monitors = set()
		if interceptors is None:
			interceptors = OrderedSet()
		if spoofers is None:
			spoofers = set()
		return Network(
			name=name,
			members=members,
			monitors=monitors,
			interceptors=interceptors,
			spoofers=spoofers
		)
	def C(name, agents, networks, time_limit=maxsize, cpu_time_limit=maxsize, solution=None):
		return Challenge(
			name=name,
			agents=agents,
			networks=networks,
			time_limit=time_limit,
			cpu_time_limit=cpu_time_limit,
			solution=solution
		)
	# Create the simplest possible networks (for when nothing complex is needed)
	def fastN(*members):
		return [N("public", set(members))]
	
	# Define some "prefab" agents used in the tests
	# empty and admin are the agents without code, so at least one appears in every test
	# (with appropriate code for what's being tested). admin may set solutions, empty may not.
	empty      = A("empty", None)
	admin      = A("admin", None, may_set_solution=True)
	do_nothing = A("do_nothing", "")
	echo       = A("echo", dedent("""\
		while True:
			msg = receive()
			print(msg.data["s"])
	"""))
	forever    = A("forever", dedent("""\
		from time import sleep
		
		while True:
			sleep(1)
	"""))
	alice      = A("alice", dedent("""\
		from time import sleep
		
		send({"s": "hello world"}, "echo")
		sleep(0.05)
	"""))
	solutions  = A("solutions", dedent("""\
		from time import sleep
		
		for x in range(2, 12, 2):
			set_solution(str(x / 10), x / 10)
		
		while True:
			sleep(1)
	"""), may_set_solution=True)
	
	await run_test(
		C("default_score_is_zero", [empty, do_nothing], fastN("empty", "do_nothing")),
		"",
		ExpectResult(score=0.0)
	)
	
	await run_test(
		C("invalid_json_no_message", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			import sys; sys.stdout = send.__globals__["_real_stdout"]
			print("invalid json")
		"""),
		ExpectEvents(())
	)
	
	await run_test(
		C("invalid_unicode_is_replaced", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			import sys
			sys.stderr.buffer.write(bytes.fromhex("d168656c6c6ffe0a"))
			sys.stderr.buffer.flush()
		"""),
		ExpectEvents([
			Event(DebugPrint, line="\ufffdhello\ufffd")
		])
	)
	
	await run_test(
		C("json_not_dict_no_message", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			import sys; sys.stdout = send.__globals__["_real_stdout"]
			print("[]")
		"""),
		ExpectEvents(())
	)
	
	await run_test(
		C("no_request_type_diagnostic", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			import sys; sys.stdout = send.__globals__["_real_stdout"]
			print("{}")
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("request_type_not_str_diagnostic", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			import sys; sys.stdout = send.__globals__["_real_stdout"]
			print('{"request_type": true}')
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("simple_message_echo", [empty, echo], fastN("empty", "echo")),
		dedent("""\
			from time import sleep
			
			send({"s": "hello"}, "echo")
			sleep(0.05)
		"""),
		ExpectEvents([Send, Receive, Event(DebugPrint, line="hello")]),
		trace=True
	)
	
	await run_test(
		C("monitors_read_all_messages", [empty, alice, echo], [
			N("public", {"empty", "alice", "echo"}, monitors={"empty"})
		]),
		dedent("""\
			from time import sleep
			
			while True:
				msg = receive()
				if "s" in msg.data:
					print(msg.data["s"])
		"""),
		ExpectEvents([DebugPrint, DebugPrint])
	)
	
	await run_test(
		C("multiple_monitors", [empty, alice, echo, A("eve", "print(receive().data['s'])")], [
			N("public", {"empty", "alice", "echo", "eve"}, monitors={"empty", "eve", "echo"})
		]),
		dedent("""\
			from time import sleep
			
			while True:
				msg = receive()
				if "s" in msg.data:
					print(msg.data["s"])
		"""),
		ExpectEvents([DebugPrint, DebugPrint, DebugPrint])
	)
	
	await run_test(
		C("data_not_dict_diagnostic", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			import sys; sys.stdout = send.__globals__["_real_stdout"]
			print('{"request_type": "send", "sender": null, "recipient": "*", "network": "*", "data": true}')
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("exceed_cpu_time_limit", [empty, forever], fastN("empty", "forever"), cpu_time_limit=0.5),
		dedent("""\
			import sys; sum(range(sys.maxsize))
		"""),
		ExpectResult(exit_reason=ExitReason.EXCEEDED_CPU_TIME_LIMIT)
	)
	
	await run_test(
		C("exceed_real_time_limit", [empty, forever], fastN("empty", "forever"), time_limit=0.5),
		dedent("""\
			import time
			time.sleep(5)
		"""),
		ExpectResult(exit_reason=ExitReason.EXCEEDED_REAL_TIME_LIMIT)
	)
	
	await run_test(
		C("line_length_diagnostic", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			from time import sleep
			
			print("a" * 4096)
			sleep(0.1)
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("builtin_solution_scores_full", [empty, do_nothing], fastN("empty", "do_nothing"), solution="foo"),
		dedent("""\
			solve("foo")
		"""),
		ExpectResult(exit_reason=ExitReason.SOLVED, score=1.0),
		ExpectEvents([
			Event(Solve, agent_name='empty', s='foo', successful=True, score=1.0)
		]),
		trace=True
	)
	
	await run_test(
		C("unknown_request_type_diagnostic", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			from time import sleep
			
			import sys; sys.stdout = send.__globals__["_real_stdout"]
			print('{"request_type": "sing"}')
			sleep(0.05)
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("invalid_network_diagnostic", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			send({}, "do_nothing", "private")
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("broadcast_single_network", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			send({}, "*", "public")
		"""),
		ExpectEvents([Send, Receive, Send, Receive]),
		trace=True
	)
	
	await run_test(
		C("broadcast_multi_network", [empty, do_nothing, forever], [
			N("public", {"empty", "do_nothing"}),
			N("private", {"empty", "forever"}),
		]),
		dedent("""\
			send({}, "*", "*")
		"""),
		ExpectEvents([Send, Receive, Send, Receive, Send, Receive, Send, Receive]),
		trace=True
	)
	
	await run_test(
		C("broadcast_single_network_when_multi", [empty, do_nothing, forever], [
			N("public", {"empty", "do_nothing"}),
			N("private", {"empty", "forever"}),
		]),
		dedent("""\
			send({}, "*", "public")
		"""),
		ExpectEvents([Send, Receive, Send, Receive]),
		trace=True
	)
	
	await run_test(
		C("recipient_invalid_diagnostic", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			send({}, "forever", "public")
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("recipient_not_on_network_diagnostic", [empty, do_nothing, forever], [
			N("public", {"empty", "do_nothing"}),
			N("private", {"empty", "forever"}),
		]),
		dedent("""\
			send({}, "do_nothing", "private")
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("may_not_spoof_diagnostic", [empty, do_nothing, forever], fastN("empty", "do_nothing", "forever")),
		dedent("""\
			send({}, "forever", "public", "do_nothing")
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("allow_spoofing", [empty, do_nothing, forever], [
			N("public", {"empty", "do_nothing", "forever"}, spoofers={"empty"})
		]),
		dedent("""\
			send({}, "forever", "public", "do_nothing")
		"""),
		ExpectEvents([
			Event(Send, agent_name="empty",
				message=Message(sender="do_nothing", recipient="forever", network="public", data={})),
			Receive
		]),
		trace=True
	)
	
	await run_test(
		C("basic_interception", [empty, alice, echo], [
			N("public", {"empty", "alice", "echo"}, interceptors=OrderedSet(["empty"]), spoofers={"empty"})
		]),
		dedent("""\
			while True:
				msg = receive()
				if msg.context == "intercept":
					if "s" in msg.data:
						msg.data["s"] = msg.data["s"].upper()
					send(msg)
		"""),
		ExpectEvents([
			Event(DebugPrint, agent_name="echo", line="HELLO WORLD")
		])
	)
	
	await run_test(
		C("intercept_change_network_diagnostic", [empty, alice, echo], [
			N("public", {"empty", "alice", "echo"}, interceptors=OrderedSet(["empty"]), spoofers={"empty"})
		]),
		dedent("""\
			msg = receive()
			msg.network = "private"
			send(msg)
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("intercept_broadcast_diagnostic", [empty, alice, echo], [
			N("public", {"empty", "alice", "echo"}, interceptors=OrderedSet(["empty"]), spoofers={"empty"})
		]),
		dedent("""\
			msg = receive()
			msg.recipient = "*"
			send(msg)
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("intercept_invalid_recipient_diagnostic", [empty, alice, echo], [
			N("public", {"empty", "alice", "echo"}, interceptors=OrderedSet(["empty"]), spoofers={"empty"})
		]),
		dedent("""\
			msg = receive()
			msg.recipient = "do_nothing"
			send(msg)
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("intercept_recipient_not_on_network_diagnostic", [empty, alice, echo, forever], [
			N("public", {"empty", "alice", "echo"}, interceptors=OrderedSet(["empty"]), spoofers={"empty"}),
			N("private", {"empty", "forever"}, interceptors=OrderedSet(["empty"]), spoofers={"empty"}),
		]),
		dedent("""\
			msg = receive()
			msg.recipient = "forever"
			send(msg)
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("intercept_and_drop", [empty, alice, echo], [
			N("public", {"empty", "alice", "echo"}, interceptors=OrderedSet(["empty"]), spoofers={"empty"})
		]),
		dedent("""\
			msg = receive()
			drop()
		"""),
		ExpectEvents((Send, InterceptDrop)),
		trace=True
	)
	
	await run_test(
		C("intercepts_are_ordered", [empty, alice, echo, A("prepend-k", dedent("""\
			while True:
				msg = receive()
				if msg.context == "intercept":
					if "s" in msg.data:
						msg.data["s"] = "k " + msg.data["s"]
					send(msg)
		"""))], [N(
			"public",
			{"empty", "alice", "echo", "prepend-k"},
			interceptors=OrderedSet(["prepend-k", "empty"]),
			spoofers={"prepend-k", "empty"}
		)]),
		dedent("""\
			while True:
				msg = receive()
				if msg.context == "intercept":
					if "s" in msg.data:
						msg.data["s"] = msg.data["s"].replace(" ", "-")
					send(msg)
		"""),
		ExpectEvents([
			Event(DebugPrint, line="k-hello-world")
		])
	)
	
	await run_test(
		C("no_message_to_drop_diagnostic", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			from time import sleep
			
			drop()
			sleep(0.1)
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("may_not_set_solutions_diagnostic", [empty, do_nothing], fastN("empty", "do_nothing")),
		dedent("""\
			set_solution("foo")
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("partial_solution_no_early_exit", [empty, solutions], fastN("empty", "solutions")),
		dedent("""\
			from time import sleep
			
			sleep(0.1)  # give time for the solutions to be loaded
			solve("0.2")
		"""),
		ExpectResult(exit_reason=ExitReason.AGENT_FINISHED, score=0.2),
		ExpectEvents([
			SetSolutions, SetSolutions, SetSolutions, SetSolutions, SetSolutions,
			Event(Solve, agent_name='empty', s='0.2', successful=True, score=0.2),
		]),
		trace=True
	)
	
	await run_test(
		C("most_recent_solve_supersedes", [empty, solutions], fastN("empty", "solutions")),
		dedent("""\
			from time import sleep
			
			sleep(0.1)  # give time for the solutions to be loaded
			solve("0.2")
			solve("0.8")
			solve("0.6")
		"""),
		ExpectResult(exit_reason=ExitReason.AGENT_FINISHED, score=0.6),
		ExpectEvents([
			SetSolutions, SetSolutions, SetSolutions, SetSolutions, SetSolutions,
			Event(Solve, agent_name='empty', s='0.2', successful=True, score=0.2),
			Event(Solve, agent_name='empty', s='0.8', successful=True, score=0.8),
			Event(Solve, agent_name='empty', s='0.6', successful=True, score=0.6)
		]),
		trace=True
	)
	
	await run_test(
		C("complete_solve_ends_early", [empty, solutions], fastN("empty", "solutions")),
		dedent("""\
			from time import sleep
			
			sleep(0.1)  # give time for the solutions to be loaded
			solve("0.2")
			solve("1.0")
			solve("0.6")
		"""),
		ExpectResult(exit_reason=ExitReason.SOLVED, score=1.0),
		trace=True
	)
	
	await run_test(
		C("invalid_solution_diagnostic", [empty, forever], fastN("empty", "forever")),
		dedent("""\
			solve("foo")
		"""),
		ExpectEvents([
			Event(Solve, agent_name='empty', s='foo', successful=False, score=None),
			Diagnostic
		]),
		trace=True
	)
	
	await run_test(
		C("solution_removal", [empty, solutions, A("solution_remover", dedent("""\
			from time import sleep
			
			sleep(0.05)
			remove_solution("1.0")
		"""), may_set_solution=True)], fastN("empty", "solutions", "solution_remover")),
		dedent("""\
			from time import sleep
			
			sleep(0.1)
			solve("1.0")
		"""),
		ExpectResult(exit_reason=ExitReason.AGENT_FINISHED, score=0.0)
	)
	
	await run_test(
		C("solution_out_of_range_diagnostic", [admin, do_nothing], fastN("admin", "do_nothing")),
		dedent("""\
			set_solutions({"foo": 2})
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	await run_test(
		C("score_not_float_diagnostic", [admin, do_nothing], fastN("admin", "do_nothing")),
		dedent("""\
			import sys; sys.stdout = send.__globals__["_real_stdout"]
			print('{"request_type": "set_solutions", "solutions": {"foo": "yes"}}')
		"""),
		ExpectEvents((Diagnostic,))
	)
	
	if test_num == tests_passed:
		cprint(f"Ran {test_num} tests; {tests_passed} tests passed.", "green", attrs=["bold"])
	else:
		cprint(f"Ran {test_num} tests; ", "red", end="")
		cprint(f"{tests_passed} passed.", "red", attrs=["bold"])


if __name__ == "__main__":
	asyncio.run(main())

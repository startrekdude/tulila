"""The Tulila Agent Loader.

This is run by the simulator inside the sandbox and is responsible for
reading in the agent code from standard in, setting up the execution
environment for the agent, and ultimately executing the agent.

Setting up the execution environment consists of:
  - Providing methods for the agent to interact with the simulator.
    (Ultimately over standard out, though this detail is abstracted)
  - Redirecting standard out to standard error so print()s and such
    go to the right place.
  - Making a few more miscellaneous changes intended to help Python and
    the sandbox work a bit better together. (None of these changes are
    required for security; the sandbox does that all by itself.)
"""

import json
import sys

from dataclasses import dataclass
from functools import update_wrapper
from os import environ
from select import select
from time import perf_counter_ns
from types import ModuleType

from typing import Any, Optional


# Keep a reference to the real standard out; this is how we talk to
# the simulator. Later, we redirect standard out to standard error
# as we don't want print()s and such in the agent code interpreted
# as requests to the simulator.
_real_stdout = sys.stdout

# Keep a reference to the real exception handler of last resort.
# We pre-process exceptions to remove loader frames from the traceback.
_real_excepthook = sys.excepthook


def _input_or_timeout(timeout):
	"""Return a line of input or timeout (returning None).
	
	A timeout value of -1 will be interpreted as allowing an infinite wait.
	
	Note that this code may not return in `timeout` time if data _not_ ending
	with a newline is placed in standard in; as such, it is not safe in the
	general case. Here, however, we know the simulator only writes complete
	lines to standard in at a time.
	"""
	if timeout == -1:
		return sys.stdin.readline()
	elif select((sys.stdin,), (), (), timeout)[0]:
		return sys.stdin.readline()
	else:
		return None


@dataclass
class Message:
	"""Represent a message to/from another agent that was received or is to be sent.
	
	The context field represents why the message was received (direct, monitor,
	or intercept) and is not used when sending messages.
	"""
	sender   : Optional[str]
	recipient: str
	network  : str
	data     : dict[str, Any]
	context  : Optional[str] = None


def send(message_or_data, recipient=None, network="*", sender=None):
	"""Send a message to another agent (or modify an intercepted message).
	
	The default network of "*" will be interpreted by the simulator code as "all
	networks I share with the recipient" for a non-broadcast recipient.
	
	You may broadcast to all recipients with "*", either on a given network
	or all networks (again with "*").
	"""
	if isinstance(message_or_data, Message):
		message = message_or_data
	else:
		message = Message(sender, recipient, network, message_or_data)
	
	if message.sender is not None and not isinstance(message.sender, str):
		raise TypeError(f"sender must be str, not {type(message.sender).__name__}")
	if not isinstance(message.recipient, str):
		raise TypeError(f"recipient must be str, not {type(message.recipient).__name__}")
	if not isinstance(message.network, str):
		raise TypeError(f"network must be str, not {type(message.network).__name__}")
	if not isinstance(message.data, dict):
		raise TypeError(f"data must be dict, not {type(message.data).__name__}")
	
	print(json.dumps({
		"request_type": "send",
		"sender"      : message.sender,
		"recipient"   : message.recipient,
		"network"     : message.network,
		"data"        : message.data,
	}), file=_real_stdout)


def receive(*, timeout=-1):
	"""Receive a message from another agent.
	
	The message will not necessarily be addressed to you, if you are
	a monitor or interceptor on a network.
	"""
	line = _input_or_timeout(timeout)
	if not line:
		return None
		
	o = json.loads(line)
	return Message(
		o["sender"],
		o["recipient"],
		o["network"],
		o["data"],
		o["context"],
	)


def drop():
	"""Drop an intercepted message (the least recent such message that has not been handled).
	
	This is not meaningful for agents who are not interceptors on any network."""
	print(json.dumps({"request_type": "drop"}), file=_real_stdout)


def solve(s):
	"""Try to solve the challenge with the given solution string."""
	print(json.dumps({
		"request_type": "solve",
		"s"           : str(s),
	}), file=_real_stdout)


def set_solutions(solutions):
	"""Modify the set of solution strings that will be accepted for this challenge run.
	
	Agents must have permission to do this.
	
	The solutions parameter should be a mapping between solution strings and scores
	between 0 and 1; a score of 0 will be interpreted as removing the string as a
	solution if it is so registered.
	"""
	print(json.dumps({
		"request_type": "set_solutions",
		"solutions"   : solutions,
	}), file=_real_stdout)


def set_solution(s, score=1):
	"""Add a solution string that will be accepted for this challenge run with the specified score.
	
	Agents must have permission to do this.
	"""
	if not isinstance(s, str):
		raise TypeError(f"s must be str, not {type(s).__name__}")
	if not isinstance(score, (float, int)) or isinstance(score, bool):
		raise TypeError(f"score must be float or int, not {type(score).__name__}")
	if not (0 < score <= 1):
		raise TypeError(f"score must be between 0 and 1")
	set_solutions({s: score})


def remove_solutions(solutions):
	"""Remove a set of solution strings from this challenge run.
	
	Agents must have permission to do this.
	"""
	set_solutions({solution: 0 for solution in solutions})


def remove_solution(s):
	"""Remove a solution string from this challenge run.
	
	Agents must have permission to do this.
	"""
	if not isinstance(s, str):
		raise TypeError(f"s must be str, not {type(s).__name__}")
	remove_solutions([s])


def mark_solved(score=1):
	"""Directly mark this challenge as solved with the specified score.
	
	Agents must have permission to do this."""
	set_solution("__solved__", score)
	solve("__solved__")


def _usleep(us):
	"""Wait for a specified number of microseconds, then return.
	
	This function uses a busy-loop and is much more precise than time.sleep
	for intervals less than ~5 milliseconds.
	"""
	start = perf_counter_ns()
	while perf_counter_ns() < start + us * 1000:
		pass


def throttled_print(*args, **kwargs):
	"""Print a message, wait 100 microseconds, and return.
	
	This function accepts the same arguments as print() - in fact, it simply
	forwards whatever (positional+keyword) arguments it is given to print().
	
	This function exists because students - one of the intended audiences of
	Tulila - will inevitably submit solutions that just print() over and over
	in a loop with no delay. Tulila and Tulila Server are both equipped to
	handle this without negative effects on concurrent simulations, so this is
	OK and not something that needs to, strictly speaking, be _prevented_.
	(a.k.a. this is not a security feature!)
	
	However, one component that is ill-equipped to handle a torrent of messages
	is the user's browser. Tulila Server will send all debug messages over a
	WebSocket to the user's browser as fast as possible (note that messages may
	be dropped if they are not accepted fast enough). The browser will not have
	a very fun time rendering >100000 new lines every second. So, to save
	challenge recipients from themselves, we throttle debug output to at most
	10000 prints/sec.
	
	This applies to debug output only - messages continue to be relayed as fast
	as they are sent and accepted. And, I do not feel that 10000 prints/sec
	is at all limiting for debug output. If this is really a problem, users may
	simply print() messages with multiple lines of data.
	"""
	print(*args, **kwargs)
	_usleep(100)


def _excepthook(type, value, traceback):
	"""Remove loader frames from an exception before display.
	
	The agent loader is an implementation detail that should be hidden as much
	as possible from the challenge recipient; this helps with that.
	
	Note, of course, that no part of the sandbox is implemented in the agent
	loader and, e.g., learning the agent loader's filename from a traceback
	and dumping its code does not help escape the sandbox even a little bit.
	This is not a security feature, merely a quality-of-life improvement.
	"""
	# First, trim frames off the start of the traceback
	new_tb = None
	tb = traceback
	while tb.tb_next:
		if tb.tb_frame.f_code.co_filename != __file__:
			new_tb = tb
			break
		tb = tb.tb_next
	
	# Then, trim frames off the end of the traceback
	while tb.tb_next:
		if tb.tb_next.tb_frame.f_code.co_filename == __file__:
			tb.tb_next = None
			break
		tb = tb.tb_next
	
	value.__traceback__ = new_tb
	return _real_excepthook(type, value, new_tb)


_INJECTED_GLOBALS = {
	"Message"         : Message,
	"send"            : send,
	"receive"         : receive,
	"drop"            : drop,
	"solve"           : solve,
	"set_solutions"   : set_solutions,
	"set_solution"    : set_solution,
	"remove_solutions": remove_solutions,
	"remove_solution" : remove_solution,
	"mark_solved"     : mark_solved,
}


def main():
	"""Read in the agent's code and execute it an appropriate environment."""
	# The code will be sent as: <length>\n<code>\n
	code = sys.stdin.read(int(input()))
	if (c := sys.stdin.read(1)) != "\n":
		raise RuntimeError(f"expected '\n', got {c!r}")
	
	# Tell Python it isn't able to launch any subprocesses
	# The sandbox will enforce this regardless, but you get nicer error
	# messages if you tell Python
	import subprocess
	if hasattr(subprocess, "_can_fork_exec"):
		subprocess._can_fork_exec = False
	del subprocess
	
	# Use line buffering on both standard out and error
	# (it is not default on standard out when piped)
	sys.stdout.reconfigure(line_buffering=True)
	sys.stderr.reconfigure(line_buffering=True)
	
	# All prints from the agent code should go to standard error
	# Standard out goes to the simulator and should only be used directly
	# by the injected globals, above
	sys.stdout = sys.stderr
	
	# Install our modified exception handler of last resort that
	# removes loader frames before printing the exception.
	sys.excepthook = update_wrapper(_excepthook, sys.excepthook)
	
	# Hide the sandboxing mechanism - this is an implementation detail
	# that need not be exposed to agent code. (The sandbox is secure
	# regardless, of course.)
	environ.pop("LD_PRELOAD", None)
	environ.pop("_PLEDGE", None)
	
	# Hide argv as it contains the path to the agent loader - also an
	# implementation detail that need not be exposed to agent code.
	sys.argv = []
	
	# Any use of input is likely an error - hide it
	# Communication with the simulator should be done only through the
	# methods we provide (the alternative is unnecessarily confusing)
	new_builtins = ModuleType(__builtins__.__name__)
	new_builtins.__dict__.update(__builtins__.__dict__)
	del new_builtins.__dict__["input"]
	
	# Install the throttled version of print (see above comment)
	new_builtins.__dict__["print"] = update_wrapper(throttled_print, print)
	
	injected_globals = _INJECTED_GLOBALS | {"__builtins__": new_builtins}
	
	# For module semantics, set locals=globals
	exec(code, locals=injected_globals, globals=injected_globals)


if __name__ == "__main__":
	main()

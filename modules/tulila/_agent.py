"""Represent an agent in Tulila's object model.

An agent consists of the following key attributes:
  - The agent's name.
  - Whether or not the agent may set the solution.
  - The code for the agent's implementation.
  - The dependencies required for the agent to run.
as well as arbitrary "metadata" attributes.

This module contains the code to represent and launch an agent.
Additionally, Tulila's sandboxing implementation, relying on Justine
Tunney's pledge utility, lives here.

Once launched, the simulator interacts with the agent through
standard in and out. The agent is unable to write to anything other
than standard out and error.
"""

from __future__ import annotations

import atexit
import importlib.resources
import subprocess

from asyncio import StreamReader, StreamWriter
from asyncio.subprocess import create_subprocess_exec
from dataclasses import dataclass, field
from functools import partial
from os import environ
from os.path import dirname, expanduser
from subprocess import PIPE

import venvcache

from ._config import VM_LIMIT

from collections.abc import Collection, Mapping
from typing import Final, Optional, Protocol, TypeGuard, TYPE_CHECKING

if TYPE_CHECKING:  # avoid circular import chain
	from ._types import Metadata


__all__ = (
	"Agent",
	"ProcessProtocol",
	"PipedProcess",
)


# Make sure both pledge and unveil are supported on this system
# (should be true for a kernel newer than ~2021), and fail otherwise
# It is better to not run at all than run insecurely.
# (and we all know no one reads warning messages)
# Uses pledge's -T (test) feature
def _test(what: str) -> bool:
	"""Test to see if a feature (either pledge or unveil) is supported."""
	try:
		return subprocess.run(["pledge", "-T", what]).returncode == 0
	except Exception:
		return False

if not (_test("pledge") and _test("unveil")):
	raise RuntimeError("pledge and/or unveil is not available (or the binary is not installed)")

del _test


# Get the path to the Tulila Agent Loader, the script that runs in the
# sandbox and sets up the execution environment for the agent.
# It is stored as a package resource.
#
# This is complicated because Python supports importing packages from
# zip files, and indeed has comprehensive extension hooks for the
# import system, so there's no particular guarantee the file we want
# is on disk already (though it will be in 99% of cases).
#
# For this reason importlib.resources.path returns a context manager
# that will extract the desired file to a temporary path and then return
# that (and delete it after use). I would like the file to be available
# for the entire lifetime of the program (in particular, I don't want
# to make a new one for each agent we launch) and the following is how
# you spell that when using context managers.
# 99% of the time this code is a no-op and the file on disk will be used
_ctx = importlib.resources.path(__package__, "rsrc/tulila-agent-loader.py")
_AGENT_LOADER_PATH: Final = str(_ctx.__enter__())
atexit.register(partial(_ctx.__exit__, None, None, None))
del _ctx


# A sanitized environment with minimal information to give agent processes
_AGENT_ENV: Final[Mapping[str, str]] = {
	# Hard dependency on PATH and USER being set
	"PATH": environ["PATH"],
	"USER": environ["USER"],
	
	# For HOME and LANG, we provide sensible defaults
	# Note that pledge requires that home be a writable directory
	"HOME": expanduser("~"),
	"LANG": environ.get("LANG", "C"),
	
	# Important as agent processes may not write any files
	"PYTHONDONTWRITEBYTECODE": "1",
}


@dataclass(frozen=True, kw_only=True)
class Agent:
	"""Represent and launch an agent.
	
	This class and its fields are logically immutable. Modifying any of the fields
	of this class via mutable references retained from before it was instantiated
	is unsafe and _will_ lead to undefined behaviour. 
	"""
	name            : str
	may_set_solution: bool
	deps            : Collection[str]
	code            : Optional[str]
	metadata        : Metadata = field(default_factory=dict)
	
	def __post_init__(self) -> None:
		"""Validate the Agent's attributes.
		
		In particular, the name may not start with an asterisk as that
		is used by the simulator for broadcast messages.
		"""
		if not self.name:
			raise ValueError("name must not be empty")
		
		if self.name.startswith("*"):
			raise ValueError("name may not start with '*'")
	
	async def _launch(self) -> PipedProcess:
		"""Launch the agent.
		
		This launches the agent in a sandbox and returns a Process with stdin,
		stdout, and stderr piped. The caller may interact with the sandboxed
		agent through these handles.
		
		The agent will be launched in a virtual environment with all requested
		dependencies.
		"""
		assert self.code is not None
		
		interpreter = await venvcache.setup(self.deps)
		
		# Launch the sandbox
		proc = await create_subprocess_exec(
			"pledge",
			
			# Run process with maximum "niceness" (only use idle cycles)
			"-n",
			
			# Do not log violations to stderr
			"-q",
			
			# Process may allocate at most VM_LIMIT bytes RAM
			"-M", str(VM_LIMIT),
			
			# Communicate over stdin/out/err, read files if permitted
			# check tty details, load executable code (shared libraries)
			# Only files permitted by -v or implied may be read
			# No access whatsoever is given to system calls that write files
			# (even if access would otherwise be given via -v)
			"-p", "stdio rpath tty prot_exec",
			
			# stdio implies reading /dev/null, /dev/urandom, /dev/stdin, etc
			# the interpreter being dynamically linked implies /lib, /usr/lib, etc
			
			# Allow RO access to the agent loader and venv
			"-v", _AGENT_LOADER_PATH,
			"-v", dirname(dirname(interpreter)),
			
			interpreter, _AGENT_LOADER_PATH,
			env=_AGENT_ENV,
			stdin=PIPE, stdout=PIPE, stderr=PIPE
		)
		
		assert _is_piped_process(proc)
		
		# Send the agent code to the loader
		proc.stdin.write(
			str(len(self.code)).encode()
			+ b"\n"
			+ self.code.encode()
			+ b"\n"
		)
		await proc.stdin.drain()
		
		return proc


# The following two classes and one method is boilerplate that teaches mypy
# about a new type, PipedProcess---"like an asyncio.subprocess.Process, but
# we know for sure that std{in,out,err} are not None". It's a bit wordy, but
# preferable to adding, e.g., "proc.stdin is not None" before every time the
# rest of the code uses it.
# ProcessProtocol is adapted from the typeshed stub definition of Process.
class ProcessProtocol(Protocol):
	"""Represent an object with identical members to asyncio.subprocess.Process."""
	stdin : Optional[StreamWriter]
	stdout: Optional[StreamReader]
	stderr: Optional[StreamReader]
	pid   : int
	
	@property
	def returncode(self) -> Optional[int]: ...
	
	async def wait(self) -> int: ...
	def send_signal(self, signal: int) -> None: ...
	def terminate(self) -> None: ...
	def kill(self) -> None: ...
	async def communicate(self, input: bytes | bytearray | memoryview | None = None) -> tuple[bytes, bytes]: ...

class PipedProcess(ProcessProtocol, Protocol):
	"""Represent a ProcessProtocol with non-None stdin, stdout, and stderr."""
	stdin : StreamWriter
	stdout: StreamReader
	stderr: StreamReader

def _is_piped_process(proc: ProcessProtocol) -> TypeGuard[PipedProcess]:
	"""Verify a ProcessProtocol meets the additional requirements to be considered a PipedProcess."""
	return (
		proc.stdin is not None
		and proc.stdout is not None
		and proc.stderr is not None
	)

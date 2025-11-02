"""Create and cache virtual environments with requested dependencies.

This module creates virtual environments with a requested set of dependencies,
given in pip "requirement specifier" format. These virtual environments are
cached and will be re-used if available. Optional functionality to track used
virtual environments, and remove unused virtual environments from the cache, is
available.

Similar to Python's random module, this module can be used either by instantiating
VenvCache objects as needed or by using the per-process global VenvCache, whose
instance methods are exported as module methods.

A simple usage example to run a script with PyCryptodome is as follows:
  intrp_path = await venvcache.setup(["PyCryptodome"])
  proc = await create_subprocess_exec(intrp_path, "/path/to/script.py")
"""

import os
import os.path
import venv

from asyncio.subprocess import create_subprocess_exec, DEVNULL
from contextlib import suppress
from hashlib import sha256
from os import listdir
from os.path import abspath, expanduser, isdir, isfile
from shutil import rmtree
from string import hexdigits

from collections.abc import Collection
from typing import Final, Optional


__all__ = (
	"VenvCache",
	"Deps",
	"set_directory",
	"setup",
	"interpreter",
	"mark_venv_used",
	"includes",
	"clean",
)


type Deps = Collection[str]


class VenvCache:
	"""Create and cache virtual environments with requested dependencies.
	
	This class represents a virtual environment cache that uses a specific
	filesystem path. It provides services to create a new virtual environment
	with a requested set of dependencies, and will track environments that
	have been completely built and environments that have been used.
	
	Optionally, consumers may call the .clean() method to delete unused
	virtual enviroments; they may be re-created at any time.
	"""
	
	@staticmethod
	def _hash_deps_list(deps: Deps) -> str:
		"""Hash a dependency list into a unique key."""
		return sha256("\n".join(sorted(deps)).encode()).hexdigest()
	
	def __init__(self, path: str):
		"""Create a VenvCache using the specified path."""
		self.set_directory(path)
	
	def _load(self) -> None:
		"""Load the set of built virtual environments."""
		self._built_venvs: set[str] = set()
		
		# The set of built virtual environments is stored in a file in each
		# venv cache directory. It is a newline-separated list of the hash IDs
		# of each virtual environment.
		if isfile(self._built_venvs_path):
			with open(self._built_venvs_path) as f:
				for hash_id in f.read().splitlines():
					
					# Since we're loading data from the filesystem, be tolerant of
					# nonsense we would never write. Only add the line to the set
					# of built venvs if it looks like a SHA256 hash and the
					# corresponding directory exists and is a venv.
					hash_id = hash_id.lower()
					if (
						all(c in hexdigits for c in hash_id)
						and len(hash_id) == 64
						and isfile(os.path.join(self.path, hash_id, "pyvenv.cfg"))
					):
						self._built_venvs.add(hash_id)
	
	def _save(self) -> None:
		"""Save the set of built venvs to the filesystem."""
		with open(self._built_venvs_path, "w") as f:
			f.write("\n".join(self._built_venvs))
			f.write("\n")
	
	async def _install_deps(self, deps: Deps) -> None:
		"""Install the requested dependencies in a virtual enviroment."""
		hash_id = VenvCache._hash_deps_list(deps)
		proc = await create_subprocess_exec(
			self._interpreter_path(hash_id),
			"-m", "pip", "install", "--disable-pip-version-check", "--", *deps,
			stdout=DEVNULL, stderr=DEVNULL
		)
		code = await proc.wait()
		if code != 0:
			raise RuntimeError(f"pip exited with non-zero exit code {code}")
	
	def _interpreter_path(self, hash_id: str) -> str:
		"""Return the path to the Python interpreter in a given venv."""
		if os.name != "nt":
			return os.path.join(self.path, hash_id, "bin", "python3")
		else:
			return os.path.join(self.path, hash_id, "Scripts", "python.exe")
	
	def set_directory(self, path: str) -> None:
		"""Point this VenvCache to a new directory."""
		self.path = abspath(path)
		self._used_venvs: set[str] = set()
		self._load()
	
	async def setup(self, deps: Deps) -> str:
		"""Create, if required, a virtual environment with the requested dependencies.
		
		Returns the path to the Python interpreter in the requested virtual environment.
		"""
		hash_id = VenvCache._hash_deps_list(deps)
		if hash_id in self._built_venvs:
			self._used_venvs.add(hash_id)
			return self._interpreter_path(hash_id)
		
		venv_path = os.path.join(self.path, hash_id)
		try:
			venv.create(
				venv_path,
				clear=True,
				with_pip=True,
				symlinks=(os.name == "posix")
			)
			if len(deps) > 0:
				await self._install_deps(deps)  # Install deps
		except Exception as e:
			# If setting up the virtual environment failed for any reason, clean up the
			# directory on a best-effort basis.
			with suppress(Exception):
				rmtree(venv_path)
			
			raise e from None
		else:
			# Only mark the venv as fully built once all steps complete successfully.
			self._built_venvs.add(hash_id)
			self._used_venvs.add(hash_id)
			self._save()
			
			return self._interpreter_path(hash_id)
	
	def interpreter(self, deps: Deps) -> Optional[str]:
		"""Return the path to the interpreter in a venv with the given dependencies, if one exists."""
		hash_id = VenvCache._hash_deps_list(deps)
		if hash_id in self._built_venvs:
			self._used_venvs.add(hash_id)
			return self._interpreter_path(hash_id)
		return None
	
	mark_venv_used = interpreter
	
	def includes(self, deps: Deps) -> bool:
		"""Return if this VenvCache contains a virtual enviroment with the requested dependencies."""
		return VenvCache._hash_deps_list(deps) in self._built_venvs
	
	def clean(self) -> None:
		"""Delete unused virtual environments from this VenvCache."""
		if not isdir(self.path): return
		
		# Explicitly iterate over all directories, not just ones that correspond to built venvs
		# This could remove partially-built venvs or junk that other processes placed here
		for name in listdir(self.path):
			name_path = os.path.join(self.path, name)
			if isdir(name_path) and name not in self._used_venvs:
				rmtree(name_path)
				self._built_venvs.discard(name)
		self._save()
	
	@property
	def _built_venvs_path(self) -> str:
		"""Return the path to the file that contains the set of built venvs."""
		return os.path.join(self.path, "built-venvs")


_inst = VenvCache(expanduser("~/.venvcache"))
set_directory  : Final = _inst.set_directory
setup          : Final = _inst.setup
interpreter    : Final = _inst.interpreter
mark_venv_used : Final = _inst.mark_venv_used
includes       : Final = _inst.includes
clean          : Final = _inst.clean
del _inst

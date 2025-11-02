"""Load Tulila challenges from .json5 files.

This module contains the routines to load Tulila challenges (and thus, indirectly, agents
and networks) from JSON5 files on disk. Any data present in the JSON5 file that is not
used to construct the challenge will be placed in the Challenge's metadata attribute
(or an Agent or Network's, if it is so nested).

Validation of internal challenge structure and consistency happens in the __post_init__
methods in _types. Validation of the _types_ of data happens here, and any data that is
not of the expected type will result in an error being raised.

As this module deals with unstructured data, it is type-checked with allow_any_expr set.
(Of course, once a JSON5 file has been successfully loaded by this module, the objects
that are created all have the right types - so the other modules use disallow_any_expr.)

Internally, this module is structured as a series of functions that pop a key from a
mapping, check its type, and either raise an error or return the datum as appropriate. 
Some of these build on each other---e.g., _pop_str_list builds on _pop_list and
_pop_str_set builds on_pop_str_list. After these functions are functions that load
data into an object using the pop methods. Once all of the keys corresponding to
the object's attributes are popped off, the remainder of the mapping is used as
the object's metadata.
"""

import os.path

from functools import partial
from glob import glob
from os.path import abspath, dirname

import pyjson5 as json5

from ordered_set import OrderedSet

from ._agent import Agent
from ._types import Challenge, Network

from collections.abc import (
	Callable,
	Collection,
	Mapping,
	MutableMapping,
	MutableSequence,
	Set,
	Sequence,
)
from typing import Any


__all__ = (
	"load_challenge",
	"load_challenges",
)


def _verify_key(o: Mapping[Any, Any], key: str) -> None:
	"""Verify a key is present in a mapping and raise an error if not."""
	if key not in o:
		raise RuntimeError(f"missing {key}")


def _pop_str(o: MutableMapping[Any, Any], key: str) -> str:
	"""Pop a string from a mapping. If the value is not a string, raise an error."""
	_verify_key(o, key)
	val = o.pop(key)
	if not isinstance(val, str):
		raise RuntimeError(f"{key}: expected str, got {type(val).__name__}")
	return val


def _pop_float(o: MutableMapping[Any, Any], key: str) -> float:
	"""Pop a float from a mapping. If the value is not numeric, raise an error.
	
	Integers will be coerced into a float.
	"""
	_verify_key(o, key)
	val = o.pop(key)
	
	# Explicitly exclude bool, as it's technically a subclass of int...
	if not isinstance(val, (float, int)) or isinstance(val, bool):
		raise RuntimeError(f"{key}: expected float, got {type(val).__name__}")
	return float(val)


def _pop_bool(o: MutableMapping[Any, Any], key: str) -> bool:
	"""Pop a boolean from a mapping. If the value is not a boolean, raise an error."""
	_verify_key(o, key)
	val = o.pop(key)
	if not isinstance(val, bool):
		raise RuntimeError(f"{key}: expected bool, got {type(val).__name__}")
	return val


def _pop_list(o: MutableMapping[Any, Any], key: str) -> MutableSequence[Any]:
	"""Pop a list from a mapping. If the value is not a list, raise an error."""
	_verify_key(o, key)
	val = o.pop(key)
	if not isinstance(val, list):
		raise RuntimeError(f"{key}: expected list, got {type(val).__name__}")
	return val


def _pop_str_list(o: MutableMapping[Any, Any], key: str) -> Collection[str]:
	"""Pop a list of non-empty strings from a mapping.
	
	If:
	  - the value is not a list
	  - the value contains elements not of type str
	  - any of the strings are empty
	...raise an error.
	"""
	val = _pop_list(o, key)
	for i in range(len(val)):
		if not isinstance(val[i], str):
			raise RuntimeError(f"{key} at position {i}: expected str, got {type(val).__name__}")
		if not val[i]:
			raise RuntimeError(f"{key} at position {i}: string must not be empty")
	return val


def _pop_str_set(o: MutableMapping[Any, Any], key: str) -> Set[str]:
	"""Pop a list of strings from a mapping and convert it into a set.
	
	If the list contains duplicate values, raise an error.
	"""
	val     = _pop_str_list(o, key)
	set_val = frozenset(val)
	if len(val) > len(set_val):
		raise RuntimeError(f"{key}: may not contain duplicate values")
	return set_val


def _pop_str_ordered_set(o: MutableMapping[Any, Any], key: str) -> OrderedSet[str]:
	"""Pop a list of strings from a mapping and convert it into an ordered set.
	
	If the list contains duplicate values, raise an error.
	
	(This is distinct from _pop_str_set instead of, e.g., just another parameter
	 to keep the type-checker happy.)
	"""
	val = _pop_str_list(o, key)
	set_val = OrderedSet(val)
	if len(val) > len(set_val):
		raise RuntimeError(f"{key}: may not contain duplicate values")
	return set_val


def _load_agent(relative_to: str, o: MutableMapping[Any, Any]) -> Agent:
	"""Load an Agent object from a mapping.
	
	If a relative path is specified in the mapping's code field, it will be resolved
	relative to the relative_to parameter when loading the agent's code.
	
	If may_set_solution is not specified, it will default to False.
	If deps is not specified, it will default to an empty list (i.e., no dependencies).
	
	After all fields describing the agent have been removed from the mapping, the
	rest of the mapping will be used as the agent's metadata attribute.
	"""
	if "code" in o:
		# NOTE: if code is an absolute path, it will be used as-is
		# This is intended behaviour; we _allow_, but do not _mandate_, the use of relative paths
		with open(os.path.join(dirname(relative_to), _pop_str(o, "code"))) as f:
			code = f.read()
	else: code = None
	
	return Agent(
		name             = _pop_str(o, "name"),
		may_set_solution = _pop_bool(o, "may_set_solution") if "may_set_solution" in o else False,
		deps             = _pop_str_list(o, "deps") if "deps" in o else [],
		code             = code,
		metadata         = o,
	)


def _load_network(o: MutableMapping[Any, Any]) -> Network:
	"""Load a Network object from a mapping.
	
	After all fields describing the network have been removed from the mapping,
	the rest of the mapping will be used as the network's metadata attribute.
	"""
	return Network(
		name         = _pop_str(o, "name"),
		members      = _pop_str_set(o, "members"),
		monitors     = _pop_str_set(o, "monitors"),
		interceptors = _pop_str_ordered_set(o, "interceptors"),
		spoofers     = _pop_str_set(o, "spoofers"),
		metadata     = o,
	)


def _pop_object_list[T](
	o: MutableMapping[Any, Any],
	key: str,
	factory_fn: Callable[[MutableMapping[Any, Any]], T],
) -> Collection[T]:
	"""Pop a list of objects from a mapping.
	
	These objects are themselves represented as mappings and will be "re-hydrated" into
	the appropriate type using factory_fn.
	
	If the key does not correspond to a value of type list, or the list contains any
	values that are not mappings, an error will be raised.
	
	If factory_fn raises an error loading a mapping into an object, additional
	information will be added indicating which element is at fault (and the error will
	be re-raised).
	"""
	vals = _pop_list(o, key)
	for i in range(len(vals)):
		val = vals[i]
		if not isinstance(val, dict):
			raise RuntimeError(f"{key} at position {i}: expected dict, got {type(val).__name__}")
		
		try:
			vals[i] = factory_fn(val)
		except (ValueError, RuntimeError) as e:
			e.args = (f"{key} at position {i}: " + e.args[0],) + e.args[1:]
			raise
	
	return vals


def load_challenge(path: str) -> Challenge:
	"""Load a challenge from a JSON5 file on disk.
	
	Agent code will be loaded relative to the provided path.
	
	Any keys/values present at the top level in the JSON5 file that are not used
	to construct the Challenge will be stored in its metadata attribute.
	
	Additionally, the absolute path from which the challenge was loaded will be included
	in the Challenge's metadata attribute under key 'path'.
	"""
	path = abspath(path)
	with open(path) as f:
		o = json5.load(f)
	
	if not isinstance(o, dict):
		raise RuntimeError(f"JSON5 object: expected dict, got {type(o).__name__}")
	
	return Challenge(
		name           = _pop_str(o, "name"),
		time_limit     = _pop_float(o, "time_limit"),
		cpu_time_limit = _pop_float(o, "cpu_time_limit"),
		solution       = _pop_str(o, "solution") if "solution" in o else None,
		agents         = _pop_object_list(o, "agents", partial(_load_agent, path)),
		networks       = _pop_object_list(o, "networks", _load_network),
		metadata       = o | {"path": path},
	)


def load_challenges(*dir_paths: str, unique_names: bool = True) -> Sequence[Challenge]:
	"""Load all challenges from a list of directories.
	
	This is a convenience function that will recursively locate all .json5 files
	in each of the specified directories and load them as a challenge.
	
	It will then verify that all of the loaded challenges have unique names before
	returning them (this behaviour can be suppressed by setting unique_names = False).
	
	If any of the directories passed in contain a .json5 file that is not a valid
	challenge, an error will be raised.
	
	The resulting list of challenges will be ordered first by the list of directories
	that was passed in---i.e., all challenges loaded from directory 1 will appear, then
	all challenges from directory 2, and so on---then lexicographically by absolute path
	within the directory. It is therefore possible to manipulate the order of challenges
	by modifying their name (or path) as, e.g., 01.json5 will come before 02.json5.
	
	This obviates the need to include any ordering information in the challenges themself,
	and is a cool trick I picked up from, um, _every Unix daemon ever_ (or, more specifically,
	the .d "configuration directory" mechanism that is quite common on Linux these days).
	"""
	chals: MutableSequence[Challenge] = []
	
	for dir_path in dir_paths:
		dir_path = abspath(dir_path)
		
		paths = glob(dir_path + "/**/*.json5", recursive=True)
		paths.sort()
		
		# Load the challenges one at a time; this way, if one of them fails to load,
		# we can "augment" the resultant exception to indicate which
		for path in paths:
			try:
				chals.append(load_challenge(path))
			except (ValueError, RuntimeError) as e:
				e.args = (f"{path!r}: " + e.args[0],) + e.args[1:]
				raise
	
	if unique_names and len(set(chal.name for chal in chals)) != len(chals):
		raise RuntimeError("all challenges must have unique names")
	
	return chals

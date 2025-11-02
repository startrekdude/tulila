"""Visualize a challenge's agents, networks, and the relationships between them.

This module contains functionality to build a Graphviz graph from the agents
and networks in a challenge and render it to SVG by shelling out to Graphviz.

That this module uses Graphviz can be considered an implementation detail
[though the name does collide :)] --- the public API of the module returns
an SVG image for a challenge directly.

Note to installers: for best results, the Latin Modern Sans font should be
installed and available to Graphviz on the server where Tulila Server is
installed; the font metrics are required for Graphviz to properly lay out
text (though it is never rendered server-side).

To avoid unnecessary computation, this module also implements a fairly simple
on-disk cache of the SVGs generated for challenges: they are compressed with
Zstandard and stored in the ~/gvcache directory. To remove unused files from
this cache, this module also exports a function that accepts as an argument
all of the challenges that are still in use.
"""

import os
import os.path
import re
import subprocess

from asyncio import create_subprocess_exec
from functools import partial
from hashlib import sha256
from io import StringIO
from os import listdir, makedirs, stat
from os.path import expanduser, isdir, isfile
from shutil import rmtree, which
from subprocess import DEVNULL, PIPE

import pyzstd as zstd

from ._challenges import (
	AgentWithMetadata as Agent,
	ChallengeWithMetadata as Challenge,
	NetworkWithMetadata as Network,
)

from collections.abc import Iterable
from typing import Optional


__all__ = (
	"render",
	"discard_unused_graphs",
)


# Validate that Graphviz is installed...
if not which("dot"):
	raise RuntimeError("graphviz is required but not installed")

# ...and that it's a new enough version to support svg_inline
# NOTE: the version of Graphviz shipped in Ubuntu 24.04's repositories is ancient---
# you will likely have to install from .debs!
err = subprocess.run(["dot", "-Tsvg_inline", "/dev/null"], stdout=DEVNULL, stderr=DEVNULL).returncode
if err:
	raise RuntimeError("the installed graphviz binaries do not support svg_inline output (try updating)")
del err


def _build_graph(chal: Challenge) -> str:
	"""Create a Graphviz graph visualizing the agents, networks, and relationships between them in a challenge.
	
	Agents and networks each become a node; the link between an agent and a network it
	is in becomes an edge. Entire networks or agents may be hidden by setting
	visible=False in their metadata.
	
	Labels will be laid out in Latin Modern Sans, which matches the font used by
	Tulila Server's HTML client. For best results, ensure the Latin Modern Sans
	font is installed on the server and accessible to Graphviz so it can center
	the labels correctly (as this requires knowing the width).
	"""
	buf = StringIO()
	print("graph G {", file=buf)
	print('  node [fontsize=12, fontname="Latin Modern Sans"]', file=buf)
	print('  edge [fontname="Latin Modern Sans"]', file=buf)
	
	def small_italic(s: str, sz: int = 7) -> str:
		"""Make a string small and italic, in Graphviz HTML-lite syntax."""
		return f'<font point-size="{sz}"><i>{s}</i></font>'
	
	def color(s: str) -> str:
		"""Return a string that sets an object's color and fontcolor to the given value in Graphviz syntax."""
		return f'color="{s}", fontcolor="{s}"'
	
	def id_for(o: Agent | Network) -> str:
		"""Create a unique ID for an agent or network suitable for use by Graphviz.
		
		The ID is unique within a given challenge but might not be unique across challenges.
		
		The ID will be suitable for use in Graphviz syntax without escaping or quoting.
		(At the moment, this is implemented by making the ID entirely numeric.)
		"""
		unique_id = type(o).__name__ + ":" + o.name
		return str(int.from_bytes(sha256(unique_id.encode()).digest()[:20]))
	
	# First, render all the visible agents
	for agent in chal.agents:
		if not agent.visible: continue
		print(f"  {id_for(agent)} [label=<{small_italic("Agent")}<br/>{agent.name}", end="", file=buf)
		
		# The agent provided by the challenge recipient is called out as such
		if agent.code is not None:
			print(">]", file=buf)
		else:
			print(f"<br/>{small_italic("(You!)")}>, {color("green")}]", file=buf)
	
	# Then, render all the visible networks...
	for network in chal.networks:
		if not network.visible: continue
		print(f"  {id_for(network)} [label=<{small_italic("Network")}<br/>{network.name}>, shape=rectangle]", file=buf)
		
		# ...and the edges to/from visible agents
		# Indicate the privileges an agent has on the network using an edge label
		for name in network.members:
			agent = chal.agents_by_name[name]
			if not agent.visible: continue
			
			print(f"  {id_for(network)} -- {id_for(agent)}", end="", file=buf)
			if   name in network.interceptors and name in network.monitors:
				print(f" [label=<{small_italic("(intercepts, spoofs, monitors)", 5)}>, {color("blue")}]", file=buf)
			elif name in network.interceptors:
				print(f" [label=<{small_italic("(intercepts, spoofs)", 5)}>, {color("blue")}]", file=buf)
			elif name in network.spoofers and name in network.monitors:
				print(f" [label=<{small_italic("(spoofs, monitors)", 5)}>, {color("purple")}]", file=buf)
			elif name in network.spoofers:
				print(f" [label=<{small_italic("(spoofs)", 5)}>, {color("purple")}]", file=buf)
			elif name in network.monitors:
				print(f" [label=<{small_italic("(monitors)", 5)}>, {color("red")}]", file=buf)
			else:
				print(file=buf)
	
	print("}", file=buf)
	
	result = buf.getvalue()
	buf.close()  # Eagerly free the memory used by the buffer
	return result


# Remove <!--comments--> and <title>title elements</title>
_remove_svg_cruft = partial(re.compile(r"\s*(?:<!--[^>]*-->|<title>[^>]*</title>)\s*").sub, "")

async def _run_graphviz(graph: str, size: Optional[float] = None) -> str:
	"""Render a graph in Graphviz syntax to an SVG image of the given size.
	
	The given size is in CSS inches. The horizontal size of the returned
	SVG will be exactly the given size; the vertical size will be _at most_
	the given size.
	
	This is a relatively thin wrapper around the Graphviz command line
	tool "dot".
	"""
	if size is None:
		# As 1 CSS inch = 96 pixels, 8.33 inches = 800 pixels
		size = 8.33
	
	proc = await create_subprocess_exec(
		"dot",
		"-Tsvg_inline",
		f"-Gsize={size},{size}!",
		stdin=PIPE, stdout=PIPE, stderr=PIPE
	)
	out, err = await proc.communicate(graph.encode())
	return _remove_svg_cruft(out.decode())


_SVG_CACHE_PATH = expanduser("~/gvcache")
makedirs(_SVG_CACHE_PATH, exist_ok=True)


def _cache_key(chal: Challenge) -> str:
	"""Return the name of the file containing cached SVG data for a challenge.
	
	This file does not necessarily exist.
	
	The file is named using the SHA-256 hash of the challenge file's path.
	"""
	return sha256(chal.path.encode()).hexdigest() + ".svg.zstd"


async def render(chal: Challenge) -> str:
	"""Render the network and agent graph of a challenge to SVG.
	
	If this challenge has already been rendered and is present in
	the cache, return the cached data.
	
	The returned SVG data is suitable for including as-is in an
	HTML response.
	"""
	cache_path = os.path.join(_SVG_CACHE_PATH, _cache_key(chal))
	
	# Check to see if the challenge file has been modified since the
	# cached data was created - if so, the cached data may not be used
	if isfile(cache_path) and stat(cache_path).st_mtime > stat(chal.path).st_mtime:
		with open(cache_path, "rb") as f:
			return zstd.decompress(f.read()).decode()
	
	svg = await _run_graphviz(_build_graph(chal), chal.graph_size)
	
	if isdir(cache_path): rmtree(cache_path)
	with open(cache_path, "wb") as f:
		f.write(zstd.compress(svg.encode()))
	
	return svg


def discard_unused_graphs(chals: Iterable[Challenge]) -> None:
	"""Remove unused/obsolete files and directories from the cache directory."""
	used_graphs = {_cache_key(chal) for chal in chals}
	for name in listdir(_SVG_CACHE_PATH):
		path = os.path.join(_SVG_CACHE_PATH, name)
		if name not in used_graphs or not isfile(path):
			if isdir(path):
				rmtree(path)
			else:
				os.remove(path)

"""Present challenge data to the rest of Tulila Server in the maximally convenient way.

The representation of challenges directly provided by Tulila is not suitable
for direct consumption by Tulila Server, for several reasons. This module
creates and presents an alternate representation:
  - That has a (URL-safe!) numeric ID.
  - That allows easy retrieval of challenges by their ID, name, or category.
  - Where the metadata is type-checked, validated, and processed as required
    (this may involve, e.g., reading sidecar files).

Convenient representations of agents, networks, and challenges are provided;
all access to challenge data goes through this module.

This module is also responsible for initially calling into Tulila to load the
challenge data.
"""

from __future__ import annotations

import csv
import os.path

from asyncio import Queue
from dataclasses import dataclass
from functools import cached_property
from os.path import dirname, expanduser, isfile

import mistune
import ordered_set

from aiohttp.web import AppKey, Application
from mistune import create_markdown, HTMLRenderer
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters.html import HtmlFormatter
from tulila import load_challenges, Agent, Challenge, Event, Network, OrderedSet, Result

from ._config import CHALLENGE_PATHS

from collections.abc import Collection, Iterator, Mapping, MutableMapping, Set, Sequence
from typing import cast, Optional


__all__ = (
	"AgentWithMetadata",
	"NetworkWithMetadata",
	"ChallengeWithMetadata",
	"Challenges",
	"read_name_id_map",
	"init_challenges",
)


@dataclass(frozen=True, kw_only=True)
class AgentWithMetadata:
	"""Parse agent metadata and provide convenient access to all relevant fields.
	
	Tulila's Agent, Network, and Challenge types only concern themselves with the
	data required to run a simulation of a challenge---everything else is shoved
	into their "metadata" mapping.
	
	Tulila Server actually cares about some of that metadata (e.g., a
	challenge's description, short name, etc.) but loading it direct from the
	metadata attribute every time it is used is a poor solution, for several
	reasons:
	  - Tulila Server is type-checked. Loading untyped data is unacceptable,
	    and including type-validation code at every use is poor design.
	  - Certain metadata fields require additional processing. For example,
	    the "description" field in a challenge's metadata refers to a
		Markdown file that must be loaded and rendered into HTML.
	
	For these reasons, three classes---AgentWithMetadata, NetworkWithMetadata,
	and ChallengeWithMetadata---are defined here and provide Tulila Server's
	view of the Tulila objects. All of the metadata is validated, processed,
	and provided in a nice convenient way for other code to use.
	
	[In fact, in other Tulila Server modules, I tend to rename these to just
	 Agent, Network, and Challenge on import to save typing :)]
	"""
	
	agent     : Agent
	visible   : bool
	show_code : bool
	
	@property
	def name(self) -> str:
		"""Return the agent's name."""
		return self.agent.name
	
	@property
	def code(self) -> Optional[str]:
		"""Return the agent's code, if any.
		
		A single agent per challenge will not have associated code as this code
		will be given by the challenge recipient.
		"""
		return self.agent.code
	
	@property
	def deps(self) -> Collection[str]:
		"""Return the agent's dependencies."""
		return self.agent.deps
	
	@staticmethod
	def _from_agent(agent: Agent) -> AgentWithMetadata:
		"""Parse and validate the metadata from a Tulila Network and use it to create an AgentWithMetadata.
		
		Default values will be substituded for missing metadata and an error will
		be raised if a metadata key is present but the value is not the correct
		type.
		"""
		visible = agent.metadata.get("visible", True)
		if not isinstance(visible, bool):
			raise ValueError(f"visible: expected bool, got {type(visible).__name__}")
		
		show_code = agent.metadata.get("show_code", False)
		if not isinstance(show_code, bool):
			raise ValueError(f"show_code: expected bool, got {type(show_code).__name__}")
		
		if show_code and agent.code is None:
			raise ValueError("may not have show_code=True on an agent without code")
		
		return AgentWithMetadata(
			agent     = agent,
			visible   = visible,
			show_code = show_code,
		)


@dataclass(frozen=True, kw_only=True)
class NetworkWithMetadata:
	"""Parse network metadata and provide convenient access to all relevant fields.
	
	For more information on the context and purpose of this class, see the
	documentation for the similar class AgentWithMetadata, above.
	"""
	
	network : Network
	visible : bool
	
	@property
	def name(self) -> str:
		"""Return the network's name."""
		return self.network.name
	
	@property
	def members(self) -> Set[str]:
		"""Return the network's members (a set of agent names)."""
		return self.network.members
	
	@property
	def monitors(self) -> Set[str]:
		"""Return the network's monitors (a set of agent names)."""
		return self.network.monitors
	
	@property
	def interceptors(self) -> OrderedSet[str]:
		"""Return the network's interceptors (an ordered set of agent names)."""
		return self.network.interceptors
	
	@property
	def spoofers(self) -> Set[str]:
		"""Return the network's spoofers (a set of agent names)."""
		return self.network.spoofers
	
	@staticmethod
	def _from_network(network: Network) -> NetworkWithMetadata:
		"""Parse and validate the metadata from a Tulila Network and use it to create a NetworkWithMetadata.
		
		Right now, that's just whether the network is visible - this will default
		to true if unspecified and an error will be raised if the key is present,
		but the value is not a boolean.
		"""
		visible = network.metadata.get("visible", True)
		if not isinstance(visible, bool):
			raise ValueError(f"visible: expected bool, got {type(visible).__name__}")
		
		return NetworkWithMetadata(
			network = network,
			visible = visible,
		)


_DEFAULT_CATEGORY = "Uncategorized"

@dataclass(frozen=True, kw_only=True)
class ChallengeWithMetadata:
	"""Parse challenge metadata and provide convenient access to all relevant fields.
	
	For more information on the context and purpose of this class, see the
	documentation for the similar class AgentWithMetadata, above.
	"""
	
	challenge  : Challenge
	id         : int
	path       : str
	category   : str
	short_name : str
	description: str
	graph_size : Optional[float]  # in CSS inches
	template   : Optional[str]  # a.k.a. starter code
	agents     : Collection[AgentWithMetadata]
	networks   : Collection[NetworkWithMetadata]

	async def launch(self, code: str, *, event_queue: Optional[Queue[Event]] = None, trace : bool = False) -> Result:
		"""Launch a simulation of the challenge using the provided code and return the result.
		
		See tulila.Challenge.launch().
		"""
		return await self.challenge.launch(code, event_queue=event_queue, trace=trace)

	@property
	def name(self) -> str:
		"""Return the challenge's name."""
		return self.challenge.name
	
	@cached_property
	def description_html(self) -> str:
		"""Render the challenge's description (written in Markdown) to HTML."""
		return cast(str, create_markdown(renderer=_HighlightRenderer())(self.description))
	
	@cached_property
	def agents_by_name(self) -> Mapping[str, AgentWithMetadata]:
		"""Return a mapping of agent names to the corresponding objects."""
		return {agent.name: agent for agent in self.agents}
	
	@staticmethod
	def _from_challenge(chal: Challenge, id: int) -> ChallengeWithMetadata:
		"""Parse and validate the metadata from a Tulila Challenge and use it to create a ChallengeWithMetadata.
		
		The ID of the challenge is also explicitly passed in to be stored in
		the created ChallengeWithMetadata.
		
		Default values will be substituted for missing metadata (except for path,
		which is inserted by the Tulila challenge loader and should always be
		present).
		
		An error will be raised if a piece of metadata is present but not of
		the correct type.
		
		The description and template metadata fields will be interpreted as a
		path and read.
		"""
		path = chal.metadata.get("path", None)
		if not isinstance(path, str):
			raise ValueError(f"path: expected str, got {type(path).__name__}")
		
		category = chal.metadata.get("category", _DEFAULT_CATEGORY)
		if not isinstance(category, str):
			raise ValueError(f"category: expected str, got {type(category).__name__}")
		
		short_name = chal.metadata.get("short_name", chal.name)
		if not isinstance(short_name, str):
			raise ValueError(f"short_name: expected str, got {type(short_name).__name__}")
		
		description_path = chal.metadata.get("description", None)
		if description_path is not None and not isinstance(description_path, str):
			raise ValueError(f"description: expected str, got {type(description_path).__name__}")
		
		if description_path:
			# If a relative path is specified, it will be loaded relative to the
			# challenge JSON5 file. If an absolute path is specified, it will be
			# used as=is. This is the desired behavior.
			with open(os.path.join(dirname(path), description_path)) as f:
				description = f.read()
		else: description = ""
		
		graph_size = chal.metadata.get("graph_size", None)
		# Explicitly reject bool (it is a subclass of int)
		if isinstance(graph_size, int) and not isinstance(graph_size, bool):
			graph_size = float(graph_size)
		if graph_size is not None and not isinstance(graph_size, float):
			raise ValueError(f"graph_size: expected float, got {type(graph_size).__name__}")
		
		template_path = chal.metadata.get("template", None)
		if template_path is not None and not isinstance(template_path, str):
			raise ValueError(f"template: expected str, got {type(template_path).__name__}")
		
		if template_path:
			with open(os.path.join(dirname(path), template_path)) as f:
				template = f.read()
		else: template = None
		
		return ChallengeWithMetadata(
			id          = id,
			challenge   = chal,
			path        = path,
			category    = category,
			short_name  = short_name,
			description = description,
			graph_size  = graph_size,
			template    = template,
			agents      = [AgentWithMetadata._from_agent(agent) for agent in chal.agents],
			networks    = [NetworkWithMetadata._from_network(network) for network in chal.networks],
		)


@dataclass(frozen=True)
class Challenges:
	"""Provide convenient ways of accessing challenges.
	
	One instance of this class exists and all access to challenge data from the
	rest of Tulila Server goes through here.
	"""
	
	challenges : Sequence[ChallengeWithMetadata]
	name_id_map: Mapping[str, int]
	
	def __iter__(self) -> Iterator[ChallengeWithMetadata]:
		"""Return an iterator of the challenges."""
		return iter(self.challenges)
	
	@cached_property
	def categories(self) -> OrderedSet[str]:
		"""Return the names of all categories, ordered by first appearance.
		
		Due to the behavior of tulila.load_challenges, this is ultimately
		ordered by challenge paths. The category of the challenge loaded
		from the path that is lexicographically first will appear first,
		and so on.
		"""
		# This should be a one-liner, but the type-checker can't follow the inferences
		# unless I split it into the three lines. Re-visit when mypy gets smarter.
		all_known_categories = [chal.category for chal in self.challenges]
		unique_categories = ordered_set.OrderedSet(all_known_categories)
		return unique_categories
	
	@cached_property
	def id_name_map(self) -> Mapping[int, str]:
		"""Return the mapping between challenge IDs and names."""
		return {v: k for k, v in self.name_id_map.items()}
	
	@cached_property
	def by_name(self) -> Mapping[str, ChallengeWithMetadata]:
		"""Return a mapping that allows retrieval of a challenge object by its name."""
		return {chal.name: chal for chal in self.challenges}
	
	@cached_property
	def by_id(self) -> Mapping[int, ChallengeWithMetadata]:
		"""Return a mapping that allows retrieval of a challenge object by its ID."""
		return {id: self.by_name[name] for id, name in self.id_name_map.items()}
	
	@cached_property
	def by_category(self) -> Mapping[str, Sequence[ChallengeWithMetadata]]:
		"""Return a mapping that allows retrieval of all challenges in a given category."""
		return {
			category: [chal for chal in self.challenges if chal.category == category]
			for category in self.categories
		}


_NAME_ID_MAP_PATH = expanduser("~/name_id_map")

def read_name_id_map() -> MutableMapping[str, int]:
	"""Read the saved mapping of challenge names to IDs.
	
	This is exported as it is used to export scores without needing the
	paths of the challenges (that information is passed in an environment
	variable that is only present when Tulila Server is launched from
	systemd).
	"""
	name_id_map: MutableMapping[str, int] = {}
	
	if isfile(_NAME_ID_MAP_PATH):
		with open(_NAME_ID_MAP_PATH, "r", newline="") as f:
			reader = csv.reader(f)
			for name, id in reader:
				name_id_map[name] = int(id)
	
	return name_id_map


def _map_names_to_ids(chals: Sequence[Challenge]) -> Mapping[str, int]:
	"""Load or create a mapping from challenge names to numeric IDs.
	
	Challenges are defined in JSON5 files and may only be referred to by
	name or path, neither of which is (guaranteed to be) safe for use in
	URLs.
	
	This function creates/loads a persistent mapping of challenge names
	to sequential numeric IDs. These IDs are safe for use in URLs and
	are also used to reference challenges in database models.
	
	Renaming or deleting a challenge once it has been mapped is not
	supported, as this may break references to the challenge in the
	database. To safely remove or rename a challenge, one must delete
	both the on-disk database and name/ID map first (note: this is only
	safe if you don't care about what's in the database, of course!).
	"""
	name_id_map = read_name_id_map()
	
	for name in name_id_map:
		if not any(chal.name == name for chal in chals):
			raise RuntimeError(f"unknown challenge: {name}")
	
	next_id = max(name_id_map.values(), default=0) + 1
	for chal in chals:
		if chal.name not in name_id_map:
			name_id_map[chal.name] = next_id
			next_id += 1
	
	with open(_NAME_ID_MAP_PATH, "w", newline="") as f:
		writer = csv.writer(f)
		for row in name_id_map.items():
			writer.writerow(row)
	
	return name_id_map


challenges: AppKey[Challenges] = AppKey("challenges")

def init_challenges(app: Application) -> None:
	"""Load Tulila challenges and provide them for use by an application.
	
	As part of this process, associate numeric IDs with the challenges and parse
	the challenge metadata. This process is documented further in the methods
	this calls.
	"""
	chals = load_challenges(*CHALLENGE_PATHS)
	name_id_map = _map_names_to_ids(chals)
	app[challenges] = Challenges(
		[ChallengeWithMetadata._from_challenge(chal, name_id_map[chal.name]) for chal in chals],
		name_id_map,
	)


class _HighlightRenderer(HTMLRenderer):
	"""Extend the default Markdown renderer to support syntax highlighting of code blocks.
	
	Adapted from a recipe at https://mistune.lepture.com/en/latest/guide.html
	"""
	
	def block_code(self, code: str, info: Optional[str] = None) -> str:
		"""If a language is specified for this code block, syntax-highlight it."""
		if info:
			lexer = get_lexer_by_name(info, stripall=True)
			# We use the xcode style as it is also supported by the client-side
			# code editor component
			formatter = HtmlFormatter(style="xcode", noclasses=True)
			return highlight(code, lexer, formatter)
		return "<pre><code>" + mistune.escape(code) + "</code></pre>"

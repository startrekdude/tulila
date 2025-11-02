"""Manage the lifecycle of submissions, from acceptance through evaluation and saving.

This module implements and provides Tulila Server's submission manager, the component
responsible for tracking pending submissions from acceptance all the way through
saving an evaluated submission object to the database. It advances a submission through
its life in accordance with various rules and limits.

The life of a submission is as follows:
  0. Data on the client
   -- submitted, accepted --
  1. Queued
   -- enough resources available to run --
  2. Running
   -- finishes --
  3. Saved to database.

A large portion of the submission manager's code is dedicated to enforcing various
limits intended to stop a single user from using a disproportionate amount of the
server's resources (CPU, memory, network bandwidth, disk space) and implementing logic
to gracefully handle cases where the limit is exceeded. Documentation for this sort
of functionality lives below, closer to where it is implemented.

The submission manager runs interleaved with the web server's processing of requests
(i.e. in the background).
"""

from __future__ import annotations

import asyncio

from asyncio import create_task, CancelledError, Task, Queue, FIRST_COMPLETED
from aiohttp.web import WebSocketResponse
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cached_property
from os import sysconf
from sys import getsizeof
from traceback import print_exc
from uuid import UUID, uuid4

from aiohttp.web import AppKey, Application
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from tulila import Event

from ._challenges import challenges, ChallengeWithMetadata as Challenge
from ._config import CONCURRENT_SUBMISSION_LIMIT_OVERRIDE, LOG_SIZE_LIMIT
from ._database import database, LogLine, Submission, User

from collections.abc import AsyncIterator, Callable, Iterable, Iterator, MutableMapping, MutableSet
from typing import Any, ClassVar


__all__ = (
	"PendingSubmission",
	"SubmissionManager",
	"init_submissions",
)


@dataclass(frozen=True, kw_only=True)
class PendingSubmission:
	"""Represent a pending submission (i.e., a submission that has not yet been evaluated).
	
	Pending submissions may be queued or running.
	"""
	id       : UUID
	user     : User
	challenge: Challenge
	code     : str
	queued_at: datetime
	
	@property
	def user_id(self) -> UUID:
		"""Return the ID of the user associated with this pending submission."""
		return self.user.id
	
	@property
	def challenge_id(self) -> int:
		"""Return the ID of the challenge associated with this pending submission."""
		return self.challenge.id


_EMPTY_STRING_SIZE = getsizeof("")

def _estimate_str_size(s: str) -> int:
	"""Estimate the size of a string in bytes.
	
	This completes in O(1) as it does not actually encode the string.
	
	This will always return a value >= the actual encoded size of the
	string and, for (at least) ASCII strings, a value exactly equal to
	the encoded size of the string.
	"""
	return getsizeof(s) - _EMPTY_STRING_SIZE


def _estimate_log_line_size(line: LogLine) -> int:
	"""Estimate the size of a log line in bytes.
	
	The estimate is calculated as the sum of the following:
	  1. The estimated size of the agent name in bytes.
	  2. The estimated size of the line in bytes.
	  3. 4 bytes for the timestamp (coded as a 32-bit float).
	  4. A byte for the agent name's null terminator.
	  5. A byte for the line's null terminator.
	This follows the serialization format in _database._types.
	
	The value returned will always be >= the actual size of
	the line in bytes.
	
	As _estimate_str_size is O(1), so is this.
	"""
	return _estimate_str_size(line.agent_name) + _estimate_str_size(line.line) + 6


class _BoundedLogStorage:
	"""Store log entries up to a given cumulative encoded capacity.
	
	If a new log entry would cause the object to exceed its capacity,
	old log entries are discarded until it fits.
	"""
	
	def __init__(self, capacity: int):
		"""Construct a _BoundedLogStorage object with the given capacity."""
		self._deque: deque[LogLine] = deque()
		self._capacity = capacity
		self._size = 0
		self.did_truncate = False
	
	def append(self, line: LogLine) -> None:
		"""Add a new log entry at the logical end.
		
		If adding this entry would cause the cumulative encoded size of
		all retained log entries to exceed the capacity, log entries are
		discarded until it fits, starting from the oldest.
		"""
		sz = _estimate_log_line_size(line)
		while self._size + sz > self._capacity:
			self.did_truncate = True
			self._size -= _estimate_log_line_size(self._deque.popleft())
		self._size += sz
		self._deque.append(line)
	
	def __iter__(self) -> Iterator[LogLine]:
		"""Return an iterator of the log lines."""
		return iter(self._deque)


type _Tasks = Iterable[Task[Any]]

async def _cancel_all(tasks: _Tasks) -> None:
	"""Cancel and await all of the given tasks.
	
	No results, exceptional or otherwise, will be returned.
	Do not call this on tasks you still care about!
	"""
	for task in tasks:
		task.cancel()
		
		with suppress(CancelledError, Exception):
			await task


submission_manager: AppKey[SubmissionManager] = AppKey("submission_manager")

class SubmissionManager:
	"""Manage submissions until they are evaluated and saved.
	
	This class acts as a singleton associated with the aiohttp web Application and is
	responsible for managing the lifecycle of submissions from acceptance until they
	are evaluated and saved in the database.
	
	As part of this role, it must:
	  - Decide whether a submission may be accepted (each user may have at most one
	    pending submission at any given time).
	  - Evaluate submissions concurrently up to the concurrent submission limit.
	  - Send events to a client via a WebSocket, to enable live log display.
	  - Enforce limits on the cumulative size of a submission log.
	  - Enforce limits on the number of submissions that will be retained for a
	    single user (for any given challenge).
	"""
	
	# Custom WebSocket close reason codes
	_ANOTHER_CLIENT_CONNECTED: ClassVar[int] = 4001
	_FINAL_RESULTS_READY     : ClassVar[int] = 4002
	
	def __init__(self, app: Application):
		"""Create a new submission manager, associated with the given application."""
		self._app = app
		self.pending_by_id: MutableMapping[UUID, PendingSubmission] = {}
		self.pending_by_user: MutableMapping[UUID, PendingSubmission] = {}
		self.start_times: MutableMapping[UUID, datetime] = {}
		self._pending_queue: Queue[PendingSubmission] = Queue()
		self._sockets: MutableMapping[UUID, WebSocketResponse] = {}
	
	async def submit(self, user: User, challenge: Challenge, code: str) -> PendingSubmission:
		"""Accept a submission for later evaluation.
		
		Each user may have at most one pending submission at a time.
		"""
		if user.id in self.pending_by_user:
			raise RuntimeError("you already have a submission queued")
		
		submission = PendingSubmission(
			id        = uuid4(),
			user      = user,
			challenge = challenge,
			code      = code,
			queued_at = datetime.now(timezone.utc),
		)
		self.pending_by_id[submission.id] = submission
		self.pending_by_user[user.id] = submission
		await self._pending_queue.put(submission)
		
		return submission
	
	async def register_socket(self, submission_id: UUID, ws: WebSocketResponse) -> None:
		"""Associate a WebSocket with a pending submission.
		
		Events associated with this submission will be sent to the WebSocket.
		"""
		if submission_id not in self.pending_by_id:
			raise RuntimeError("cannot register to receive events for a submission that is not pending")
		
		if submission_id in self._sockets:
			await self._sockets[submission_id].close(code=SubmissionManager._ANOTHER_CLIENT_CONNECTED)
		
		self._sockets[submission_id] = ws
	
	def deregister_socket(self, submission_id: UUID, ws: WebSocketResponse) -> None:
		"""If the given WebSocket is associated with the submission ID, remove this association.
		
		It is not correct to unconditionally deregister whichever WebSocket is associated
		with the submission ID as this may be called from the cleanup handler of a replaced
		WebSocket---in this case, the new WebSocket should remain associated with the
		submission ID.
		"""
		if self._sockets.get(submission_id, None) is ws:
			del self._sockets[submission_id]
	
	async def _background_task(self) -> None:
		"""Process queued submissions up to the concurrent submission limit.
		
		This runs in the background, interleaved with the web server
		processing requests.
		"""
		queue_read_task = create_task(self._pending_queue.get())
		tasks: MutableSet[Task[PendingSubmission | None]] = {queue_read_task}
		
		try:
			while True:
				complete, tasks = await asyncio.wait(tasks, return_when=FIRST_COMPLETED)
				
				for task in complete:
					if task is queue_read_task:
						tasks.add(create_task(self._run_submission(await queue_read_task)))
					else:
						await task
				
				# Restart the queue_read_task iff we haven't hit the concurrent submission limit
				if not any(task is queue_read_task for task in tasks) \
				   and len(tasks) < self._concurrent_submission_limit:
					queue_read_task = create_task(self._pending_queue.get())
					tasks.add(queue_read_task)
		finally: await _cancel_all(tasks)
	
	async def _run_submission(self, submission: PendingSubmission) -> None:
		"""Run a submission to completion.
		
		Events from the ongoing submission will be sent to the associated
		WebSocket, if any.
		
		This method also enforces limits on the cumulative size of the
		retained log lines (using _BoundedLogStorage) and the number of
		WebSocket messages in flight.
		"""
		self.start_times[submission.id] = datetime.now(timezone.utc)
		event_queue: Queue[Event] = Queue(maxsize=50_000)
		log = _BoundedLogStorage(LOG_SIZE_LIMIT)
		
		# At any given time, have a task to read an event from the queue and
		# a task to read the final result (when the simulation is complete).
		# Additional tasks to send WebSocket messages may be added.
		queue_read_task = create_task(event_queue.get())
		done_task = create_task(submission.challenge.launch(submission.code, event_queue=event_queue))
		websocket_msgs_in_flight = 0
		tasks = {queue_read_task, done_task}
		
		result = None
		internal_error = False  # Set to true if the simulation itself raises an Exception
		done = False
		
		try:
			while not done:
				complete, tasks = await asyncio.wait(tasks, return_when=FIRST_COMPLETED)
				
				for task in complete:
					if task is done_task:
						done = True
						try:
							result = await done_task
						except Exception:
							print_exc()
							internal_error = True
					elif task is queue_read_task:
						log_line = LogLine.from_event(await queue_read_task)
						log.append(log_line)
						
						if (ws := self._sockets.get(submission.id, None)) is not None \
						   and websocket_msgs_in_flight < 250:
							tasks.add(create_task(ws.send_json(log_line.as_dict())))
							websocket_msgs_in_flight += 1
						
						if not done:
							queue_read_task = create_task(event_queue.get())
							tasks.add(queue_read_task)
					else:  # WebSocket send task is done
						websocket_msgs_in_flight -= 1
						with suppress(Exception):  # WebSocket delivery is best-effort
							await task
		finally: await _cancel_all(tasks)
		
		# Handle any un-processed events
		# At this stage, we do not send them via WebSocket as the simulation
		# is complete. They will be added to the log and can be viewed once
		# the submission page reloads to the "completed submission" version.
		while not event_queue.empty():
			log.append(LogLine.from_event(await event_queue.get()))
		
		self._save_submission(Submission(
			id                   = submission.id,
			user                 = submission.user,
			challenge            = submission.challenge,
			code                 = submission.code,
			queued_at            = submission.queued_at,
			started_at           = self.start_times[submission.id],
			finished_at          = datetime.now(timezone.utc),
			internal_error       = internal_error,
			score                = result.score if result else None,
			exit_reason          = result.exit_reason if result else None,
			time                 = result.time if result else None,
			approximate_cpu_time = result.approximate_cpu_time if result else None,
			log                  = list(log),
			did_truncate         = log.did_truncate,
		))
		
		if (ws := self._sockets.pop(submission.id, None)) is not None:
			await ws.close(code=SubmissionManager._FINAL_RESULTS_READY)
	
	def _save_submission(self, submission: Submission) -> None:
		"""Save an evaluated submission to the database and clean up associated state.
		
		This also enforces the limit on the number of submissions to a challenge by
		a single user that will be stored by deleting old submissions. Only the 5
		newest submissions and the oldest submission with the highest score will
		be kept.
		
		State associated with the pending submission will be cleared after it is
		saved; after this, the user will be allowed to submit again.
		"""
		with Session(self._app[database]) as session, session.begin():
			other_submissions = list(session.scalars(
				select(Submission)
				.where(Submission.user == submission.user)
				.where(Submission.challenge_id == submission.challenge_id)
				.order_by(Submission.queued_at.desc())
			))
			
			# Figure out which of the other submissions will be kept
			kept_ids = {sub.id for sub in other_submissions[:4]}
			if other_submissions:
				score_or_zero: Callable[[Submission], float] = lambda sub: sub.score or 0.0
				highest_scoring = max(reversed(other_submissions), key=score_or_zero)
				if score_or_zero(highest_scoring) > 0 \
				   and score_or_zero(submission) <= score_or_zero(highest_scoring):
					kept_ids.add(highest_scoring.id)
			
			# Delete old submissions and add the new one
			session.execute(
				delete(Submission)
				.where(Submission.user == submission.user)
				.where(Submission.challenge_id == submission.challenge_id)
				.where(Submission.id.not_in(kept_ids))
			)
			session.add(submission)
			
			# Clear state associated with the pending submission
			del self.pending_by_user[submission.user.id]
			del self.pending_by_id[submission.id]
			del self.start_times[submission.id]
	
	@cached_property
	def _concurrent_submission_limit(self) -> int:
		"""Calculate the limit on the number of submissions that may run concurrently.
		
		This is either an estimation based on the available memory or specified
		explicitly in an environment variable (see _config).
		"""
		if CONCURRENT_SUBMISSION_LIMIT_OVERRIDE > 0:
			return CONCURRENT_SUBMISSION_LIMIT_OVERRIDE
		
		# If we assume each agent takes 80 MB and the simulation as a whole
		# has 100 MB overhead, set the limit so we don't ever use more than
		# 75% of the machine's physical memory. As a heuristic, this tends to
		# overestimate an agent's memory consumption, but that's what we
		# want here anyways.
		max_agents = max(len(chal.agents) for chal in self._app[challenges].challenges)
		memory_upper_bound = (max_agents * 80 + 100) * 1024 * 1024
		machine_memory = sysconf("SC_PAGE_SIZE") * sysconf("SC_PHYS_PAGES")
		return (machine_memory // 4 * 3) // memory_upper_bound


async def _setup_background_task(app: Application) -> AsyncIterator[None]:
	"""Run the submission manager in the background while the app is running.
	
	This is a valid aiohttp cleanup_ctx - it starts the background task,
	yields, and cancels it when the application exits.
	"""
	task = create_task(app[submission_manager]._background_task())
	
	yield
	
	task.cancel()
	with suppress(CancelledError):
		await task


def init_submissions(app: Application) -> None:
	"""Setup a submission manager for use by the  given application."""
	app[submission_manager] = SubmissionManager(app)
	app.cleanup_ctx.append(_setup_background_task)

"""
Modus Light — Linda Tuple Space
===============================
Generative coordination tuple space based on the classic Linda model (out, in_lease, rd).
Replaces chatty quadratic O(N^2) conversational agent loops with decoupled tuple state.
"""

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Optional
from .types import TaskTuple


class TupleSpace:
    """
    Decoupled In-Memory Linda Tuple Space:
    Allows agents to coordinate asynchronously through pattern-matched tuples
    without passing raw conversational transcripts over network wires.
    """

    #: Completed tuples are kept so a caller can read a result back, but only this
    #: many. Without a bound, a long-running coordinator accumulates every task it
    #: ever ran and the space grows without limit.
    DEFAULT_COMPLETED_RETENTION = 1000

    #: How long a lease may be held before the tuple is returned to PENDING for
    #: another worker. A lease is exclusive, so a worker that dies between
    #: in_lease() and complete() would otherwise hold the task forever: the queue
    #: reports it as in progress, nobody is working it, and no error is ever
    #: raised. Reclaiming trades at-most-once execution for at-least-once, which
    #: is the right default for work a supervisor is expected to retry.
    DEFAULT_LEASE_TIMEOUT_SECONDS = 300.0

    def __init__(
        self,
        completed_retention: int = DEFAULT_COMPLETED_RETENTION,
        lease_timeout_seconds: Optional[float] = DEFAULT_LEASE_TIMEOUT_SECONDS,
    ):
        self._tuples: Dict[int, TaskTuple] = {}
        self._counter = 1000
        self._completed_retention = max(0, completed_retention)
        # None disables reclaim, for a caller that needs at-most-once semantics
        # and would rather strand a task than risk running it twice.
        self._lease_timeout = lease_timeout_seconds
        #: Count of leases reclaimed, so a stuck worker is observable and not
        #: merely survived in silence.
        self.leases_reclaimed = 0
        # Completion order, oldest first — the eviction queue for finished work.
        self._completed_order: Deque[int] = deque()
        self._lock = threading.Lock()

    def out(
        self,
        topic: str,
        payload: Dict[str, Any],
        tenant_id: str = "default",
        priority: int = 0,
        ttl_seconds: Optional[float] = None,
    ) -> TaskTuple:
        """
        Linda 'out': Emits a new task tuple into the space.
        """
        with self._lock:
            self._counter += 1
            now = time.time()
            # `is not None`, not truthiness: ttl_seconds=0 means expire now,
            # while None means never expire. A falsy test collapses the two and
            # grants the immortal case to a caller asking for the opposite.
            exp = (now + ttl_seconds) if ttl_seconds is not None else None

            t = TaskTuple(
                id=self._counter,
                tenant_id=tenant_id,
                topic=topic,
                payload=payload,
                priority=priority,
                status="PENDING",
                lease_owner=None,
                created_at=now,
                expires_at=exp,
            )
            self._tuples[self._counter] = t
            return t

    def rd(self, topic: Optional[str] = None, tenant_id: Optional[str] = None) -> Optional[TaskTuple]:
        """
        Linda 'rd': Non-destructively inspects a matching tuple from the space without removing it.
        """
        with self._lock:
            self._prune_expired()
            # Prioritize higher priority tuples
            candidates = sorted(
                self._tuples.values(),
                key=lambda x: (x.priority, -x.created_at),
                reverse=True
            )
            for t in candidates:
                if topic and t.topic != topic:
                    continue
                if tenant_id and t.tenant_id != tenant_id:
                    continue
                return t
            return None

    def in_lease(
        self,
        worker_id: str,
        topic: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Optional[TaskTuple]:
        """
        Linda 'in': Claims an exclusive lease on a matching tuple for execution.
        """
        with self._lock:
            self._prune_expired()
            candidates = sorted(
                self._tuples.values(),
                key=lambda x: (x.priority, -x.created_at),
                reverse=True
            )
            for t in candidates:
                if t.status != "PENDING":
                    continue
                if topic and t.topic != topic:
                    continue
                if tenant_id and t.tenant_id != tenant_id:
                    continue

                t.status = "LEASED"
                t.lease_owner = worker_id
                t.leased_at = time.time()
                return t
            return None

    def complete(
        self,
        tuple_id: int,
        result_payload: Optional[Dict[str, Any]] = None,
        *,
        worker_id: str,
    ) -> bool:
        """
        Marks a leased tuple as completed and stores the result.

        A tuple can only be completed by the worker currently holding its lease.
        `worker_id` is required, not optional: an ownership check a caller can
        skip by omitting an argument is not exclusivity, and because tuple ids
        are sequential they are guessable, so any agent in the process could
        otherwise close out and overwrite work it never claimed. It is
        keyword-only so that a positional call written against a different
        signature fails loudly rather than passing a result payload where the
        worker id belongs.

        Returns False — rather than raising — when the tuple is unknown, already
        finished, or held by someone else, so a racing worker can simply move on.
        """
        with self._lock:
            t = self._tuples.get(tuple_id)
            if t is None:
                return False
            if t.status != "LEASED":
                return False
            if t.lease_owner != worker_id:
                return False

            t.status = "COMPLETED"
            t.leased_at = None
            if result_payload:
                t.payload["_result"] = result_payload

            self._completed_order.append(tuple_id)
            self._evict_surplus_completed()
            return True

    def _evict_surplus_completed(self):
        """Drops the oldest completed tuples once retention is exceeded.

        Caller must hold the lock.
        """
        while len(self._completed_order) > self._completed_retention:
            stale_id = self._completed_order.popleft()
            self._tuples.pop(stale_id, None)

    def count(self, status: Optional[str] = None) -> int:
        """Returns the number of active tuples matching status."""
        with self._lock:
            self._prune_expired()
            if status is None:
                return len(self._tuples)
            return sum(1 for t in self._tuples.values() if t.status == status)

    def _prune_expired(self):
        """Drops expired tuples and returns timed-out leases to PENDING.

        Caller must hold the lock.

        `expires_at is not None` rather than a truthiness test, and `<= now`
        rather than `< now`: a tuple created with `ttl_seconds=0` is asking to
        expire immediately, and both a falsy-zero check and a strict comparison
        would instead let it be claimed.
        """
        now = time.time()
        expired_ids = [
            tid for tid, t in self._tuples.items()
            if t.expires_at is not None and t.expires_at <= now
        ]
        for tid in expired_ids:
            del self._tuples[tid]

        if self._lease_timeout is None:
            return
        for t in self._tuples.values():
            if t.status != "LEASED" or t.leased_at is None:
                continue
            if now - t.leased_at >= self._lease_timeout:
                t.status = "PENDING"
                t.lease_owner = None
                t.leased_at = None
                self.leases_reclaimed += 1

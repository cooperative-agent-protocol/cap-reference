# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Reference reservation arbiter for CAP (Ch06 §6.3).

This is the implementation counterpart of the formally verified reservation
semantics:

* the **queued regime** (default) -- a busy resource queues the request in
  FIFO-with-priority order instead of denying it -- is the starvation-free
  discipline verified in ``cap-spec/formal/tla/CAPCoordination`` (NoStarvation
  holds with QueuedGrants = TRUE, and a starvation counterexample exists under
  deny-on-busy);
* a monotonically increasing per-resource **grant epoch** (fencing token) is
  issued with every grant; ``validate_fence`` rejects an action whose epoch is
  stale, which is the mechanism verified in
  ``cap-spec/formal/tla/ReservationFencing`` (ExclusiveActuation holds with the
  token, is violated without it).

The arbiter is pure in-memory logic (no I/O), so it is directly unit-testable
and is the same logic a Site Agent ``on_frame`` handler wraps to answer
``ReservationRequest`` with a ``ReservationStatus``.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from cap.v0.core import events_pb2, site_agent_pb2

_RS = events_pb2.ReservationStatus
_STATE = _RS.ReservationState


@dataclass(order=True)
class _QueuedRequest:
    # Sort key: higher priority first, then FIFO by arrival sequence.
    sort_key: tuple[int, int] = field(init=False)
    priority: int
    seq: int
    reservation_id: str = field(compare=False)
    holder_id: str = field(compare=False)

    def __post_init__(self) -> None:
        self.sort_key = (-self.priority, self.seq)


class ReservationManager:
    """Single-arbiter reservation manager with queued-fair grants and fencing.

    Args:
        queued: ``True`` (default) selects the starvation-free queued regime;
            ``False`` selects the OPTIONAL deny-on-busy regime (which the formal
            model shows can starve a machine -- see Ch06 §6.3.5).
    """

    def __init__(self, *, queued: bool = True) -> None:
        self._queued = queued
        self._holder: dict[str, str | None] = {}          # resource_id -> holder
        self._epoch: dict[str, int] = {}                  # resource_id -> current grant epoch
        self._queue: dict[str, list[_QueuedRequest]] = {} # resource_id -> ordered waiters
        self._resource_of: dict[str, str] = {}            # reservation_id -> resource_id
        self._holder_of: dict[str, str] = {}              # reservation_id -> holder_id
        self._seq = itertools.count()

    # ─── Queries ──────────────────────────────────────────────────────

    def current_epoch(self, resource_id: str) -> int:
        """The resource's current grant epoch (0 if never granted)."""
        return self._epoch.get(resource_id, 0)

    def holder(self, resource_id: str) -> str | None:
        return self._holder.get(resource_id)

    def validate_fence(self, resource_id: str, grant_epoch: int) -> bool:
        """True iff ``grant_epoch`` matches the resource's current epoch.

        A holder echoes the ``grant_epoch`` it was issued on any action gated by
        the reservation; a stale epoch (the holder's grant was superseded after
        a lost release/expiry notification) is rejected. This is the fencing
        check verified in ``ReservationFencing.tla``.
        """
        return grant_epoch == self._epoch.get(resource_id, 0)

    # ─── Arbitration ──────────────────────────────────────────────────

    def request(self, req: site_agent_pb2.ReservationRequest) -> _RS:
        """Arbitrate a ReservationRequest, returning a ReservationStatus."""
        resource = req.resource_id
        if self._holder.get(resource) is None:
            return self._grant(req.reservation_id, resource, req.holder_id)

        # Resource is busy.
        if not self._queued:
            return _RS(
                reservation_id=req.reservation_id,
                resource_id=resource,
                holder_id=self._holder[resource] or "",
                state=_STATE.RESERVATION_STATE_DENIED,
                reason=f"occupied by {self._holder[resource]}",
            )

        # Queued regime: enqueue in FIFO-with-priority order.
        waiter = _QueuedRequest(
            priority=req.priority,
            seq=next(self._seq),
            reservation_id=req.reservation_id,
            holder_id=req.holder_id,
        )
        q = self._queue.setdefault(resource, [])
        q.append(waiter)
        q.sort()
        self._resource_of[req.reservation_id] = resource
        self._holder_of[req.reservation_id] = req.holder_id
        pos = next(i for i, w in enumerate(q) if w.reservation_id == req.reservation_id) + 1
        return _RS(
            reservation_id=req.reservation_id,
            resource_id=resource,
            holder_id=req.holder_id,
            state=_STATE.RESERVATION_STATE_QUEUED,
            queue_position=pos,
        )

    def release(self, reservation_id: str) -> _RS | None:
        """Release a held reservation.

        Returns the ``ReservationStatus(GRANTED)`` for the next queued waiter, if
        any (the resource is handed to the head of the FIFO-with-priority queue);
        otherwise ``None`` (the resource is now free).
        """
        resource = self._resource_of.get(reservation_id)
        if resource is None or self._holder.get(resource) != self._holder_of.get(reservation_id):
            return None
        self._holder[resource] = None
        self._resource_of.pop(reservation_id, None)
        self._holder_of.pop(reservation_id, None)

        q = self._queue.get(resource)
        if q:
            nxt = q.pop(0)
            return self._grant(nxt.reservation_id, resource, nxt.holder_id)
        return None

    def _grant(self, reservation_id: str, resource: str, holder: str) -> _RS:
        # Monotonically bump the per-resource grant epoch (fencing token).
        epoch = self._epoch.get(resource, 0) + 1
        self._epoch[resource] = epoch
        self._holder[resource] = holder
        self._resource_of[reservation_id] = resource
        self._holder_of[reservation_id] = holder
        return _RS(
            reservation_id=reservation_id,
            resource_id=resource,
            holder_id=holder,
            state=_STATE.RESERVATION_STATE_GRANTED,
            grant_epoch=epoch,
        )

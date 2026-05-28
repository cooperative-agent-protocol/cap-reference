# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0
"""CommandHandle — lifecycle handle returned by HAL.dispatch(intent).

Replaces the legacy ``HAL.send_command()`` "fire-and-forget" pattern,
which returned only "request accepted" and forced the agent to
``wait_for_phase_change()`` polling the bridge's /state endpoint.

Under the new design:

  agent: handle = await hal.dispatch(intent)
         await handle.wait_for(CommandState.COMPLETED, timeout=...)

  bridge: dispatcher.update(handle, state=EXECUTING, last_phase=..., ...)
          ...
          dispatcher.update(handle, state=COMPLETED, ...)

The handle is the single source of truth for execution lifecycle.
Phase strings (``"loading_truck"``, ``"returning"``) become opaque
``last_phase`` annotations rather than the contract for completion
detection.

Pure-Python; no protobuf or grpc dependency at this layer. Wire
encoding lives in ``cap-spec/proto/cap/v0/lifecycle.proto``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class CommandState(str, Enum):
    """Monotonic lifecycle states.

    Order:  QUEUED → EXECUTING → (COMPLETED | FAILED | PREEMPTED)
            REJECTED is terminal-from-start (dispatcher refused).
    """

    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    PREEMPTED = "preempted"
    REJECTED = "rejected"


_TERMINAL_STATES: frozenset[CommandState] = frozenset({
    CommandState.COMPLETED,
    CommandState.FAILED,
    CommandState.PREEMPTED,
    CommandState.REJECTED,
})


# Allowed transitions (closed-world; anything else is logged + rejected).
_TRANSITIONS: dict[CommandState, frozenset[CommandState]] = {
    CommandState.QUEUED: frozenset({
        CommandState.EXECUTING,
        CommandState.COMPLETED,   # rare: instant idempotent confirm
        CommandState.FAILED,
        CommandState.REJECTED,
        CommandState.PREEMPTED,
    }),
    CommandState.EXECUTING: frozenset({
        CommandState.COMPLETED,
        CommandState.FAILED,
        CommandState.PREEMPTED,
    }),
    # Terminal states have no outgoing edges
    CommandState.COMPLETED: frozenset(),
    CommandState.FAILED: frozenset(),
    CommandState.PREEMPTED: frozenset(),
    CommandState.REJECTED: frozenset(),
}


class AbortCause(str, Enum):
    """Reason a command moved to FAILED. Mirrors lifecycle.proto.AbortCause."""

    UNSPECIFIED = "unspecified"
    FOOTPRINT_SLOPE = "footprint_slope"
    GROUND_CLEARANCE = "ground_clearance"
    HAZARD_INTRUSION = "hazard_intrusion"
    PEER_PROXIMITY = "peer_proximity"
    ROLL_LIMIT = "roll_limit"
    PITCH_LIMIT = "pitch_limit"
    FALL_DETECTED = "fall_detected"
    PATH_INFEASIBLE = "path_infeasible"
    TIMEOUT = "timeout"
    HAL_DISCONNECT = "hal_disconnect"
    USER_CANCEL = "user_cancel"


def _now() -> float:
    return time.time()


@dataclass
class CommandHandle:
    """Lifecycle-bearing handle for a single in-flight Intent.

    The agent never reads ``state`` directly in production — it awaits
    ``wait_for(target)`` instead. ``state`` is exposed for telemetry
    and debug only.
    """

    command_id: str
    intent_kind: str           # "drive" | "dig" | "swing" | ...
    correlation_id: str = ""    # caller's stable id for idempotent re-submit
    machine_id: str = ""

    state: CommandState = CommandState.QUEUED
    progress: float = 0.0       # 0..1 for long-running primitives
    last_phase: str = ""        # MachinePhase enum value, for observability

    submitted_at: float = field(default_factory=_now)
    last_event_at: float = field(default_factory=_now)

    error_message: str = ""
    abort_cause: AbortCause = AbortCause.UNSPECIFIED
    diagnostics: dict[str, str] = field(default_factory=dict)

    # ── Internal: state-change notifier (event-loop bound) ─────────
    _state_changed: asyncio.Event = field(
        default_factory=asyncio.Event, repr=False, compare=False,
    )

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES

    @property
    def succeeded(self) -> bool:
        return self.state == CommandState.COMPLETED

    @property
    def time_in_flight_sec(self) -> float:
        return max(0.0, self.last_event_at - self.submitted_at)

    # ── Mutators (called by dispatcher) ─────────────────────────────

    def update(
        self,
        *,
        state: CommandState | None = None,
        progress: float | None = None,
        last_phase: str | None = None,
        error_message: str | None = None,
        abort_cause: AbortCause | None = None,
        diagnostics: dict[str, str] | None = None,
    ) -> bool:
        """Apply a state update. Returns True if the update was accepted.

        Closed-world transition validation: an attempt to move from a
        terminal state, or via an unsupported transition, is rejected
        and returns False (caller's bug; the handle keeps its prior
        state). All other fields update independently of ``state``.

        After any successful field change, all current ``wait_for``
        awaiters are woken; they re-check the predicate and either
        return or sleep again.
        """
        accepted = False
        if state is not None and state != self.state:
            allowed = _TRANSITIONS.get(self.state, frozenset())
            if state not in allowed:
                return False
            self.state = state
            accepted = True
        if progress is not None and 0.0 <= progress <= 1.0 and progress != self.progress:
            self.progress = progress
            accepted = True
        if last_phase is not None and last_phase != self.last_phase:
            self.last_phase = last_phase
            accepted = True
        if error_message is not None and error_message != self.error_message:
            self.error_message = error_message
            accepted = True
        if abort_cause is not None and abort_cause != self.abort_cause:
            self.abort_cause = abort_cause
            accepted = True
        if diagnostics is not None:
            # Merge (don't replace) so dispatchers can append context.
            self.diagnostics = {**self.diagnostics, **diagnostics}
            accepted = True

        if accepted:
            self.last_event_at = _now()
            # Wake all current waiters; reset for next round.
            self._state_changed.set()
            self._state_changed.clear()
        return accepted

    # ── Awaiters (called by agent) ─────────────────────────────────

    async def wait_for(
        self,
        target: CommandState,
        *,
        timeout: float | None = None,
    ) -> bool:
        """Wait until ``state == target`` or a terminal state is reached.

        Returns True if state ended up exactly at ``target``, False if
        a different terminal state was reached or the timeout expired.

        Multiple concurrent waiters are supported; each wakes on every
        state change and re-checks the predicate. Spurious wakeups are
        impossible (the event is only set on real changes), but the
        re-check logic tolerates them gracefully.
        """
        deadline: float | None = None
        if timeout is not None:
            loop = asyncio.get_event_loop()
            deadline = loop.time() + timeout

        while True:
            if self.state == target:
                return True
            if self.is_terminal:
                return False  # ended in a different terminal state
            if deadline is None:
                await self._state_changed.wait()
            else:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    return self.state == target
                try:
                    await asyncio.wait_for(self._state_changed.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    return self.state == target

    async def wait_until_terminal(
        self, *, timeout: float | None = None,
    ) -> CommandState:
        """Wait for any terminal state. Returns the final state.

        Raises ``asyncio.TimeoutError`` on timeout; callers that prefer
        a non-raising form should use ``wait_for(target, timeout=...)``.
        """
        if self.is_terminal:
            return self.state
        deadline: float | None = None
        if timeout is not None:
            loop = asyncio.get_event_loop()
            deadline = loop.time() + timeout
        while not self.is_terminal:
            if deadline is None:
                await self._state_changed.wait()
            else:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError("wait_until_terminal timeout")
                await asyncio.wait_for(self._state_changed.wait(), timeout=remaining)
        return self.state


def make_handle(
    *,
    intent_kind: str,
    machine_id: str,
    correlation_id: str = "",
) -> CommandHandle:
    """Construct a fresh handle in the QUEUED state."""
    return CommandHandle(
        command_id=uuid.uuid4().hex[:16],
        intent_kind=intent_kind,
        correlation_id=correlation_id,
        machine_id=machine_id,
    )


__all__ = [
    "AbortCause",
    "CommandHandle",
    "CommandState",
    "make_handle",
]

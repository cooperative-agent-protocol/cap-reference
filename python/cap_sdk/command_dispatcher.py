# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0
"""CommandDispatcher — owns the bridge-side lifecycle of in-flight Intents.

Replaces the legacy "controller mutates state on every action; agent
polls /state" pattern with a single owner of (Intent, CommandHandle)
pairs. The dispatcher:

  1. Translates ``dispatch(intent)`` into a ``CommandHandle``.
  2. Enforces idempotency via ``correlation_id`` — re-submitting the
     same Intent while in-flight is a no-op (returns the existing
     handle).
  3. Preempts the current handle when a different Intent arrives on
     the same machine — the legacy controller used per-action guards
     for this; the dispatcher centralizes it.
  4. Drives ``CommandHandle`` lifecycle (QUEUED → EXECUTING →
     COMPLETED / FAILED / PREEMPTED / REJECTED) by listening to
     phase observations from the bridge.
  5. Exposes a unified cancel via ``StopIntent`` and direct
     ``cancel(correlation_id, cause)`` API.

Pure Python; the actual translation Intent → controller side-effect
is supplied by the caller as a ``ControllerExecutor`` Protocol so
this module is testable in isolation.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from .command_handle import (
    AbortCause,
    CommandHandle,
    CommandState,
    make_handle,
)
from .intents import (
    Intent,
    StopIntent,
    StopMode,
    intent_payload,
)

logger = logging.getLogger(__name__)


# ─── ControllerExecutor: bridge-side adapter ──────────────────────────


class ExecutorResult:
    """Three-valued result of a controller's intent application."""

    ACCEPTED = "accepted"           # controller now executing
    NO_OP = "no_op"                  # already in target state (idempotent confirm)
    REJECTED = "rejected"            # invalid for current controller state
    ERROR = "error"                  # bridge / HAL failure


@runtime_checkable
class ControllerExecutor(Protocol):
    """Bridge-side adapter that applies an Intent to a controller.

    Implementations transform the typed Intent into the underlying
    controller's invocation form (typically a legacy
    ``handle_command(action, params)`` API on the simulator/bridge
    side).
    """

    async def __call__(
        self, intent: Intent, handle: CommandHandle,
    ) -> str:
        """Apply ``intent`` and return one of ``ExecutorResult.*``."""
        ...


# ─── PhaseObserver: bridge-side lifecycle source ──────────────────────


@runtime_checkable
class PhaseObserver(Protocol):
    """Subscribed by dispatcher to receive phase change events.

    ``register(machine_id, callback)`` returns a deregister callable.
    The bridge's state aggregator calls back whenever a controller
    transitions phase (e.g., MOVING_TO_DIG → DIGGING → SWINGING_TO_LOAD).
    The dispatcher uses these events to advance the active handle's
    state and decide when to flip to COMPLETED.
    """

    def register(
        self,
        machine_id: str,
        callback: Callable[[str], Awaitable[None] | None],
    ) -> Callable[[], None]:
        ...


# ─── Dispatcher ──────────────────────────────────────────────────────


_TerminalPhases: frozenset[str] = frozenset({
    # Phases that, when reached, terminate the active drive intent.
    # Other Intent kinds use intent-specific terminal-phase predicates.
    "idle",
})


class CommandDispatcher:
    """Per-machine command lifecycle owner.

    Construct one dispatcher per controller (one per excavator / truck).
    The dispatcher's ``dispatch`` method is the public entry point;
    everything else is wired internally.
    """

    def __init__(
        self,
        *,
        machine_id: str,
        executor: ControllerExecutor,
        terminal_phase_predicate: Callable[[Intent, str], bool] | None = None,
    ) -> None:
        self._machine_id = machine_id
        self._executor = executor
        self._terminal_predicate = (
            terminal_phase_predicate or _default_terminal_predicate
        )
        self._handles: dict[str, CommandHandle] = {}
        # The "active" handle is the most recent non-terminal one. When
        # a new Intent preempts, the prior active handle moves to
        # PREEMPTED before the new one is dispatched.
        self._active_correlation_id: str | None = None
        self._active_intent: Intent | None = None
        self._lock = asyncio.Lock()

    # ── Public API ──────────────────────────────────────────────────

    async def dispatch(self, intent: Intent) -> CommandHandle:
        """Apply an Intent. Returns the (possibly existing) CommandHandle.

        Lifecycle:
          1. Idempotent re-submit (same correlation_id, same payload,
             still in-flight) → return existing handle, no controller call.
          2. Same correlation_id, different payload → preempt → new
             handle, dispatch.
          3. Different correlation_id → preempt prior active (if any) →
             new handle, dispatch.
          4. StopIntent → preempt active, mark new StopIntent
             COMPLETED immediately if controller acknowledged the stop.
        """
        if isinstance(intent, StopIntent):
            return await self._handle_stop(intent)
        async with self._lock:
            existing = self._handles.get(intent.correlation_id)
            if existing is not None and not existing.is_terminal:
                if self._intents_equal(existing, intent):
                    # Idempotent: already in flight with same payload.
                    return existing
                # Same correlation_id, different payload → preempt.
                existing.update(
                    state=CommandState.PREEMPTED,
                    error_message="superseded by new payload",
                )

            # If a *different* correlation_id is currently active, preempt it.
            if (
                self._active_correlation_id is not None
                and self._active_correlation_id != intent.correlation_id
            ):
                prior = self._handles.get(self._active_correlation_id)
                if prior is not None and not prior.is_terminal:
                    prior.update(
                        state=CommandState.PREEMPTED,
                        error_message=(
                            f"superseded by intent={intent.kind.value} "
                            f"correlation_id={intent.correlation_id}"
                        ),
                    )

            handle = make_handle(
                intent_kind=intent.kind.value,
                machine_id=self._machine_id,
                correlation_id=intent.correlation_id,
            )
            handle.diagnostics["task_id"] = intent.task_id
            handle.diagnostics["intent_payload"] = str(intent_payload(intent))
            self._handles[intent.correlation_id] = handle
            self._active_correlation_id = intent.correlation_id
            self._active_intent = intent

        # Run executor outside the lock (it may take time / await).
        try:
            result = await self._executor(intent, handle)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[%s] dispatcher executor raised: intent=%s",
                self._machine_id, intent.kind.value,
            )
            handle.update(
                state=CommandState.FAILED,
                error_message=f"executor exception: {exc}",
                abort_cause=AbortCause.HAL_DISCONNECT,
            )
            return handle

        async with self._lock:
            if result == ExecutorResult.ACCEPTED:
                handle.update(state=CommandState.EXECUTING)
            elif result == ExecutorResult.NO_OP:
                # Controller is already in target state; mark COMPLETED.
                handle.update(state=CommandState.EXECUTING)
                handle.update(state=CommandState.COMPLETED)
            elif result == ExecutorResult.REJECTED:
                handle.update(
                    state=CommandState.REJECTED,
                    error_message="controller rejected intent",
                )
            elif result == ExecutorResult.ERROR:
                handle.update(
                    state=CommandState.FAILED,
                    error_message="controller execution error",
                )
            else:
                handle.update(
                    state=CommandState.FAILED,
                    error_message=f"unknown executor result: {result}",
                )
        return handle

    async def cancel(
        self,
        correlation_id: str,
        *,
        reason: str = "user cancel",
    ) -> CommandHandle | None:
        """Cancel an in-flight handle by its correlation_id.

        Returns the now-PREEMPTED handle, or None if no such handle
        exists or it was already terminal.
        """
        async with self._lock:
            handle = self._handles.get(correlation_id)
            if handle is None or handle.is_terminal:
                return None
            handle.update(
                state=CommandState.PREEMPTED,
                error_message=reason,
                abort_cause=AbortCause.USER_CANCEL,
            )
            if self._active_correlation_id == correlation_id:
                self._active_correlation_id = None
                self._active_intent = None
            return handle

    async def notify_phase(self, phase: str) -> None:
        """Bridge calls this when the controller's phase transitions.

        Updates the active handle's ``last_phase`` and, if the phase
        matches the intent-specific completion predicate, transitions
        to COMPLETED.
        """
        async with self._lock:
            cid = self._active_correlation_id
            intent = self._active_intent
            handle = self._handles.get(cid) if cid is not None else None
            if handle is None or handle.is_terminal or intent is None:
                # Phase observed but no active intent — nothing to do.
                return
            handle.update(last_phase=phase)
            if self._terminal_predicate(intent, phase):
                handle.update(state=CommandState.COMPLETED)
                self._active_correlation_id = None
                self._active_intent = None

    async def notify_failure(
        self,
        *,
        cause: AbortCause,
        message: str = "",
    ) -> CommandHandle | None:
        """Bridge calls this when the safety supervisor ABORTs the active intent."""
        async with self._lock:
            cid = self._active_correlation_id
            handle = self._handles.get(cid) if cid is not None else None
            if handle is None or handle.is_terminal:
                return None
            handle.update(
                state=CommandState.FAILED,
                abort_cause=cause,
                error_message=message,
            )
            self._active_correlation_id = None
            self._active_intent = None
            return handle

    # ── Read-only state ────────────────────────────────────────────

    @property
    def active_handle(self) -> CommandHandle | None:
        if self._active_correlation_id is None:
            return None
        return self._handles.get(self._active_correlation_id)

    def get_handle(self, correlation_id: str) -> CommandHandle | None:
        return self._handles.get(correlation_id)

    def in_flight_count(self) -> int:
        return sum(
            1 for h in self._handles.values() if not h.is_terminal
        )

    # ── Internals ──────────────────────────────────────────────────

    async def _handle_stop(self, intent: StopIntent) -> CommandHandle:
        async with self._lock:
            cid = self._active_correlation_id
            prior = self._handles.get(cid) if cid is not None else None
            if prior is not None and not prior.is_terminal:
                prior.update(
                    state=CommandState.PREEMPTED,
                    error_message=intent.reason or "stop dispatched",
                    abort_cause=AbortCause.USER_CANCEL,
                )

            handle = make_handle(
                intent_kind=intent.kind.value,
                machine_id=self._machine_id,
                correlation_id=intent.correlation_id,
            )
            handle.diagnostics["stop_mode"] = intent.mode.value
            handle.diagnostics["stop_reason"] = intent.reason
            self._handles[intent.correlation_id] = handle
            self._active_correlation_id = None
            self._active_intent = None

        try:
            result = await self._executor(intent, handle)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[%s] dispatcher stop executor raised", self._machine_id,
            )
            handle.update(
                state=CommandState.FAILED,
                error_message=f"stop executor exception: {exc}",
                abort_cause=AbortCause.HAL_DISCONNECT,
            )
            return handle
        async with self._lock:
            if result in (ExecutorResult.ACCEPTED, ExecutorResult.NO_OP):
                # Stop reaches COMPLETED as soon as the bridge accepts it.
                handle.update(state=CommandState.EXECUTING)
                handle.update(state=CommandState.COMPLETED)
            elif result == ExecutorResult.REJECTED:
                handle.update(state=CommandState.REJECTED)
            else:
                handle.update(
                    state=CommandState.FAILED,
                    error_message=f"stop executor result: {result}",
                )
        return handle

    @staticmethod
    def _intents_equal(handle: CommandHandle, intent: Intent) -> bool:
        """Idempotency check: same kind + same payload as the in-flight intent.

        Uses ``intent_payload(intent)`` against the handle's stored
        payload diagnostic. The payload is serialized to a stable
        string at dispatch time, so deep equality on dataclasses isn't
        needed — and cap_sdk avoids depending on any implementation's
        internal plan/intent types.
        """
        if handle.intent_kind != intent.kind.value:
            return False
        existing = handle.diagnostics.get("intent_payload", "")
        new_payload = str(intent_payload(intent))
        return existing == new_payload


# ─── Default terminal-phase predicate ────────────────────────────────


def _default_terminal_predicate(intent: Intent, phase: str) -> bool:
    """Default mapping from (intent kind, phase) → completion.

    Mirrors the bridge controllers' phase semantics:
      * DriveIntent: COMPLETED when phase returns to "idle" (controller
        reaches arrival).
      * DigIntent: COMPLETED when phase leaves "digging" (cycle done).
      * SwingIntent: COMPLETED when phase leaves "swinging_to_load".
      * LoadTruckIntent: COMPLETED when phase leaves "loading_truck".
      * StabilizeArmIntent: COMPLETED when phase reaches "idle".
      * DumpIntent: COMPLETED when phase leaves "dumping".
      * WaitForLoadIntent: COMPLETED when phase leaves "waiting_for_load".

    Callers can override via ``terminal_phase_predicate`` for skill-
    specific semantics.
    """
    kind = intent.kind.value
    if kind == "drive":
        return phase == "idle"
    if kind == "dig":
        # Phase advances digging → swinging_to_load when bucket fills.
        return phase != "digging" and phase != "moving_to_dig"
    if kind == "swing":
        return phase != "swinging_to_load"
    if kind == "load_truck":
        return phase != "loading_truck"
    if kind == "stabilize_arm":
        return phase == "idle"
    if kind == "dump":
        return phase != "dumping"
    if kind == "wait_for_load":
        return phase != "waiting_for_load"
    return False


__all__ = [
    "CommandDispatcher",
    "ControllerExecutor",
    "ExecutorResult",
    "PhaseObserver",
]

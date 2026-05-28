# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CAP Authors
"""Tests for CommandDispatcher: idempotency, preemption, lifecycle
advance via phase observation, cancellation, failure injection."""

# pylint: disable=missing-function-docstring,missing-class-docstring

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from cap_sdk.command_dispatcher import (
    CommandDispatcher,
    ExecutorResult,
)
from cap_sdk.command_handle import (
    AbortCause,
    CommandHandle,
    CommandState,
)
from cap_sdk.intents import (
    DigIntent,
    DriveIntent,
    Intent,
    StabilizeArmIntent,
    StopIntent,
    StopMode,
)


@dataclass(frozen=True)
class _StubPlan:
    plan_id: str = "p-stub"
    world_seq: int = 1
    body_envelope_hash: str = "body-x"
    zone_grid_hash: str = "zone-y"
    waypoints: tuple = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
    motion_types: tuple = (0,)
    headings: tuple = (0.0, 0.0)
    expected_speed_mps: float = 1.0
    horizon_sec: float = 30.0


class _RecordingExecutor:
    """Captures every (intent, handle) call; configurable result."""

    def __init__(self, *, default_result: str = ExecutorResult.ACCEPTED) -> None:
        self.calls: list[tuple[Intent, CommandHandle]] = []
        self.default_result = default_result
        self.next_result: str | None = None
        self.raise_on_call = False

    async def __call__(
        self, intent: Intent, handle: CommandHandle,
    ) -> str:
        self.calls.append((intent, handle))
        if self.raise_on_call:
            raise RuntimeError("simulated executor crash")
        result = self.next_result if self.next_result is not None else self.default_result
        self.next_result = None
        return result


def _drive(machine_id: str = "zx", correlation_id: str = "cid-drive") -> DriveIntent:
    return DriveIntent(
        machine_id=machine_id, plan=_StubPlan(),
        correlation_id=correlation_id,
    )


# ─── Basic dispatch ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_dispatch_returns_handle_in_executing_state() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    handle = await disp.dispatch(_drive())
    assert handle.state == CommandState.EXECUTING
    assert handle.intent_kind == "drive"
    assert len(executor.calls) == 1


@pytest.mark.anyio
async def test_dispatch_no_op_marks_completed() -> None:
    executor = _RecordingExecutor(default_result=ExecutorResult.NO_OP)
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    handle = await disp.dispatch(_drive())
    assert handle.state == CommandState.COMPLETED


@pytest.mark.anyio
async def test_dispatch_rejected_marks_rejected() -> None:
    executor = _RecordingExecutor(default_result=ExecutorResult.REJECTED)
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    handle = await disp.dispatch(_drive())
    assert handle.state == CommandState.REJECTED
    assert handle.is_terminal is True


@pytest.mark.anyio
async def test_dispatch_executor_raises_marks_failed() -> None:
    executor = _RecordingExecutor()
    executor.raise_on_call = True
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    handle = await disp.dispatch(_drive())
    assert handle.state == CommandState.FAILED
    assert handle.abort_cause == AbortCause.HAL_DISCONNECT


# ─── Idempotency ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_idempotent_resubmit_returns_same_handle() -> None:
    """Same correlation_id + same payload while in flight → same handle, no re-execution."""
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    intent = _drive(correlation_id="abc")
    h1 = await disp.dispatch(intent)
    h2 = await disp.dispatch(intent)
    assert h1 is h2  # same object
    assert len(executor.calls) == 1  # executor invoked once


@pytest.mark.anyio
async def test_resubmit_after_terminal_creates_new_handle() -> None:
    """Same correlation_id after terminal → new handle (re-dispatched)."""
    executor = _RecordingExecutor(default_result=ExecutorResult.NO_OP)
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    intent = _drive(correlation_id="abc")
    h1 = await disp.dispatch(intent)
    assert h1.is_terminal
    h2 = await disp.dispatch(intent)
    assert h1 is not h2
    assert len(executor.calls) == 2


# ─── Preemption ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_different_correlation_id_preempts_active() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    h1 = await disp.dispatch(_drive(correlation_id="A"))
    assert h1.state == CommandState.EXECUTING
    h2 = await disp.dispatch(_drive(correlation_id="B"))
    assert h1.state == CommandState.PREEMPTED
    assert h2.state == CommandState.EXECUTING


@pytest.mark.anyio
async def test_same_correlation_id_different_payload_preempts() -> None:
    """Same correlation_id but different plan → preempt + re-dispatch."""
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    h1 = await disp.dispatch(_drive(correlation_id="X"))
    # Different plan_id → different payload
    intent2 = DriveIntent(
        machine_id="zx",
        plan=_StubPlan(plan_id="p-other"),
        correlation_id="X",
    )
    h2 = await disp.dispatch(intent2)
    assert h1 is not h2
    assert h1.state == CommandState.PREEMPTED
    assert h2.state == CommandState.EXECUTING


@pytest.mark.anyio
async def test_in_flight_count_tracks_active() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    await disp.dispatch(_drive(correlation_id="A"))
    assert disp.in_flight_count() == 1
    await disp.dispatch(_drive(correlation_id="B"))
    # A preempted → terminal; B executing → 1 in flight
    assert disp.in_flight_count() == 1


# ─── Phase notification → lifecycle advance ──────────────────────────


@pytest.mark.anyio
async def test_phase_notify_updates_last_phase() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    handle = await disp.dispatch(_drive())
    await disp.notify_phase("moving_to_dig")
    assert handle.last_phase == "moving_to_dig"
    assert handle.state == CommandState.EXECUTING


@pytest.mark.anyio
async def test_drive_completes_when_phase_returns_to_idle() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    handle = await disp.dispatch(_drive())
    await disp.notify_phase("moving_to_dig")
    assert handle.state == CommandState.EXECUTING
    await disp.notify_phase("idle")
    assert handle.state == CommandState.COMPLETED


@pytest.mark.anyio
async def test_dig_completes_when_phase_leaves_digging() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    handle = await disp.dispatch(DigIntent(
        machine_id="zx", target_volume_m3=8.0, bucket_capacity_m3=0.8,
    ))
    await disp.notify_phase("digging")
    assert handle.state == CommandState.EXECUTING
    await disp.notify_phase("swinging_to_load")
    assert handle.state == CommandState.COMPLETED


@pytest.mark.anyio
async def test_stabilize_arm_completes_when_phase_idle() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    handle = await disp.dispatch(StabilizeArmIntent(machine_id="zx"))
    await disp.notify_phase("idle")
    assert handle.state == CommandState.COMPLETED


@pytest.mark.anyio
async def test_phase_notify_with_no_active_intent_is_silent() -> None:
    """Phase events when no intent in flight → no-op (no crash)."""
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    await disp.notify_phase("idle")
    assert disp.active_handle is None


@pytest.mark.anyio
async def test_phase_notify_after_completion_is_silent() -> None:
    """Phase events after handle terminal → no further updates."""
    executor = _RecordingExecutor(default_result=ExecutorResult.NO_OP)
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    handle = await disp.dispatch(_drive())
    assert handle.state == CommandState.COMPLETED
    await disp.notify_phase("digging")
    # State unchanged because handle is terminal
    assert handle.state == CommandState.COMPLETED


# ─── Failure notification ────────────────────────────────────────────


@pytest.mark.anyio
async def test_notify_failure_marks_handle_failed_with_cause() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    handle = await disp.dispatch(_drive())
    failed = await disp.notify_failure(
        cause=AbortCause.FOOTPRINT_SLOPE,
        message="slope 24° > 21°",
    )
    assert failed is handle
    assert handle.state == CommandState.FAILED
    assert handle.abort_cause == AbortCause.FOOTPRINT_SLOPE
    assert "24°" in handle.error_message


@pytest.mark.anyio
async def test_notify_failure_with_no_active_returns_none() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    result = await disp.notify_failure(cause=AbortCause.FALL_DETECTED)
    assert result is None


# ─── Cancellation ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_cancel_marks_preempted_with_user_cancel_cause() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    handle = await disp.dispatch(_drive(correlation_id="cancel-target"))
    cancelled = await disp.cancel("cancel-target", reason="operator stop")
    assert cancelled is handle
    assert handle.state == CommandState.PREEMPTED
    assert handle.abort_cause == AbortCause.USER_CANCEL


@pytest.mark.anyio
async def test_cancel_unknown_id_returns_none() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    assert await disp.cancel("nonexistent") is None


@pytest.mark.anyio
async def test_cancel_already_terminal_returns_none() -> None:
    executor = _RecordingExecutor(default_result=ExecutorResult.NO_OP)
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    await disp.dispatch(_drive(correlation_id="cid"))
    # Already COMPLETED via NO_OP
    assert await disp.cancel("cid") is None


# ─── StopIntent ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_stop_intent_preempts_active_and_completes() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    drive = await disp.dispatch(_drive(correlation_id="drv"))
    stop = await disp.dispatch(StopIntent(
        machine_id="zx", mode=StopMode.HARD, reason="cliff",
        correlation_id="stop-1",
    ))
    assert drive.state == CommandState.PREEMPTED
    assert stop.state == CommandState.COMPLETED


@pytest.mark.anyio
async def test_stop_when_no_active_just_completes() -> None:
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    stop = await disp.dispatch(StopIntent(
        machine_id="zx", correlation_id="s",
    ))
    assert stop.state == CommandState.COMPLETED


# ─── Custom terminal predicate ───────────────────────────────────────


@pytest.mark.anyio
async def test_custom_terminal_predicate() -> None:
    """Caller can override completion semantics for skill-specific phases."""
    executor = _RecordingExecutor()

    def predicate(intent: Intent, phase: str) -> bool:
        # DriveIntent completes only when phase is "arrived"
        if intent.kind.value == "drive":
            return phase == "arrived"
        return False

    disp = CommandDispatcher(
        machine_id="zx", executor=executor,
        terminal_phase_predicate=predicate,
    )
    handle = await disp.dispatch(_drive())
    await disp.notify_phase("idle")
    # Default would have completed; custom predicate doesn't
    assert handle.state == CommandState.EXECUTING
    await disp.notify_phase("arrived")
    assert handle.state == CommandState.COMPLETED


# ─── End-to-end: dispatcher + wait_for ───────────────────────────────


@pytest.mark.anyio
async def test_e2e_dispatch_wait_for_completion() -> None:
    """Driver task notifies phases asynchronously; agent awaits."""
    executor = _RecordingExecutor()
    disp = CommandDispatcher(machine_id="zx", executor=executor)

    async def phase_driver() -> None:
        await asyncio.sleep(0.01)
        await disp.notify_phase("moving_to_dig")
        await asyncio.sleep(0.01)
        await disp.notify_phase("idle")  # → COMPLETED for drive

    # Agent dispatches and awaits
    handle = await disp.dispatch(_drive())
    asyncio.create_task(phase_driver())
    succeeded = await asyncio.wait_for(
        handle.wait_for(CommandState.COMPLETED), timeout=1.0,
    )
    assert succeeded is True


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"

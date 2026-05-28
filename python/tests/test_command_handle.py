# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CAP Authors
"""Tests for CommandHandle: lifecycle state machine, multi-waiter
notification, transition validation, abort cause."""

# pylint: disable=missing-function-docstring,missing-class-docstring

from __future__ import annotations

import asyncio

import pytest

from cap_sdk.command_handle import (
    AbortCause,
    CommandHandle,
    CommandState,
    make_handle,
)


# ─── Construction ────────────────────────────────────────────────────


def test_make_handle_starts_in_queued() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx120-01")
    assert handle.state == CommandState.QUEUED
    assert handle.intent_kind == "drive"
    assert handle.machine_id == "zx120-01"
    assert handle.is_terminal is False
    assert handle.succeeded is False
    assert len(handle.command_id) == 16


def test_make_handle_carries_correlation_id() -> None:
    handle = make_handle(
        intent_kind="dig", machine_id="zx", correlation_id="abc-123",
    )
    assert handle.correlation_id == "abc-123"


# ─── Transitions: happy path ────────────────────────────────────────


def test_queued_to_executing() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    accepted = handle.update(state=CommandState.EXECUTING)
    assert accepted is True
    assert handle.state == CommandState.EXECUTING


def test_executing_to_completed() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(state=CommandState.EXECUTING)
    accepted = handle.update(state=CommandState.COMPLETED)
    assert accepted is True
    assert handle.state == CommandState.COMPLETED
    assert handle.is_terminal is True
    assert handle.succeeded is True


def test_executing_to_failed_with_cause() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(state=CommandState.EXECUTING)
    handle.update(
        state=CommandState.FAILED,
        abort_cause=AbortCause.FOOTPRINT_SLOPE,
        error_message="slope 24° > 21°",
    )
    assert handle.state == CommandState.FAILED
    assert handle.abort_cause == AbortCause.FOOTPRINT_SLOPE
    assert handle.succeeded is False
    assert handle.is_terminal is True


def test_executing_to_preempted() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(state=CommandState.EXECUTING)
    accepted = handle.update(state=CommandState.PREEMPTED)
    assert accepted is True
    assert handle.is_terminal is True


def test_queued_directly_to_rejected() -> None:
    """Dispatcher rejects an Intent (e.g. plan expired) before executing."""
    handle = make_handle(intent_kind="drive", machine_id="zx")
    accepted = handle.update(
        state=CommandState.REJECTED, error_message="plan expired",
    )
    assert accepted is True
    assert handle.is_terminal is True


# ─── Transitions: rejection ────────────────────────────────────────


def test_terminal_state_rejects_further_updates() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(state=CommandState.EXECUTING)
    handle.update(state=CommandState.COMPLETED)
    accepted = handle.update(state=CommandState.EXECUTING)
    assert accepted is False
    assert handle.state == CommandState.COMPLETED


def test_completed_to_failed_rejected() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(state=CommandState.EXECUTING)
    handle.update(state=CommandState.COMPLETED)
    assert handle.update(state=CommandState.FAILED) is False
    assert handle.state == CommandState.COMPLETED


def test_executing_to_queued_rejected() -> None:
    """Cannot regress to a non-terminal earlier state."""
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(state=CommandState.EXECUTING)
    assert handle.update(state=CommandState.QUEUED) is False


def test_same_state_update_is_no_op_for_state() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(state=CommandState.EXECUTING)
    accepted = handle.update(state=CommandState.EXECUTING)
    # Same state → no transition; nothing else changed → False
    assert accepted is False


# ─── Field updates without state ───────────────────────────────────


def test_progress_update_independent_of_state() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(state=CommandState.EXECUTING)
    accepted = handle.update(progress=0.5)
    assert accepted is True
    assert handle.progress == 0.5


def test_progress_clamped_to_unit_range() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    accepted = handle.update(progress=1.5)
    assert accepted is False  # invalid → not applied
    assert handle.progress == 0.0


def test_last_phase_update() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(last_phase="moving_to_dig")
    assert handle.last_phase == "moving_to_dig"


def test_diagnostics_merge() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(diagnostics={"k1": "v1"})
    handle.update(diagnostics={"k2": "v2"})
    assert handle.diagnostics == {"k1": "v1", "k2": "v2"}


def test_diagnostics_overwrite_same_key() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(diagnostics={"k": "v1"})
    handle.update(diagnostics={"k": "v2"})
    assert handle.diagnostics == {"k": "v2"}


# ─── Async wait_for ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_wait_for_returns_when_target_reached() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")

    async def driver() -> None:
        await asyncio.sleep(0.01)
        handle.update(state=CommandState.EXECUTING)
        await asyncio.sleep(0.01)
        handle.update(state=CommandState.COMPLETED)

    asyncio.create_task(driver())
    result = await asyncio.wait_for(
        handle.wait_for(CommandState.COMPLETED), timeout=1.0,
    )
    assert result is True
    assert handle.state == CommandState.COMPLETED


@pytest.mark.anyio
async def test_wait_for_terminal_other_than_target_returns_false() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")

    async def driver() -> None:
        await asyncio.sleep(0.01)
        handle.update(state=CommandState.EXECUTING)
        await asyncio.sleep(0.01)
        handle.update(state=CommandState.FAILED)

    asyncio.create_task(driver())
    # We asked for COMPLETED, but FAILED happened.
    result = await asyncio.wait_for(
        handle.wait_for(CommandState.COMPLETED), timeout=1.0,
    )
    assert result is False
    assert handle.state == CommandState.FAILED


@pytest.mark.anyio
async def test_wait_for_immediate_when_already_at_target() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(state=CommandState.EXECUTING)
    handle.update(state=CommandState.COMPLETED)
    result = await handle.wait_for(CommandState.COMPLETED)
    assert result is True


@pytest.mark.anyio
async def test_wait_for_timeout_returns_false_at_unreached_state() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    # Don't drive any updates → wait_for must time out
    result = await handle.wait_for(CommandState.COMPLETED, timeout=0.05)
    assert result is False
    assert handle.state == CommandState.QUEUED


@pytest.mark.anyio
async def test_wait_for_intermediate_target_unblocks() -> None:
    """Wait for EXECUTING (non-terminal) returns when state advances there."""
    handle = make_handle(intent_kind="drive", machine_id="zx")

    async def driver() -> None:
        await asyncio.sleep(0.01)
        handle.update(state=CommandState.EXECUTING)

    asyncio.create_task(driver())
    result = await asyncio.wait_for(
        handle.wait_for(CommandState.EXECUTING), timeout=1.0,
    )
    assert result is True


@pytest.mark.anyio
async def test_multiple_concurrent_waiters_all_wake() -> None:
    """Two awaiters on the same handle both wake when state changes."""
    handle = make_handle(intent_kind="drive", machine_id="zx")

    async def driver() -> None:
        await asyncio.sleep(0.02)
        handle.update(state=CommandState.EXECUTING)
        await asyncio.sleep(0.01)
        handle.update(state=CommandState.COMPLETED)

    waiter_a = asyncio.create_task(handle.wait_for(CommandState.COMPLETED))
    waiter_b = asyncio.create_task(handle.wait_for(CommandState.COMPLETED))
    asyncio.create_task(driver())

    a, b = await asyncio.gather(
        asyncio.wait_for(waiter_a, timeout=1.0),
        asyncio.wait_for(waiter_b, timeout=1.0),
    )
    assert a is True
    assert b is True


# ─── wait_until_terminal ───────────────────────────────────────────


@pytest.mark.anyio
async def test_wait_until_terminal_returns_state() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")

    async def driver() -> None:
        await asyncio.sleep(0.01)
        handle.update(state=CommandState.EXECUTING)
        await asyncio.sleep(0.01)
        handle.update(state=CommandState.FAILED, abort_cause=AbortCause.FALL_DETECTED)

    asyncio.create_task(driver())
    final = await asyncio.wait_for(handle.wait_until_terminal(), timeout=1.0)
    assert final == CommandState.FAILED


@pytest.mark.anyio
async def test_wait_until_terminal_immediate_when_already_terminal() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    handle.update(state=CommandState.EXECUTING)
    handle.update(state=CommandState.COMPLETED)
    final = await handle.wait_until_terminal()
    assert final == CommandState.COMPLETED


@pytest.mark.anyio
async def test_wait_until_terminal_timeout_raises() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    with pytest.raises(asyncio.TimeoutError):
        await handle.wait_until_terminal(timeout=0.05)


# ─── time_in_flight_sec ─────────────────────────────────────────────


def test_time_in_flight_starts_at_zero() -> None:
    handle = make_handle(intent_kind="drive", machine_id="zx")
    # submitted_at == last_event_at at construction
    assert handle.time_in_flight_sec == pytest.approx(0.0, abs=0.01)


def test_time_in_flight_increases_after_update() -> None:
    import time as _t
    handle = make_handle(intent_kind="drive", machine_id="zx")
    _t.sleep(0.02)
    handle.update(state=CommandState.EXECUTING)
    assert handle.time_in_flight_sec > 0.01


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"

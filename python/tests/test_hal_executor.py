# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CAP Authors
"""Tests for HALCommandExecutor: Intent → HAL send_command() translation.

Verifies:
  - Each intent type maps to the correct HALCommand constant and params.
  - ACCEPTED is returned on HAL success; REJECTED on failure.
  - machine_type routing: DriveIntent → EXC_DRIVE_TO vs TRUCK_DRIVE_TO.
  - StopIntent sends STOP with machine_id in StopParams.
  - Unknown intent raises ValueError.
  - hal_error is recorded in handle.diagnostics on rejection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from cap_sdk.command_dispatcher import ExecutorResult
from cap_sdk.command_handle import CommandState, make_handle
from cap_sdk.hal_executor import HALCommandExecutor
from cap_sdk.intents import (
    DigIntent,
    DriveIntent,
    DumpIntent,
    LoadTruckIntent,
    StabilizeArmIntent,
    StopIntent,
    StopMode,
    SwingIntent,
    WaitForLoadIntent,
)


# ─── Helpers ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _StubPlan:
    """Minimal PlanLike for tests."""

    plan_id: str = "p"
    world_seq: int = 1
    body_envelope_hash: str = "b"
    zone_grid_hash: str = "z"
    waypoints: tuple = ((0.0, 0.0, 0.0), (5.0, 5.0, 0.0), (10.0, 10.0, 0.0))
    motion_types: tuple = (0, 1)
    headings: tuple = (0.0, 0.5, 1.0)
    expected_speed_mps: float = 1.5
    horizon_sec: float = 20.0


def _make_hal(*, success: bool = True, error: str = "") -> MagicMock:
    """Build a mock HAL whose send_command returns a configurable result."""
    hal = MagicMock()
    result = MagicMock()
    result.success = success
    result.error = error
    hal.send_command = AsyncMock(return_value=result)
    return hal


def _make_executor(hal: MagicMock, machine_type: str = "excavator") -> HALCommandExecutor:
    return HALCommandExecutor(hal, machine_id="zx120-01", machine_type=machine_type)


# ─── DriveIntent routing ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_drive_intent_excavator_uses_exc_drive_to() -> None:
    hal = _make_hal()
    executor = _make_executor(hal, machine_type="excavator")
    handle = make_handle(intent_kind="drive", machine_id="zx120-01")

    result = await executor(DriveIntent(machine_id="zx120-01", plan=_StubPlan()), handle)

    assert result == ExecutorResult.ACCEPTED
    hal.send_command.assert_called_once()
    cmd, params = hal.send_command.call_args[0]
    assert cmd.value == "exc_drive_to"
    assert params.target_x == 10.0
    assert params.target_y == 10.0
    assert params.waypoints == [(0.0, 0.0), (5.0, 5.0), (10.0, 10.0)]
    assert params.motion_types == [0, 1]
    assert params.headings == [0.0, 0.5, 1.0]


@pytest.mark.anyio
async def test_drive_intent_dump_truck_uses_truck_drive_to() -> None:
    hal = _make_hal()
    executor = _make_executor(hal, machine_type="dump_truck")
    handle = make_handle(intent_kind="drive", machine_id="ic120-01")

    result = await executor(DriveIntent(machine_id="ic120-01", plan=_StubPlan()), handle)

    assert result == ExecutorResult.ACCEPTED
    cmd, params = hal.send_command.call_args[0]
    assert cmd.value == "truck_drive_to"
    assert params.target_x == 10.0


@pytest.mark.anyio
async def test_drive_intent_unknown_machine_type_defaults_to_exc() -> None:
    """Unrecognised machine_type falls back to EXC_DRIVE_TO (safe default)."""
    hal = _make_hal()
    executor = _make_executor(hal, machine_type="robot_arm")
    handle = make_handle(intent_kind="drive", machine_id="x")

    result = await executor(DriveIntent(machine_id="x", plan=_StubPlan()), handle)

    assert result == ExecutorResult.ACCEPTED
    cmd, _ = hal.send_command.call_args[0]
    assert cmd.value == "exc_drive_to"


# ─── Non-drive intents ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_dig_intent_sends_exc_start_dig() -> None:
    hal = _make_hal()
    executor = _make_executor(hal)
    handle = make_handle(intent_kind="dig", machine_id="zx120-01")

    result = await executor(
        DigIntent(machine_id="zx120-01", target_volume_m3=0.8, bucket_capacity_m3=0.8),
        handle,
    )

    assert result == ExecutorResult.ACCEPTED
    cmd = hal.send_command.call_args[0][0]
    assert cmd.value == "exc_start_dig"
    assert handle.diagnostics["hal_command"] == "exc_start_dig"


@pytest.mark.anyio
async def test_swing_intent_sends_exc_swing_to_load() -> None:
    hal = _make_hal()
    executor = _make_executor(hal)
    handle = make_handle(intent_kind="swing", machine_id="zx120-01")

    result = await executor(
        SwingIntent(machine_id="zx120-01", target_yaw_rad=1.57),
        handle,
    )

    assert result == ExecutorResult.ACCEPTED
    cmd = hal.send_command.call_args[0][0]
    assert cmd.value == "exc_swing_to_load"


@pytest.mark.anyio
async def test_load_truck_intent_sends_exc_load_truck() -> None:
    hal = _make_hal()
    executor = _make_executor(hal)
    handle = make_handle(intent_kind="load_truck", machine_id="zx120-01")

    result = await executor(
        LoadTruckIntent(machine_id="zx120-01", truck_id="ic120-01", bucket_volume_m3=0.8),
        handle,
    )

    assert result == ExecutorResult.ACCEPTED
    cmd = hal.send_command.call_args[0][0]
    assert cmd.value == "exc_load_truck"


@pytest.mark.anyio
async def test_stabilize_arm_intent_sends_string_command() -> None:
    """StabilizeArmIntent uses a string command (not enum) for exc_stabilize_arm."""
    hal = _make_hal()
    executor = _make_executor(hal)
    handle = make_handle(intent_kind="stabilize_arm", machine_id="zx120-01")

    result = await executor(StabilizeArmIntent(machine_id="zx120-01"), handle)

    assert result == ExecutorResult.ACCEPTED
    # send_command is called with a plain string, not a HALCommand enum
    cmd = hal.send_command.call_args[0][0]
    assert cmd == "exc_stabilize_arm"
    assert handle.diagnostics["hal_command"] == "exc_stabilize_arm"


@pytest.mark.anyio
async def test_dump_intent_sends_truck_start_dump() -> None:
    hal = _make_hal()
    executor = _make_executor(hal, machine_type="dump_truck")
    handle = make_handle(intent_kind="dump", machine_id="ic120-01")

    result = await executor(DumpIntent(machine_id="ic120-01"), handle)

    assert result == ExecutorResult.ACCEPTED
    cmd = hal.send_command.call_args[0][0]
    assert cmd.value == "truck_start_dump"


@pytest.mark.anyio
async def test_wait_for_load_intent_sends_truck_wait_for_load() -> None:
    hal = _make_hal()
    executor = _make_executor(hal, machine_type="dump_truck")
    handle = make_handle(intent_kind="wait_for_load", machine_id="ic120-01")

    result = await executor(
        WaitForLoadIntent(machine_id="ic120-01", timeout_sec=30.0),
        handle,
    )

    assert result == ExecutorResult.ACCEPTED
    cmd = hal.send_command.call_args[0][0]
    assert cmd.value == "truck_wait_for_load"


@pytest.mark.anyio
async def test_stop_intent_sends_stop_with_machine_id_params() -> None:
    hal = _make_hal()
    executor = _make_executor(hal)
    handle = make_handle(intent_kind="stop", machine_id="zx120-01")

    result = await executor(
        StopIntent(machine_id="zx120-01", mode=StopMode.HARD, reason="cliff"),
        handle,
    )

    assert result == ExecutorResult.ACCEPTED
    assert hal.send_command.call_count == 1
    cmd, params = hal.send_command.call_args[0]
    assert cmd.value == "stop"
    assert params.machine_id == "zx120-01"


# ─── Success / rejection paths ───────────────────────────────────────


@pytest.mark.anyio
async def test_accepted_on_hal_success() -> None:
    hal = _make_hal(success=True)
    executor = _make_executor(hal)
    handle = make_handle(intent_kind="dig", machine_id="zx120-01")

    result = await executor(
        DigIntent(machine_id="zx120-01", target_volume_m3=0.8, bucket_capacity_m3=0.8),
        handle,
    )

    assert result == ExecutorResult.ACCEPTED
    assert "hal_error" not in handle.diagnostics


@pytest.mark.anyio
async def test_rejected_on_hal_failure_and_records_hal_error() -> None:
    hal = _make_hal(success=False, error="bridge unreachable")
    executor = _make_executor(hal)
    handle = make_handle(intent_kind="dig", machine_id="zx120-01")

    result = await executor(
        DigIntent(machine_id="zx120-01", target_volume_m3=0.8, bucket_capacity_m3=0.8),
        handle,
    )

    assert result == ExecutorResult.REJECTED
    assert handle.diagnostics.get("hal_error") == "bridge unreachable"


@pytest.mark.anyio
async def test_exception_propagates_and_records_hal_exception() -> None:
    """If send_command raises, the exception propagates (dispatcher will catch it)."""
    hal = MagicMock()
    hal.send_command = AsyncMock(side_effect=RuntimeError("connection lost"))
    executor = _make_executor(hal)
    handle = make_handle(intent_kind="dig", machine_id="zx120-01")

    with pytest.raises(RuntimeError, match="connection lost"):
        await executor(
            DigIntent(machine_id="zx120-01", target_volume_m3=0.8, bucket_capacity_m3=0.8),
            handle,
        )

    assert handle.diagnostics.get("hal_exception") == "RuntimeError"


# ─── Unknown intent ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_unknown_intent_raises_value_error() -> None:
    hal = _make_hal()
    executor = _make_executor(hal)
    handle = make_handle(intent_kind="weird", machine_id="zx120-01")

    class _Unknown:
        machine_id = "zx120-01"
        correlation_id = "c"
        task_id = ""

        @property
        def kind(self) -> Any:
            return MagicMock(value="weird")

    with pytest.raises(ValueError, match="unknown intent type"):
        await executor(_Unknown(), handle)  # type: ignore[arg-type]


# ─── hal_command diagnostic ──────────────────────────────────────────


@pytest.mark.anyio
async def test_hal_command_recorded_in_diagnostics_for_drive() -> None:
    hal = _make_hal()
    executor = _make_executor(hal, machine_type="excavator")
    handle = make_handle(intent_kind="drive", machine_id="zx120-01")

    await executor(DriveIntent(machine_id="zx120-01", plan=_StubPlan()), handle)

    assert handle.diagnostics["hal_command"] == "exc_drive_to"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"

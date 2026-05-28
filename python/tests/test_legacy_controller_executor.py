# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CAP Authors
"""Tests for LegacyControllerExecutor: Intent → (action, params) mapping
and end-to-end dispatch with a stub controller."""

# pylint: disable=missing-function-docstring,missing-class-docstring

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from cap_sdk.command_dispatcher import (
    CommandDispatcher,
    ExecutorResult,
)
from cap_sdk.command_handle import CommandHandle, CommandState, make_handle
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
from cap_sdk.legacy_controller_executor import (
    LegacyControllerExecutor,
    intent_to_controller_call,
)


@dataclass(frozen=True)
class _StubPlan:
    plan_id: str = "p"
    world_seq: int = 1
    body_envelope_hash: str = "b"
    zone_grid_hash: str = "z"
    waypoints: tuple = ((0.0, 0.0, 0.0), (5.0, 5.0, 0.5), (10.0, 10.0, 1.0))
    motion_types: tuple = (0, 1)
    headings: tuple = (0.0, 0.5, 1.0)
    expected_speed_mps: float = 1.0
    horizon_sec: float = 30.0


# ─── intent_to_controller_call: pure mapping ─────────────────────────


def test_drive_intent_maps_to_drive_to_action() -> None:
    intent = DriveIntent(machine_id="zx", plan=_StubPlan())
    action, params = intent_to_controller_call(intent)
    assert action == "drive_to"
    assert params["target_x"] == 10.0
    assert params["target_y"] == 10.0
    assert params["waypoints"] == [(0.0, 0.0), (5.0, 5.0), (10.0, 10.0)]
    assert params["motion_types"] == [0, 1]
    assert params["headings"] == [0.0, 0.5, 1.0]


def test_dig_intent_maps_to_start_dig() -> None:
    intent = DigIntent(
        machine_id="zx", target_volume_m3=8.0, bucket_capacity_m3=0.8,
    )
    action, params = intent_to_controller_call(intent)
    assert action == "start_dig"
    assert params == {"target_volume_m3": 8.0, "bucket_capacity_m3": 0.8}


def test_swing_intent_maps_to_swing_to_load() -> None:
    intent = SwingIntent(machine_id="zx", target_yaw_rad=1.5, truck_id="ic")
    action, params = intent_to_controller_call(intent)
    assert action == "swing_to_load"
    assert params == {"target_yaw_rad": 1.5, "truck_id": "ic"}


def test_load_truck_intent_maps() -> None:
    intent = LoadTruckIntent(
        machine_id="zx", truck_id="ic", bucket_volume_m3=0.8,
    )
    action, params = intent_to_controller_call(intent)
    assert action == "load_truck"
    assert params == {"truck_id": "ic", "bucket_volume_m3": 0.8}


def test_stabilize_arm_intent_maps() -> None:
    intent = StabilizeArmIntent(machine_id="zx")
    action, params = intent_to_controller_call(intent)
    assert action == "stabilize_arm"
    assert params == {}


def test_dump_intent_maps_to_start_dump() -> None:
    intent = DumpIntent(machine_id="ic")
    action, params = intent_to_controller_call(intent)
    assert action == "start_dump"
    assert params == {}


def test_wait_for_load_intent_maps() -> None:
    intent = WaitForLoadIntent(machine_id="ic", timeout_sec=120.0)
    action, params = intent_to_controller_call(intent)
    assert action == "wait_for_load"
    assert params == {"timeout_sec": 120.0}


def test_stop_intent_maps_with_mode_and_reason() -> None:
    intent = StopIntent(machine_id="zx", mode=StopMode.HARD, reason="cliff")
    action, params = intent_to_controller_call(intent)
    assert action == "stop"
    assert params == {"mode": "hard", "reason": "cliff"}


def test_unknown_intent_raises() -> None:
    class _UnknownIntent:
        machine_id = "x"
        correlation_id = "c"
        task_id = ""
        kind = "weird"
    with pytest.raises(ValueError, match="Unknown intent"):
        intent_to_controller_call(_UnknownIntent())  # type: ignore[arg-type]


def test_drive_intent_empty_plan_safe() -> None:
    """Plan with empty waypoints yields target=(0,0) safely (no IndexError)."""
    @dataclass(frozen=True)
    class _EmptyPlan:
        plan_id: str = "p"
        world_seq: int = 1
        body_envelope_hash: str = "b"
        zone_grid_hash: str = "z"
        waypoints: tuple = ()
        motion_types: tuple = ()
        headings: tuple = ()
        expected_speed_mps: float = 1.0
        horizon_sec: float = 30.0

    intent = DriveIntent(machine_id="zx", plan=_EmptyPlan())
    action, params = intent_to_controller_call(intent)
    assert action == "drive_to"
    assert params["target_x"] == 0.0
    assert params["target_y"] == 0.0
    assert params["waypoints"] == []


# ─── LegacyControllerExecutor: end-to-end ───────────────────────────


class _StubLegacyController:
    """Records every (action, params) call. Configurable result."""

    def __init__(self, *, default_status: str = "ok") -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._status = default_status
        self._async = False
        self._raise = False

    def set_status(self, status: str) -> None:
        self._status = status

    def make_async(self) -> None:
        self._async = True

    def make_raise(self) -> None:
        self._raise = True

    def handle_command(
        self, action: str, params: dict[str, Any],
    ) -> dict[str, Any] | Any:
        self.calls.append((action, params))
        if self._raise:
            raise RuntimeError("simulated controller failure")
        if self._async:
            async def _async_result():
                return {"status": self._status}
            return _async_result()
        return {"status": self._status}


@pytest.mark.anyio
async def test_executor_translates_drive_to_action() -> None:
    controller = _StubLegacyController()
    executor = LegacyControllerExecutor(controller.handle_command)
    handle = make_handle(intent_kind="drive", machine_id="zx")
    result = await executor(
        DriveIntent(machine_id="zx", plan=_StubPlan()), handle,
    )
    assert result == ExecutorResult.ACCEPTED
    assert len(controller.calls) == 1
    action, params = controller.calls[0]
    assert action == "drive_to"
    assert params["target_x"] == 10.0


@pytest.mark.anyio
async def test_executor_marks_legacy_action_in_diagnostics() -> None:
    controller = _StubLegacyController()
    executor = LegacyControllerExecutor(controller.handle_command)
    handle = make_handle(intent_kind="dig", machine_id="zx")
    await executor(
        DigIntent(machine_id="zx", target_volume_m3=8.0, bucket_capacity_m3=0.8),
        handle,
    )
    assert handle.diagnostics["legacy_action"] == "start_dig"


@pytest.mark.anyio
async def test_executor_handles_async_controller() -> None:
    controller = _StubLegacyController()
    controller.make_async()
    executor = LegacyControllerExecutor(controller.handle_command)
    handle = make_handle(intent_kind="drive", machine_id="zx")
    result = await executor(
        DriveIntent(machine_id="zx", plan=_StubPlan()), handle,
    )
    assert result == ExecutorResult.ACCEPTED


@pytest.mark.anyio
async def test_executor_propagates_error_status_as_rejected() -> None:
    controller = _StubLegacyController(default_status="error")
    executor = LegacyControllerExecutor(controller.handle_command)
    handle = make_handle(intent_kind="dig", machine_id="zx")
    result = await executor(
        DigIntent(machine_id="zx", target_volume_m3=8.0, bucket_capacity_m3=0.8),
        handle,
    )
    assert result == ExecutorResult.REJECTED


@pytest.mark.anyio
async def test_executor_no_op_status() -> None:
    controller = _StubLegacyController(default_status="no_op")
    executor = LegacyControllerExecutor(controller.handle_command)
    handle = make_handle(intent_kind="dig", machine_id="zx")
    result = await executor(
        DigIntent(machine_id="zx", target_volume_m3=8.0, bucket_capacity_m3=0.8),
        handle,
    )
    assert result == ExecutorResult.NO_OP


@pytest.mark.anyio
async def test_executor_propagates_exception() -> None:
    controller = _StubLegacyController()
    controller.make_raise()
    executor = LegacyControllerExecutor(controller.handle_command)
    handle = make_handle(intent_kind="dig", machine_id="zx")
    with pytest.raises(RuntimeError):
        await executor(
            DigIntent(machine_id="zx", target_volume_m3=8.0, bucket_capacity_m3=0.8),
            handle,
        )


@pytest.mark.anyio
async def test_executor_none_return_treated_as_accepted() -> None:
    """Some legacy controllers may return None — treat as accepted."""

    class _NoneController:
        def handle_command(self, action, params):
            return None

    executor = LegacyControllerExecutor(_NoneController().handle_command)
    handle = make_handle(intent_kind="dig", machine_id="zx")
    result = await executor(
        DigIntent(machine_id="zx", target_volume_m3=8.0, bucket_capacity_m3=0.8),
        handle,
    )
    assert result == ExecutorResult.ACCEPTED


# ─── End-to-end: Dispatcher + LegacyExecutor + StubController ─────────


@pytest.mark.anyio
async def test_e2e_dispatcher_drives_legacy_controller() -> None:
    controller = _StubLegacyController()
    executor = LegacyControllerExecutor(controller.handle_command)
    disp = CommandDispatcher(machine_id="zx", executor=executor)

    handle = await disp.dispatch(
        DriveIntent(machine_id="zx", plan=_StubPlan(), correlation_id="c-1"),
    )
    assert handle.state == CommandState.EXECUTING
    assert len(controller.calls) == 1
    action, _ = controller.calls[0]
    assert action == "drive_to"

    # Simulate phases
    await disp.notify_phase("moving_to_dig")
    assert handle.state == CommandState.EXECUTING
    await disp.notify_phase("idle")
    assert handle.state == CommandState.COMPLETED


@pytest.mark.anyio
async def test_e2e_idempotent_dispatch_does_not_duplicate_legacy_call() -> None:
    """Re-dispatching same intent → only ONE controller call."""
    controller = _StubLegacyController()
    executor = LegacyControllerExecutor(controller.handle_command)
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    intent = DriveIntent(
        machine_id="zx", plan=_StubPlan(), correlation_id="dup",
    )
    h1 = await disp.dispatch(intent)
    h2 = await disp.dispatch(intent)
    assert h1 is h2
    assert len(controller.calls) == 1


@pytest.mark.anyio
async def test_e2e_stop_intent_dispatches_stop_action() -> None:
    controller = _StubLegacyController()
    executor = LegacyControllerExecutor(controller.handle_command)
    disp = CommandDispatcher(machine_id="zx", executor=executor)
    await disp.dispatch(
        DriveIntent(machine_id="zx", plan=_StubPlan(), correlation_id="d-1"),
    )
    stop_handle = await disp.dispatch(
        StopIntent(
            machine_id="zx", mode=StopMode.HARD, reason="cliff",
            correlation_id="s-1",
        ),
    )
    # Both controller.handle_command calls happened (drive + stop)
    actions = [a for a, _ in controller.calls]
    assert actions == ["drive_to", "stop"]
    # Stop completes immediately (no phase to wait for)
    assert stop_handle.state == CommandState.COMPLETED


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"

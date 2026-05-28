# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0
"""LegacyControllerExecutor — bridges Intent dispatch to existing
``handle_command(action, params)`` controllers.

Many simulator/bridge-side controllers take ``(action: str, params: dict)``
tuples. The newer dispatcher in cap_sdk is driven by typed Intent
dataclasses, so this adapter translates between the two and lets the
dispatcher drive legacy controllers without rewriting them.

  Agent           Dispatcher          Adapter (this)        Controller
  ─────           ──────────          ──────────────        ──────────
  dispatch ───►  handle.QUEUED ───► (action, params) ──► handle_command
  wait_for ◄──── handle.EXECUTING                       returns {"status": "ok"}
  ...           handle.last_phase  ◄──── notify_phase ◄── controller.phase
  ...           handle.COMPLETED   ◄──── notify_phase ◄── (terminal phase)

The adapter is **stateless** — all idempotency / preemption decisions
live in the dispatcher; this just maps an Intent to the legacy call
shape.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .command_dispatcher import ExecutorResult
from .command_handle import CommandHandle
from .intents import (
    DigIntent,
    DriveIntent,
    DumpIntent,
    Intent,
    LoadTruckIntent,
    StabilizeArmIntent,
    StopIntent,
    SwingIntent,
    WaitForLoadIntent,
)


# Type alias for the controller's ``handle_command`` API. Returns
# something like ``{"status": "ok"}`` or ``{"status": "error", ...}``.
ControllerHandleCommand = Callable[
    [str, dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]],
]


def intent_to_controller_call(intent: Intent) -> tuple[str, dict[str, Any]]:
    """Convert an Intent into a legacy ``(action, params)`` pair.

    Pure function; throws ``ValueError`` for unknown intent types.
    """
    if isinstance(intent, DriveIntent):
        plan = intent.plan
        # Plan waypoints carry (x, y, yaw); the controller wants (x, y) + headings.
        wps_xy = [(wp[0], wp[1]) for wp in plan.waypoints]
        target_x = wps_xy[-1][0] if wps_xy else 0.0
        target_y = wps_xy[-1][1] if wps_xy else 0.0
        return "drive_to", {
            "target_x": target_x,
            "target_y": target_y,
            "waypoints": wps_xy,
            "motion_types": list(plan.motion_types),
            "headings": list(plan.headings),
        }

    if isinstance(intent, DigIntent):
        return "start_dig", {
            "target_volume_m3": intent.target_volume_m3,
            "bucket_capacity_m3": intent.bucket_capacity_m3,
        }

    if isinstance(intent, SwingIntent):
        return "swing_to_load", {
            "target_yaw_rad": intent.target_yaw_rad,
            "truck_id": intent.truck_id,
        }

    if isinstance(intent, LoadTruckIntent):
        return "load_truck", {
            "truck_id": intent.truck_id,
            "bucket_volume_m3": intent.bucket_volume_m3,
        }

    if isinstance(intent, StabilizeArmIntent):
        return "stabilize_arm", {}

    if isinstance(intent, DumpIntent):
        return "start_dump", {}

    if isinstance(intent, WaitForLoadIntent):
        return "wait_for_load", {"timeout_sec": intent.timeout_sec}

    if isinstance(intent, StopIntent):
        return "stop", {"mode": intent.mode.value, "reason": intent.reason}

    raise ValueError(f"Unknown intent type: {type(intent).__name__}")


class LegacyControllerExecutor:
    """ControllerExecutor that delegates to a legacy ``handle_command``.

    Construct one per controller (excavator or truck). The bridge's
    ``CommandDispatcher`` calls this; the executor invokes
    ``controller.handle_command(action, params)`` and translates the
    return shape into ``ExecutorResult``.
    """

    def __init__(self, handle_command: ControllerHandleCommand) -> None:
        self._handle_command = handle_command

    async def __call__(
        self, intent: Intent, handle: CommandHandle,
    ) -> str:
        action, params = intent_to_controller_call(intent)
        # Annotate the handle for telemetry / debugging.
        handle.diagnostics["legacy_action"] = action

        try:
            result = self._handle_command(action, params)
            # Support both sync and async legacy controllers.
            if hasattr(result, "__await__"):
                result = await result  # type: ignore[func-returns-value]
        except Exception as exc:  # noqa: BLE001
            handle.diagnostics["executor_exception"] = type(exc).__name__
            raise

        if not isinstance(result, dict):
            return ExecutorResult.ACCEPTED  # legacy may return None
        status = result.get("status", "ok")
        if status == "ok":
            return ExecutorResult.ACCEPTED
        if status == "error":
            handle.diagnostics["controller_error"] = str(result.get("message", ""))
            return ExecutorResult.REJECTED
        if status == "no_op":
            return ExecutorResult.NO_OP
        return ExecutorResult.ACCEPTED


__all__ = [
    "ControllerHandleCommand",
    "LegacyControllerExecutor",
    "intent_to_controller_call",
]

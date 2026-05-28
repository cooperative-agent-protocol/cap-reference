# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0
"""HALCommandExecutor — ControllerExecutor that drives the agent-side MachineHAL.

Translates a typed ``Intent`` into the corresponding ``HALCommand`` /
``send_command()`` call. This is the *agent-side* counterpart to
``LegacyControllerExecutor`` (which lives on the bridge side).

  Agent                      HALCommandExecutor              HAL bridge
  ─────                      ──────────────────              ──────────
  dispatch(intent) ──────► send_command(cmd, params) ──────► controller
  handle.EXECUTING ◄────── ACCEPTED result ◄──────────────── {"ok": true}
  handle.wait_for(COMPLETED)   ← driven by CommandOrchestrator.notify_phase

The executor is stateless — all idempotency / preemption decisions
live in ``CommandDispatcher``; this module only maps Intent → HAL call.
"""

from __future__ import annotations

import logging

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

logger = logging.getLogger(__name__)

# ─── HAL command / params imports (avoid hard dep on cap_sdk.hal at load time
#     so this module stays importable in pure-Python test environments that
#     don't have the full HAL stack).  We import lazily inside the class.


class HALCommandExecutor:
    """ControllerExecutor that translates Intents to MachineHAL.send_command() calls.

    Args:
        hal: The MachineHAL instance for this machine.
        machine_id: Identifier (e.g. ``"zx120-01"``), used for StopParams and
            diagnostics.
        machine_type: ``"excavator"`` or ``"dump_truck"`` — controls which
            HALCommand constant is used for DriveIntent (``EXC_DRIVE_TO`` vs
            ``TRUCK_DRIVE_TO``).  Defaults to empty string; if unrecognised,
            ``EXC_DRIVE_TO`` is used as a safe fallback.
    """

    def __init__(
        self,
        hal: object,
        machine_id: str,
        machine_type: str = "",
    ) -> None:
        self._hal = hal
        self._machine_id = machine_id
        self._machine_type = machine_type.lower()

    async def __call__(
        self,
        intent: Intent,
        handle: CommandHandle,
    ) -> str:
        """Apply ``intent`` via HAL and return one of ``ExecutorResult.*``."""
        try:
            result = await self._dispatch(intent, handle)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[%s] HALCommandExecutor: intent=%s raised",
                self._machine_id, type(intent).__name__,
            )
            handle.diagnostics["hal_exception"] = type(exc).__name__
            raise

        if result is None or not result.success:
            error_msg = getattr(result, "error", "unknown HAL error") if result else "null result"
            logger.warning(
                "[%s] HALCommandExecutor: intent=%s rejected: %s",
                self._machine_id, type(intent).__name__, error_msg,
            )
            handle.diagnostics["hal_error"] = str(error_msg)
            return ExecutorResult.REJECTED

        return ExecutorResult.ACCEPTED

    async def _dispatch(
        self,
        intent: Intent,
        handle: CommandHandle,
    ) -> object:
        """Map intent → HALCommand + params and call send_command."""
        # Import HAL constants lazily to stay importable in test isolation.
        from .hal import (  # noqa: PLC0415
            ExcDriveToParams,
            ExcMoveToParams,
            HALCommand,
            StopParams,
            TruckDriveToParams,
        )

        if isinstance(intent, DriveIntent):
            handle.diagnostics["hal_action"] = "drive_to"
            plan = intent.plan
            wps_xy = [(wp[0], wp[1]) for wp in plan.waypoints]
            target_x = wps_xy[-1][0] if wps_xy else 0.0
            target_y = wps_xy[-1][1] if wps_xy else 0.0

            if self._machine_type == "dump_truck":
                handle.diagnostics["hal_command"] = HALCommand.TRUCK_DRIVE_TO.value
                return await self._hal.send_command(
                    HALCommand.TRUCK_DRIVE_TO,
                    TruckDriveToParams(
                        target_x=target_x,
                        target_y=target_y,
                        waypoints=wps_xy,
                        motion_types=list(plan.motion_types),
                        headings=list(plan.headings),
                    ),
                )
            else:
                # excavator (default)
                handle.diagnostics["hal_command"] = HALCommand.EXC_DRIVE_TO.value
                return await self._hal.send_command(
                    HALCommand.EXC_DRIVE_TO,
                    ExcDriveToParams(
                        target_x=target_x,
                        target_y=target_y,
                        waypoints=wps_xy,
                        motion_types=list(plan.motion_types),
                        headings=list(plan.headings),
                    ),
                )

        if isinstance(intent, DigIntent):
            handle.diagnostics["hal_command"] = HALCommand.EXC_START_DIG.value
            return await self._hal.send_command(HALCommand.EXC_START_DIG)

        if isinstance(intent, SwingIntent):
            handle.diagnostics["hal_command"] = HALCommand.EXC_SWING_TO_LOAD.value
            return await self._hal.send_command(HALCommand.EXC_SWING_TO_LOAD)

        if isinstance(intent, LoadTruckIntent):
            handle.diagnostics["hal_command"] = HALCommand.EXC_LOAD_TRUCK.value
            return await self._hal.send_command(HALCommand.EXC_LOAD_TRUCK)

        if isinstance(intent, StabilizeArmIntent):
            handle.diagnostics["hal_command"] = "exc_stabilize_arm"
            return await self._hal.send_command("exc_stabilize_arm")

        if isinstance(intent, DumpIntent):
            handle.diagnostics["hal_command"] = HALCommand.TRUCK_START_DUMP.value
            return await self._hal.send_command(HALCommand.TRUCK_START_DUMP)

        if isinstance(intent, WaitForLoadIntent):
            handle.diagnostics["hal_command"] = HALCommand.TRUCK_WAIT_FOR_LOAD.value
            return await self._hal.send_command(HALCommand.TRUCK_WAIT_FOR_LOAD)

        if isinstance(intent, StopIntent):
            handle.diagnostics["hal_command"] = HALCommand.STOP.value
            return await self._hal.send_command(
                HALCommand.STOP,
                StopParams(machine_id=self._machine_id),
            )

        raise ValueError(f"HALCommandExecutor: unknown intent type: {type(intent).__name__}")


__all__ = ["HALCommandExecutor"]

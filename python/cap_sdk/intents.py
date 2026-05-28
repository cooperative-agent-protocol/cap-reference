# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0
"""Intent — declarative replacement for the legacy "imperative action" HAL.

The legacy ``HAL.send_command(action, params)`` mutated controller
state on every call. When Gemini batched multiple tool calls in a
single think, the controller's timer reset repeatedly — visible as
the "首ブンブン" arm oscillation. The idempotent guards added in
``excavator_controller.py`` and ``truck_controller.py`` were band-aids
for an API that should have been state-declarative from the start.

Intents are *declarative*:

  * Re-submitting the same Intent (same ``correlation_id``, same
    payload) while it is in-flight is a **no-op** — the dispatcher
    returns the existing CommandHandle.
  * A *different* Intent on the same ``correlation_id`` **preempts**
    the prior one through the dispatcher's lifecycle.

Intent payloads are pure-Python dataclasses (frozen). The wire form
is in ``cap-spec/proto/cap/v0/intent.proto``; codecs live in
``agent/site/world/codec.py`` (server side) and a future
``cap_sdk/intent_codec.py`` (client side, when needed).

This module imports only from the standard library so it is safe to
include from cap_sdk consumers running on the bridge / runner side.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class IntentKind(str, Enum):
    """Kind tag for telemetry and dispatcher routing."""

    DRIVE = "drive"
    DIG = "dig"
    SWING = "swing"
    LOAD_TRUCK = "load_truck"
    STABILIZE_ARM = "stabilize_arm"
    DUMP = "dump"
    WAIT_FOR_LOAD = "wait_for_load"
    STOP = "stop"


class AbortPolicy(str, Enum):
    """Per-intent override for the safety supervisor's abort behavior."""

    UNSPECIFIED = "unspecified"
    ABORT_ON_VIOLATION = "abort_on_violation"  # default
    DEGRADE_THEN_ABORT = "degrade_then_abort"
    FORCE = "force"  # testing only


@runtime_checkable
class PlanLike(Protocol):
    """Duck-typed handle for an implementation's PlanContract value type.

    cap_sdk does not import or depend on any implementation's plan
    object directly; instead it accepts any object that exposes the
    binding identifiers, waypoints, and headings listed below.
    """

    plan_id: str
    world_seq: int
    body_envelope_hash: str
    zone_grid_hash: str
    waypoints: tuple[tuple[float, float, float], ...]
    motion_types: tuple[int, ...]
    headings: tuple[float, ...]
    expected_speed_mps: float
    horizon_sec: float


def _new_correlation_id() -> str:
    """Default correlation id when the caller doesn't supply one.

    For idempotency to work, the *caller* should reuse the same id
    across re-submits. A fresh id makes every dispatch unique.
    """
    return uuid.uuid4().hex[:16]


# ─── Concrete Intents ────────────────────────────────────────────────


@dataclass(frozen=True)
class DriveIntent:
    """Follow a planned path."""

    machine_id: str
    plan: PlanLike
    abort_policy: AbortPolicy = AbortPolicy.ABORT_ON_VIOLATION
    correlation_id: str = field(default_factory=_new_correlation_id)
    task_id: str = ""

    @property
    def kind(self) -> IntentKind:
        return IntentKind.DRIVE


@dataclass(frozen=True)
class DigIntent:
    """Excavate at the current pose until target_volume_m3 is reached."""

    machine_id: str
    target_volume_m3: float
    bucket_capacity_m3: float
    correlation_id: str = field(default_factory=_new_correlation_id)
    task_id: str = ""

    @property
    def kind(self) -> IntentKind:
        return IntentKind.DIG


@dataclass(frozen=True)
class SwingIntent:
    """Rotate the upper carriage to the target body heading."""

    machine_id: str
    target_yaw_rad: float
    truck_id: str = ""
    correlation_id: str = field(default_factory=_new_correlation_id)
    task_id: str = ""

    @property
    def kind(self) -> IntentKind:
        return IntentKind.SWING


@dataclass(frozen=True)
class LoadTruckIntent:
    """Discharge bucket payload onto the named truck."""

    machine_id: str
    truck_id: str
    bucket_volume_m3: float
    correlation_id: str = field(default_factory=_new_correlation_id)
    task_id: str = ""

    @property
    def kind(self) -> IntentKind:
        return IntentKind.LOAD_TRUCK


@dataclass(frozen=True)
class StabilizeArmIntent:
    """Move arm to stable carry pose."""

    machine_id: str
    correlation_id: str = field(default_factory=_new_correlation_id)
    task_id: str = ""

    @property
    def kind(self) -> IntentKind:
        return IntentKind.STABILIZE_ARM


@dataclass(frozen=True)
class DumpIntent:
    """Truck-side: bed up to dump payload."""

    machine_id: str
    correlation_id: str = field(default_factory=_new_correlation_id)
    task_id: str = ""

    @property
    def kind(self) -> IntentKind:
        return IntentKind.DUMP


@dataclass(frozen=True)
class WaitForLoadIntent:
    """Truck-side: hold ready-to-load posture."""

    machine_id: str
    timeout_sec: float = 0.0  # 0 = no timeout
    correlation_id: str = field(default_factory=_new_correlation_id)
    task_id: str = ""

    @property
    def kind(self) -> IntentKind:
        return IntentKind.WAIT_FOR_LOAD


class StopMode(str, Enum):
    GRACEFUL = "graceful"
    HARD = "hard"
    HOLD = "hold"


@dataclass(frozen=True)
class StopIntent:
    """Unified cancel / preempt channel.

    Replaces:
      * ``movement.py::_abort_motion`` (drive_to error path)
      * ``unity_mobility_interface.py::stop()`` (legacy direct calls)
      * ``navigate_segmented_path``'s mandatory ``self.stop()`` before
        run-queue swap.

    All three collapse to one StopIntent with the appropriate ``mode``.
    """

    machine_id: str
    mode: StopMode = StopMode.GRACEFUL
    reason: str = ""
    correlation_id: str = field(default_factory=_new_correlation_id)
    task_id: str = ""

    @property
    def kind(self) -> IntentKind:
        return IntentKind.STOP


# Convenience type alias (Python 3.10+ syntax via runtime evaluation).
Intent = (
    DriveIntent
    | DigIntent
    | SwingIntent
    | LoadTruckIntent
    | StabilizeArmIntent
    | DumpIntent
    | WaitForLoadIntent
    | StopIntent
)


def intent_payload(intent: Intent) -> dict[str, Any]:
    """Serialize the kind-specific payload to a plain dict.

    Used by the bridge dispatcher when adapting an Intent into the
    legacy controller's dict-based ``handle_command(action, params)``
    API for backward compatibility.
    """
    if isinstance(intent, DriveIntent):
        return {
            "abort_policy": intent.abort_policy.value,
            "plan_id": intent.plan.plan_id,
            "world_seq": intent.plan.world_seq,
            "body_envelope_hash": intent.plan.body_envelope_hash,
            "zone_grid_hash": intent.plan.zone_grid_hash,
            "waypoints": list(intent.plan.waypoints),
            "motion_types": list(intent.plan.motion_types),
            "headings": list(intent.plan.headings),
            "expected_speed_mps": intent.plan.expected_speed_mps,
        }
    if isinstance(intent, DigIntent):
        return {
            "target_volume_m3": intent.target_volume_m3,
            "bucket_capacity_m3": intent.bucket_capacity_m3,
        }
    if isinstance(intent, SwingIntent):
        return {
            "target_yaw_rad": intent.target_yaw_rad,
            "truck_id": intent.truck_id,
        }
    if isinstance(intent, LoadTruckIntent):
        return {
            "truck_id": intent.truck_id,
            "bucket_volume_m3": intent.bucket_volume_m3,
        }
    if isinstance(intent, WaitForLoadIntent):
        return {"timeout_sec": intent.timeout_sec}
    if isinstance(intent, StopIntent):
        return {"mode": intent.mode.value, "reason": intent.reason}
    # StabilizeArmIntent and DumpIntent have no payload.
    return {}


__all__ = [
    "AbortPolicy",
    "DigIntent",
    "DriveIntent",
    "DumpIntent",
    "Intent",
    "IntentKind",
    "LoadTruckIntent",
    "PlanLike",
    "StabilizeArmIntent",
    "StopIntent",
    "StopMode",
    "SwingIntent",
    "WaitForLoadIntent",
    "intent_payload",
]

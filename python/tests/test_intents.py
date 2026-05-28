# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CAP Authors
"""Tests for Intent dataclasses + payload serialization."""

# pylint: disable=missing-function-docstring,missing-class-docstring

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from cap_sdk.intents import (
    AbortPolicy,
    DigIntent,
    DriveIntent,
    DumpIntent,
    Intent,
    IntentKind,
    LoadTruckIntent,
    PlanLike,
    StabilizeArmIntent,
    StopIntent,
    StopMode,
    SwingIntent,
    WaitForLoadIntent,
    intent_payload,
)


@dataclass(frozen=True)
class _StubPlan:
    """Minimal PlanLike implementation used only by these tests."""

    plan_id: str = "p-test"
    world_seq: int = 1
    body_envelope_hash: str = "body-x"
    zone_grid_hash: str = "zone-y"
    waypoints: tuple = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
    motion_types: tuple = (0,)
    headings: tuple = (0.0, 0.0)
    expected_speed_mps: float = 1.0
    horizon_sec: float = 30.0


# ─── Construction + frozen invariants ────────────────────────────────


def test_drive_intent_kind() -> None:
    intent = DriveIntent(machine_id="zx120", plan=_StubPlan())
    assert intent.kind == IntentKind.DRIVE


def test_dig_intent_kind() -> None:
    intent = DigIntent(
        machine_id="zx120", target_volume_m3=8.0, bucket_capacity_m3=0.8,
    )
    assert intent.kind == IntentKind.DIG


def test_swing_intent_kind() -> None:
    intent = SwingIntent(machine_id="zx120", target_yaw_rad=1.5)
    assert intent.kind == IntentKind.SWING


def test_load_truck_intent_kind() -> None:
    intent = LoadTruckIntent(
        machine_id="zx120", truck_id="ic120-01", bucket_volume_m3=0.8,
    )
    assert intent.kind == IntentKind.LOAD_TRUCK


def test_stabilize_arm_intent_kind() -> None:
    intent = StabilizeArmIntent(machine_id="zx120")
    assert intent.kind == IntentKind.STABILIZE_ARM


def test_dump_intent_kind() -> None:
    intent = DumpIntent(machine_id="ic120")
    assert intent.kind == IntentKind.DUMP


def test_wait_for_load_intent_kind() -> None:
    intent = WaitForLoadIntent(machine_id="ic120", timeout_sec=60.0)
    assert intent.kind == IntentKind.WAIT_FOR_LOAD


def test_stop_intent_kind() -> None:
    intent = StopIntent(machine_id="zx120", mode=StopMode.HARD, reason="cliff ahead")
    assert intent.kind == IntentKind.STOP


def test_intent_is_frozen() -> None:
    intent = DriveIntent(machine_id="zx", plan=_StubPlan())
    with pytest.raises((AttributeError, TypeError)):
        intent.machine_id = "other"  # type: ignore[misc]


def test_correlation_id_unique_when_default() -> None:
    a = DriveIntent(machine_id="x", plan=_StubPlan())
    b = DriveIntent(machine_id="x", plan=_StubPlan())
    assert a.correlation_id != b.correlation_id


def test_correlation_id_explicit_preserved() -> None:
    intent = DriveIntent(
        machine_id="zx", plan=_StubPlan(), correlation_id="caller-123",
    )
    assert intent.correlation_id == "caller-123"


# ─── PlanLike Protocol satisfaction ──────────────────────────────────
# (The cross-package check that the real PlanContract satisfies
# PlanLike lives in the agent backend's test suite, where ``alg``
# is importable. cap-reference avoids that import to preserve DDD
# layer separation.)


def test_stub_plan_satisfies_plan_like() -> None:
    """The local _StubPlan satisfies the Protocol (runtime check)."""
    assert isinstance(_StubPlan(), PlanLike)


# ─── intent_payload ──────────────────────────────────────────────────


def test_drive_intent_payload_includes_plan_fields() -> None:
    plan = _StubPlan(world_seq=42, expected_speed_mps=1.5)
    intent = DriveIntent(
        machine_id="zx", plan=plan, abort_policy=AbortPolicy.DEGRADE_THEN_ABORT,
    )
    payload = intent_payload(intent)
    assert payload["plan_id"] == plan.plan_id
    assert payload["world_seq"] == 42
    assert payload["abort_policy"] == AbortPolicy.DEGRADE_THEN_ABORT.value
    assert payload["expected_speed_mps"] == 1.5


def test_dig_intent_payload() -> None:
    intent = DigIntent(
        machine_id="zx", target_volume_m3=8.0, bucket_capacity_m3=0.8,
    )
    payload = intent_payload(intent)
    assert payload == {"target_volume_m3": 8.0, "bucket_capacity_m3": 0.8}


def test_swing_intent_payload() -> None:
    intent = SwingIntent(machine_id="zx", target_yaw_rad=1.5, truck_id="ic")
    payload = intent_payload(intent)
    assert payload == {"target_yaw_rad": 1.5, "truck_id": "ic"}


def test_load_truck_intent_payload() -> None:
    intent = LoadTruckIntent(
        machine_id="zx", truck_id="ic", bucket_volume_m3=0.8,
    )
    payload = intent_payload(intent)
    assert payload == {"truck_id": "ic", "bucket_volume_m3": 0.8}


def test_stabilize_arm_intent_no_payload() -> None:
    intent = StabilizeArmIntent(machine_id="zx")
    assert intent_payload(intent) == {}


def test_dump_intent_no_payload() -> None:
    intent = DumpIntent(machine_id="ic")
    assert intent_payload(intent) == {}


def test_wait_for_load_intent_payload() -> None:
    intent = WaitForLoadIntent(machine_id="ic", timeout_sec=120.0)
    assert intent_payload(intent) == {"timeout_sec": 120.0}


def test_stop_intent_payload() -> None:
    intent = StopIntent(machine_id="zx", mode=StopMode.HARD, reason="cliff")
    payload = intent_payload(intent)
    assert payload == {"mode": "hard", "reason": "cliff"}


# ─── Intent type alias usable as runtime annotation ──────────────────


def test_intent_type_union_resolution() -> None:
    """All concrete Intents are compatible with the Intent type alias."""
    intents: list[Intent] = [
        DriveIntent(machine_id="zx", plan=_StubPlan()),
        DigIntent(machine_id="zx", target_volume_m3=8.0, bucket_capacity_m3=0.8),
        SwingIntent(machine_id="zx", target_yaw_rad=0.0),
        LoadTruckIntent(machine_id="zx", truck_id="ic", bucket_volume_m3=0.8),
        StabilizeArmIntent(machine_id="zx"),
        DumpIntent(machine_id="ic"),
        WaitForLoadIntent(machine_id="ic"),
        StopIntent(machine_id="zx"),
    ]
    # All of them satisfy the union; just verify it doesn't error at runtime.
    assert len(intents) == 8


# ─── Idempotency contract (correlation_id semantics) ─────────────────


def test_same_correlation_id_different_plan_different_payload() -> None:
    """Two DriveIntents with same correlation_id but different plans
    are distinct objects (the dispatcher uses correlation_id +
    payload-equality to decide idempotent vs preempt).
    """
    plan_a = _StubPlan(plan_id="a")
    plan_b = _StubPlan(plan_id="b")
    intent_a = DriveIntent(machine_id="zx", plan=plan_a, correlation_id="X")
    intent_b = DriveIntent(machine_id="zx", plan=plan_b, correlation_id="X")
    assert intent_a != intent_b
    assert intent_a.correlation_id == intent_b.correlation_id


def test_identical_intents_compare_equal() -> None:
    plan = _StubPlan()
    intent_a = DriveIntent(
        machine_id="zx", plan=plan, correlation_id="X",
    )
    intent_b = DriveIntent(
        machine_id="zx", plan=plan, correlation_id="X",
    )
    assert intent_a == intent_b

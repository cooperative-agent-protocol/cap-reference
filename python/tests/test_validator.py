# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for cap_sdk.validator."""

import uuid

from cap.v0.core import common_pb2, machine_agent_pb2, runtime_pb2, site_agent_pb2, events_pb2, dialogue_pb2, error_pb2
from cap_sdk.validator import validate_frame, validate_state_transition


def _make_header(**overrides):
    defaults = {
        "message_id": str(uuid.uuid4()),
        "sender_id": "test-sender",
    }
    defaults.update(overrides)
    return common_pb2.MessageHeader(**defaults)


# ── validate_frame: header ──────────────────────────────────


class TestValidateFrameHeader:
    def test_empty_body_returns_error(self):
        frame = runtime_pb2.CapFrame(header=_make_header())
        errors = validate_frame(frame)
        assert any("body is empty" in e for e in errors)

    def test_missing_message_id(self):
        frame = runtime_pb2.CapFrame(
            header=_make_header(message_id=""),
            heartbeat=machine_agent_pb2.Heartbeat(
                machine_id="exc-01",
                current_mode=common_pb2.MACHINE_MODE_SUPERVISED_AUTONOMY,
            ),
        )
        errors = validate_frame(frame)
        assert any("message_id" in e for e in errors)

    def test_missing_sender_id(self):
        frame = runtime_pb2.CapFrame(
            header=_make_header(sender_id=""),
            heartbeat=machine_agent_pb2.Heartbeat(
                machine_id="exc-01",
                current_mode=common_pb2.MACHINE_MODE_SUPERVISED_AUTONOMY,
            ),
        )
        errors = validate_frame(frame)
        assert any("sender_id" in e for e in errors)

    def test_valid_heartbeat_frame(self):
        frame = runtime_pb2.CapFrame(
            header=_make_header(),
            heartbeat=machine_agent_pb2.Heartbeat(
                machine_id="exc-01",
                current_mode=common_pb2.MACHINE_MODE_SUPERVISED_AUTONOMY,
            ),
        )
        errors = validate_frame(frame)
        assert errors == []


# ── validate_frame: body types ──────────────────────────────


class TestValidateManifest:
    def test_empty_machine_id(self):
        frame = runtime_pb2.CapFrame(
            header=_make_header(),
            capability_manifest=machine_agent_pb2.CapabilityManifest(
                machine_id="",
                machine_type=common_pb2.MACHINE_TYPE_EXCAVATOR,
                current_mode=common_pb2.MACHINE_MODE_SUPERVISED_AUTONOMY,
            ),
        )
        errors = validate_frame(frame)
        assert any("machine_id" in e for e in errors)

    def test_unspecified_machine_type(self):
        frame = runtime_pb2.CapFrame(
            header=_make_header(),
            capability_manifest=machine_agent_pb2.CapabilityManifest(
                machine_id="exc-01",
                machine_type=common_pb2.MACHINE_TYPE_UNSPECIFIED,
                current_mode=common_pb2.MACHINE_MODE_SUPERVISED_AUTONOMY,
            ),
        )
        errors = validate_frame(frame)
        assert any("UNSPECIFIED" in e for e in errors)

    def test_valid_manifest(self):
        frame = runtime_pb2.CapFrame(
            header=_make_header(),
            capability_manifest=machine_agent_pb2.CapabilityManifest(
                machine_id="exc-01",
                machine_type=common_pb2.MACHINE_TYPE_EXCAVATOR,
                current_mode=common_pb2.MACHINE_MODE_SUPERVISED_AUTONOMY,
            ),
        )
        assert validate_frame(frame) == []


class TestValidateWorkOrder:
    def test_empty_task_id(self):
        frame = runtime_pb2.CapFrame(
            header=_make_header(),
            work_order=site_agent_pb2.WorkOrder(task_id="", skill="excavate"),
        )
        errors = validate_frame(frame)
        assert any("task_id" in e for e in errors)

    def test_empty_skill(self):
        frame = runtime_pb2.CapFrame(
            header=_make_header(),
            work_order=site_agent_pb2.WorkOrder(task_id="t-1", skill=""),
        )
        errors = validate_frame(frame)
        assert any("skill" in e for e in errors)

    def test_valid_work_order(self):
        frame = runtime_pb2.CapFrame(
            header=_make_header(),
            work_order=site_agent_pb2.WorkOrder(task_id="t-1", skill="excavate"),
        )
        assert validate_frame(frame) == []


class TestValidateProgressEvent:
    def test_unspecified_state(self):
        frame = runtime_pb2.CapFrame(
            header=_make_header(),
            progress_event=events_pb2.ProgressEvent(
                task_id="t-1",
                state=common_pb2.TASK_STATE_UNSPECIFIED,
            ),
        )
        errors = validate_frame(frame)
        assert any("UNSPECIFIED" in e for e in errors)

    def test_succeeded_requires_ratio_1(self):
        frame = runtime_pb2.CapFrame(
            header=_make_header(),
            progress_event=events_pb2.ProgressEvent(
                task_id="t-1",
                state=common_pb2.TASK_STATE_SUCCEEDED,
                completion_ratio=0.5,
            ),
        )
        errors = validate_frame(frame)
        assert any("completion_ratio" in e for e in errors)

    def test_valid_progress(self):
        frame = runtime_pb2.CapFrame(
            header=_make_header(),
            progress_event=events_pb2.ProgressEvent(
                task_id="t-1",
                state=common_pb2.TASK_STATE_RUNNING,
                completion_ratio=0.5,
            ),
        )
        assert validate_frame(frame) == []


# ── validate_state_transition ────────────────────────────────


class TestValidateStateTransition:
    def test_pending_to_accepted(self):
        valid, reason = validate_state_transition(
            common_pb2.TASK_STATE_PENDING, common_pb2.TASK_STATE_ACCEPTED,
        )
        assert valid
        assert reason == ""

    def test_running_to_succeeded(self):
        valid, _ = validate_state_transition(
            common_pb2.TASK_STATE_RUNNING, common_pb2.TASK_STATE_SUCCEEDED,
        )
        assert valid

    def test_running_to_running_is_ignore(self):
        valid, reason = validate_state_transition(
            common_pb2.TASK_STATE_RUNNING, common_pb2.TASK_STATE_RUNNING,
        )
        assert valid
        assert "IGNORE" in reason

    def test_terminal_state_cannot_transition(self):
        valid, reason = validate_state_transition(
            common_pb2.TASK_STATE_SUCCEEDED, common_pb2.TASK_STATE_RUNNING,
        )
        assert not valid
        assert "terminal" in reason

    def test_invalid_transition(self):
        valid, reason = validate_state_transition(
            common_pb2.TASK_STATE_PENDING, common_pb2.TASK_STATE_RUNNING,
        )
        assert not valid
        assert "invalid transition" in reason

    def test_blocked_to_running(self):
        valid, _ = validate_state_transition(
            common_pb2.TASK_STATE_BLOCKED, common_pb2.TASK_STATE_RUNNING,
        )
        assert valid

    def test_all_terminal_states_reject_transitions(self):
        terminals = [
            common_pb2.TASK_STATE_SUCCEEDED,
            common_pb2.TASK_STATE_FAILED,
            common_pb2.TASK_STATE_CANCELLED,
            common_pb2.TASK_STATE_REJECTED,
            common_pb2.TASK_STATE_EXPIRED,
        ]
        for state in terminals:
            valid, _ = validate_state_transition(state, common_pb2.TASK_STATE_RUNNING)
            assert not valid, f"Terminal state {state} should not allow transition"

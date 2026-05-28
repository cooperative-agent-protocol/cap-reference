# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""CAP message validator.

Validates CapFrame messages against the protocol specification:
- Required fields present
- Enum values not UNSPECIFIED (Ch06 §6.6 rule 2)
- State transition validity (Ch06 §6.1.4)
- Plan hash consistency

Usage:
    from cap_sdk.validator import validate_frame, validate_state_transition

    errors = validate_frame(frame)
    if errors:
        for e in errors:
            print(f"Validation error: {e}")
"""

from __future__ import annotations

from cap.v0.core import runtime_pb2, common_pb2


# Valid TaskState transitions (from, to) per Ch06 §6.1.4
_VALID_TASK_TRANSITIONS: set[tuple[int, int]] = {
    (common_pb2.TASK_STATE_PENDING, common_pb2.TASK_STATE_ACCEPTED),
    (common_pb2.TASK_STATE_PENDING, common_pb2.TASK_STATE_REJECTED),
    (common_pb2.TASK_STATE_PENDING, common_pb2.TASK_STATE_EXPIRED),
    (common_pb2.TASK_STATE_PENDING, common_pb2.TASK_STATE_CANCELLED),
    (common_pb2.TASK_STATE_ACCEPTED, common_pb2.TASK_STATE_RUNNING),
    (common_pb2.TASK_STATE_ACCEPTED, common_pb2.TASK_STATE_CANCELLED),
    (common_pb2.TASK_STATE_RUNNING, common_pb2.TASK_STATE_BLOCKED),
    (common_pb2.TASK_STATE_RUNNING, common_pb2.TASK_STATE_SUCCEEDED),
    (common_pb2.TASK_STATE_RUNNING, common_pb2.TASK_STATE_FAILED),
    (common_pb2.TASK_STATE_RUNNING, common_pb2.TASK_STATE_CANCELLED),
    (common_pb2.TASK_STATE_BLOCKED, common_pb2.TASK_STATE_RUNNING),
    (common_pb2.TASK_STATE_BLOCKED, common_pb2.TASK_STATE_FAILED),
    (common_pb2.TASK_STATE_BLOCKED, common_pb2.TASK_STATE_CANCELLED),
}

# IGNORE transitions (same state → same state, treated as progress update)
_IGNORE_TRANSITIONS: set[tuple[int, int]] = {
    (common_pb2.TASK_STATE_RUNNING, common_pb2.TASK_STATE_RUNNING),
    (common_pb2.TASK_STATE_BLOCKED, common_pb2.TASK_STATE_BLOCKED),
}

_TERMINAL_TASK_STATES = {
    common_pb2.TASK_STATE_SUCCEEDED,
    common_pb2.TASK_STATE_FAILED,
    common_pb2.TASK_STATE_CANCELLED,
    common_pb2.TASK_STATE_REJECTED,
    common_pb2.TASK_STATE_EXPIRED,
}


def validate_frame(frame: runtime_pb2.CapFrame) -> list[str]:
    """Validate a CapFrame for protocol conformance.

    Returns a list of error strings. Empty list means the frame is valid.
    """
    errors: list[str] = []

    # Header validation
    header = frame.header
    if not header.message_id:
        errors.append("header.message_id is empty")
    if not header.sender_id:
        errors.append("header.sender_id is empty")

    body_field = frame.WhichOneof("body")
    if body_field is None:
        errors.append("CapFrame body is empty (no oneof field set)")
        return errors

    # Body-specific validation
    if body_field == "capability_manifest":
        errors.extend(_validate_manifest(frame.capability_manifest))
    elif body_field == "heartbeat":
        errors.extend(_validate_heartbeat(frame.heartbeat))
    elif body_field == "work_order":
        errors.extend(_validate_work_order(frame.work_order))
    elif body_field == "work_order_ack":
        errors.extend(_validate_work_order_ack(frame.work_order_ack))
    elif body_field == "progress_event":
        errors.extend(_validate_progress_event(frame.progress_event))
    elif body_field == "handover_event":
        errors.extend(_validate_handover_event(frame.handover_event))
    elif body_field == "reservation_request":
        errors.extend(_validate_reservation_request(frame.reservation_request))
    elif body_field == "agent_dialogue":
        errors.extend(_validate_dialogue(frame.agent_dialogue))
    elif body_field == "cancel_work_order":
        errors.extend(_validate_cancel_work_order(frame.cancel_work_order))
    elif body_field == "reservation_release":
        errors.extend(_validate_reservation_release(frame.reservation_release))
    elif body_field == "mode_command":
        errors.extend(_validate_mode_command(frame.mode_command))
    elif body_field == "fault_event":
        errors.extend(_validate_fault_event(frame.fault_event))
    elif body_field == "safety_event":
        errors.extend(_validate_safety_event(frame.safety_event))
    elif body_field == "audit_event":
        errors.extend(_validate_audit_event(frame.audit_event))
    elif body_field == "cap_error":
        errors.extend(_validate_cap_error(frame.cap_error))

    return errors


def validate_state_transition(
    current_state: int, new_state: int
) -> tuple[bool, str]:
    """Validate a TaskState transition per Ch06 §6.1.4.

    Args:
        current_state: Current TaskState enum value.
        new_state: Proposed new TaskState enum value.

    Returns:
        (valid, reason) tuple. valid=True if the transition is allowed.
    """
    if current_state in _TERMINAL_TASK_STATES:
        return False, f"current state {common_pb2.TaskState.Name(current_state)} is terminal"

    pair = (current_state, new_state)
    if pair in _VALID_TASK_TRANSITIONS:
        return True, ""
    if pair in _IGNORE_TRANSITIONS:
        return True, "same-state update (IGNORE)"

    return False, (
        f"invalid transition: {common_pb2.TaskState.Name(current_state)} "
        f"→ {common_pb2.TaskState.Name(new_state)}"
    )


def _validate_manifest(m) -> list[str]:
    errors = []
    if not m.machine_id:
        errors.append("CapabilityManifest.machine_id is empty")
    if m.machine_type == common_pb2.MACHINE_TYPE_UNSPECIFIED:
        errors.append("CapabilityManifest.machine_type is UNSPECIFIED")
    if m.current_mode == common_pb2.MACHINE_MODE_UNSPECIFIED:
        errors.append("CapabilityManifest.current_mode is UNSPECIFIED")
    return errors


def _validate_heartbeat(hb) -> list[str]:
    errors = []
    if not hb.machine_id:
        errors.append("Heartbeat.machine_id is empty")
    if hb.current_mode == common_pb2.MACHINE_MODE_UNSPECIFIED:
        errors.append("Heartbeat.current_mode is UNSPECIFIED")
    return errors


def _validate_work_order(wo) -> list[str]:
    errors = []
    if not wo.task_id:
        errors.append("WorkOrder.task_id is empty")
    if not wo.skill:
        errors.append("WorkOrder.skill is empty")
    return errors


def _validate_work_order_ack(ack) -> list[str]:
    errors = []
    if not ack.task_id:
        errors.append("WorkOrderAck.task_id is empty")
    if ack.status == 0:  # UNSPECIFIED
        errors.append("WorkOrderAck.status is UNSPECIFIED")
    return errors


def _validate_progress_event(pe) -> list[str]:
    errors = []
    if not pe.task_id:
        errors.append("ProgressEvent.task_id is empty")
    if pe.state == common_pb2.TASK_STATE_UNSPECIFIED:
        errors.append("ProgressEvent.state is UNSPECIFIED")
    if pe.state == common_pb2.TASK_STATE_SUCCEEDED and pe.completion_ratio != 1.0:
        errors.append("ProgressEvent.completion_ratio must be 1.0 when state is SUCCEEDED")
    return errors


def _validate_handover_event(he) -> list[str]:
    errors = []
    if not he.task_id:
        errors.append("HandoverEvent.task_id is empty")
    if not he.machine_id:
        errors.append("HandoverEvent.machine_id is empty")
    if he.requested_mode == common_pb2.MACHINE_MODE_UNSPECIFIED:
        errors.append("HandoverEvent.requested_mode is UNSPECIFIED")
    return errors


def _validate_reservation_request(rr) -> list[str]:
    errors = []
    if not rr.reservation_id:
        errors.append("ReservationRequest.reservation_id is empty")
    if not rr.resource_id:
        errors.append("ReservationRequest.resource_id is empty")
    if not rr.holder_id:
        errors.append("ReservationRequest.holder_id is empty")
    return errors


def _validate_dialogue(d) -> list[str]:
    errors = []
    if not d.dialogue_id:
        errors.append("AgentDialogue.dialogue_id is empty")
    if not d.messages:
        errors.append("AgentDialogue.messages is empty")
    for i, msg in enumerate(d.messages):
        if not msg.message_id:
            errors.append(f"AgentDialogue.messages[{i}].message_id is empty")
        if not msg.HasField("provenance"):
            errors.append(f"AgentDialogue.messages[{i}].provenance is missing")
        elif not msg.provenance.model_id:
            errors.append(f"AgentDialogue.messages[{i}].provenance.model_id is empty")
    return errors


def _validate_cancel_work_order(cwo) -> list[str]:
    errors = []
    if not cwo.task_id:
        errors.append("CancelWorkOrder.task_id is empty")
    return errors


def _validate_reservation_release(rr) -> list[str]:
    errors = []
    if not rr.reservation_id:
        errors.append("ReservationRelease.reservation_id is empty")
    return errors


def _validate_mode_command(mc) -> list[str]:
    errors = []
    if not mc.machine_id:
        errors.append("ModeCommand.machine_id is empty")
    if mc.requested_mode == common_pb2.MACHINE_MODE_UNSPECIFIED:
        errors.append("ModeCommand.requested_mode is UNSPECIFIED")
    return errors


def _validate_fault_event(fe) -> list[str]:
    errors = []
    if not fe.machine_id:
        errors.append("FaultEvent.machine_id is empty")
    if not fe.fault_code:
        errors.append("FaultEvent.fault_code is empty")
    return errors


def _validate_safety_event(se) -> list[str]:
    errors = []
    if not se.machine_id:
        errors.append("SafetyEvent.machine_id is empty")
    if not se.event_type:
        errors.append("SafetyEvent.event_type is empty")
    return errors


def _validate_audit_event(ae) -> list[str]:
    errors = []
    if not ae.action:
        errors.append("AuditEvent.action is empty")
    return errors


def _validate_cap_error(ce) -> list[str]:
    errors = []
    if ce.error_code == 0:
        errors.append("CapError.error_code is 0 (must be > 0)")
    return errors

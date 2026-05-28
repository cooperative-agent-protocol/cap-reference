# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Helpers for building CapFrame messages."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from google.protobuf.timestamp_pb2 import Timestamp

from cap.v0.core import common_pb2, runtime_pb2, error_pb2
from cap.v0.core import site_agent_pb2, machine_agent_pb2, events_pb2, alo_pb2, dialogue_pb2


def _now_ts() -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(datetime.now(timezone.utc))
    return ts


def make_header(
    *,
    sender_id: str,
    receiver_id: str,
    work_package_id: str = "",
    plan_hash: str = "",
    correlation_id: str = "",
) -> common_pb2.MessageHeader:
    """Create a MessageHeader with auto-generated message_id and timestamp."""
    return common_pb2.MessageHeader(
        message_id=str(uuid.uuid4()),
        sender_id=sender_id,
        receiver_id=receiver_id,
        correlation_id=correlation_id,
        work_package_id=work_package_id,
        plan_hash=plan_hash,
        sent_at=_now_ts(),
    )


def wrap_work_order(
    header: common_pb2.MessageHeader,
    work_order: site_agent_pb2.WorkOrder,
) -> runtime_pb2.ConnectRequest:
    """Wrap a WorkOrder into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, work_order=work_order)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_capability_manifest(
    header: common_pb2.MessageHeader,
    manifest: machine_agent_pb2.CapabilityManifest,
) -> runtime_pb2.ConnectRequest:
    """Wrap a CapabilityManifest into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, capability_manifest=manifest)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_heartbeat(
    header: common_pb2.MessageHeader,
    heartbeat: machine_agent_pb2.Heartbeat,
) -> runtime_pb2.ConnectRequest:
    """Wrap a Heartbeat into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, heartbeat=heartbeat)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_work_order_ack(
    header: common_pb2.MessageHeader,
    ack: machine_agent_pb2.WorkOrderAck,
) -> runtime_pb2.ConnectRequest:
    """Wrap a WorkOrderAck into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, work_order_ack=ack)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_progress_event(
    header: common_pb2.MessageHeader,
    event: events_pb2.ProgressEvent,
) -> runtime_pb2.ConnectRequest:
    """Wrap a ProgressEvent into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, progress_event=event)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_handover_event(
    header: common_pb2.MessageHeader,
    event: events_pb2.HandoverEvent,
) -> runtime_pb2.ConnectRequest:
    """Wrap a HandoverEvent into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, handover_event=event)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_alo_state_update(
    header: common_pb2.MessageHeader,
    update: alo_pb2.ALOStateUpdate,
) -> runtime_pb2.ConnectRequest:
    """Wrap an ALOStateUpdate into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, alo_state_update=update)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_alo_interaction(
    header: common_pb2.MessageHeader,
    interaction: alo_pb2.ALOInteraction,
) -> runtime_pb2.ConnectRequest:
    """Wrap an ALOInteraction into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, alo_interaction=interaction)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_agent_dialogue(
    header: common_pb2.MessageHeader,
    dialogue: dialogue_pb2.AgentDialogue,
) -> runtime_pb2.ConnectRequest:
    """Wrap an AgentDialogue into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, agent_dialogue=dialogue)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_cancel_work_order(
    header: common_pb2.MessageHeader,
    cancel: site_agent_pb2.CancelWorkOrder,
) -> runtime_pb2.ConnectRequest:
    """Wrap a CancelWorkOrder into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, cancel_work_order=cancel)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_reservation_request(
    header: common_pb2.MessageHeader,
    request: site_agent_pb2.ReservationRequest,
) -> runtime_pb2.ConnectRequest:
    """Wrap a ReservationRequest into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, reservation_request=request)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_reservation_release(
    header: common_pb2.MessageHeader,
    release: site_agent_pb2.ReservationRelease,
) -> runtime_pb2.ConnectRequest:
    """Wrap a ReservationRelease into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, reservation_release=release)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_mode_command(
    header: common_pb2.MessageHeader,
    command: site_agent_pb2.ModeCommand,
) -> runtime_pb2.ConnectRequest:
    """Wrap a ModeCommand into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, mode_command=command)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_reservation_status(
    header: common_pb2.MessageHeader,
    status: events_pb2.ReservationStatus,
) -> runtime_pb2.ConnectRequest:
    """Wrap a ReservationStatus into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, reservation_status=status)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_fault_event(
    header: common_pb2.MessageHeader,
    event: events_pb2.FaultEvent,
) -> runtime_pb2.ConnectRequest:
    """Wrap a FaultEvent into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, fault_event=event)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_safety_event(
    header: common_pb2.MessageHeader,
    event: events_pb2.SafetyEvent,
) -> runtime_pb2.ConnectRequest:
    """Wrap a SafetyEvent into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, safety_event=event)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_audit_event(
    header: common_pb2.MessageHeader,
    event: events_pb2.AuditEvent,
) -> runtime_pb2.ConnectRequest:
    """Wrap an AuditEvent into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, audit_event=event)
    return runtime_pb2.ConnectRequest(frame=frame)


def wrap_cap_error(
    header: common_pb2.MessageHeader,
    error: error_pb2.CapError,
) -> runtime_pb2.ConnectRequest:
    """Wrap a CapError into a ConnectRequest."""
    frame = runtime_pb2.CapFrame(header=header, cap_error=error)
    return runtime_pb2.ConnectRequest(frame=frame)


# ─── Dialogue Convenience Helpers ───────────────────────────────────


def make_clarification_request(
    *,
    requester_id: str,
    task_id: str,
    question: str,
    options: list[str] | None = None,
    context: str = "",
) -> dialogue_pb2.ClarificationRequest:
    """Create a ClarificationRequest message."""
    return dialogue_pb2.ClarificationRequest(
        requester_id=requester_id,
        task_id=task_id,
        question=question,
        options=options or [],
        context=context,
    )


def make_risk_notice(
    *,
    machine_id: str,
    task_id: str,
    risk_summary: str,
    severity: int = 1,
    mitigation_suggestion: str = "",
) -> dialogue_pb2.RiskNotice:
    """Create a RiskNotice message."""
    return dialogue_pb2.RiskNotice(
        machine_id=machine_id,
        task_id=task_id,
        risk_summary=risk_summary,
        severity=severity,
        mitigation_suggestion=mitigation_suggestion,
    )


def make_execution_commit(
    *,
    machine_id: str,
    task_id: str,
    commit_summary: str,
    conditions: list[str] | None = None,
) -> dialogue_pb2.ExecutionCommit:
    """Create an ExecutionCommit message."""
    return dialogue_pb2.ExecutionCommit(
        machine_id=machine_id,
        task_id=task_id,
        commit_summary=commit_summary,
        conditions=conditions or [],
    )


def make_subgoal_complete(
    *,
    machine_id: str,
    task_id: str,
    subgoal_description: str,
    progress_percent: float = 0.0,
) -> dialogue_pb2.SubgoalComplete:
    """Create a SubgoalComplete message."""
    return dialogue_pb2.SubgoalComplete(
        machine_id=machine_id,
        task_id=task_id,
        subgoal_description=subgoal_description,
        progress_percent=progress_percent,
    )


def make_handover_request(
    *,
    machine_id: str,
    task_id: str,
    reason: str,
    severity: int = 0,
    recommended_action: str = "",
) -> dialogue_pb2.HandoverRequest:
    """Create a HandoverRequest dialogue message."""
    return dialogue_pb2.HandoverRequest(
        machine_id=machine_id,
        task_id=task_id,
        reason=reason,
        severity=severity,
        recommended_action=recommended_action,
    )

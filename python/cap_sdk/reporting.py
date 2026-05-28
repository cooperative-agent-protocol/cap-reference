# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Reporting protocol — what Machine Agents report to Site Agents.

Human analogy: a skilled worker reports milestones, issues, and requests to
their supervisor. They do NOT report every micro-decision or internal reasoning.

Reporting rules:
  REPORT: milestones, periodic status, issues, approval requests, completion
  DO NOT REPORT: micro-decisions, raw sensor data, internal reasoning, compacting
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from .agent_types import DialogueIntent, TaskState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reporting Policy
# ---------------------------------------------------------------------------

# Event types that are always reported immediately
MILESTONE_EVENTS: frozenset[str] = frozenset({
    "task_started",
    "task_phase_changed",
    "task_completed",
    "task_failed",
    "handover_requested",
})

# Event types that are always reported immediately
ISSUE_EVENTS: frozenset[str] = frozenset({
    "obstacle_detected",
    "geofence_warning",
    "fuel_low",
    "equipment_fault",
    "unexpected_state",
})

# Event types that are NEVER reported (internal only)
SUPPRESSED_EVENTS: frozenset[str] = frozenset({
    "micro_decision",
    "bucket_angle_adjusted",
    "path_waypoint_reached",
    "heartbeat_sent",
    "state_read",
    "context_compacted",
})


@dataclass
class ReportingPolicy:
    """Controls what and when the machine agent reports to site agent.

    Attributes:
        periodic_interval_sec: How often to send periodic status reports.
        periodic_interval_cycles: Or every N think cycles, whichever comes first.
        milestone_events: Events that trigger immediate reporting.
        issue_events: Events that trigger immediate reporting.
        suppressed_events: Events that are never reported.
    """

    periodic_interval_sec: float = 30.0
    periodic_interval_cycles: int = 5
    milestone_events: frozenset[str] = MILESTONE_EVENTS
    issue_events: frozenset[str] = ISSUE_EVENTS
    suppressed_events: frozenset[str] = SUPPRESSED_EVENTS

    def should_report(self, event_type: str) -> bool:
        """Check if an event type should be reported to site agent."""
        if event_type in self.suppressed_events:
            return False
        if event_type in self.milestone_events:
            return True
        if event_type in self.issue_events:
            return True
        return False

    def classify(self, event_type: str) -> Literal["suppressed", "milestone", "issue", "periodic"]:
        """Classify event type for reporting."""
        if event_type in self.suppressed_events:
            return "suppressed"
        if event_type in self.milestone_events:
            return "milestone"
        if event_type in self.issue_events:
            return "issue"
        return "periodic"


# ---------------------------------------------------------------------------
# Report → CAP Protocol mapping
# ---------------------------------------------------------------------------


def build_progress_event_dict(
    machine_id: str,
    task_id: str,
    completion_ratio: float,
    summary: str,
    state: TaskState = TaskState.RUNNING,
    metrics: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a ProgressEvent-compatible dict for sending via CAP protocol.

    Maps to: cap.v0.events_pb2.ProgressEvent
    """
    return {
        "type": "progress_event",
        "machine_id": machine_id,
        "task_id": task_id,
        "state": state.value,
        "completion_ratio": completion_ratio,
        "summary": summary,
        "metrics": metrics or {},
    }


def build_dialogue_dict(
    sender_id: str,
    receiver_id: str,
    task_id: str,
    intent: DialogueIntent,
    content: dict[str, Any] | str,
) -> dict[str, Any]:
    """Build an AgentDialogue-compatible dict for sending via CAP protocol.

    Maps to: cap.v0.dialogue_pb2.AgentDialogue

    Args:
        intent: DialogueIntent enum value.
        content: For situation_report/local_decision/plan_proposal, a dict with
                 structured fields. For ack/instruction/query, a string (free text).
    """
    dialogue_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    msg: dict[str, Any] = {
        "message_id": message_id,
        "intent": intent.value,
    }

    if isinstance(content, str):
        msg["text"] = content
    elif intent == DialogueIntent.SITUATION_REPORT:
        msg["situation_report"] = {
            "machine_id": sender_id,
            "task_id": task_id,
            "situation_summary": content.get("summary", ""),
            "recommended_action": content.get("recommended_action", ""),
        }
    elif intent == DialogueIntent.LOCAL_DECISION:
        msg["local_decision"] = {
            "machine_id": sender_id,
            "task_id": task_id,
            "scope": content.get("scope", "micro"),
            "decision_summary": content.get("summary", ""),
            "rationale": content.get("rationale", ""),
            "approval_required": content.get("scope", "micro") != "micro",
        }
    elif intent == DialogueIntent.PLAN_PROPOSAL:
        msg["plan_proposal"] = {
            "machine_id": sender_id,
            "task_id": task_id,
            "proposal_summary": content.get("summary", ""),
            "expected_outcome": content.get("expected_outcome", ""),
        }

    return {
        "type": "agent_dialogue",
        "dialogue_id": dialogue_id,
        "participant_ids": [sender_id, receiver_id],
        "task_id": task_id,
        "messages": [msg],
    }


# ---------------------------------------------------------------------------
# Report classification helper
# ---------------------------------------------------------------------------


@dataclass
class ReportTracker:
    """Tracks reporting state for periodic status updates."""

    policy: ReportingPolicy = field(default_factory=ReportingPolicy)
    _last_periodic_time: float = 0.0
    _cycles_since_periodic: int = 0

    def tick(self, current_time: float) -> bool:
        """Check if a periodic report is due. Call once per think cycle."""
        self._cycles_since_periodic += 1
        time_due = (current_time - self._last_periodic_time) >= self.policy.periodic_interval_sec
        cycle_due = self._cycles_since_periodic >= self.policy.periodic_interval_cycles

        if time_due or cycle_due:
            self._last_periodic_time = current_time
            self._cycles_since_periodic = 0
            return True
        return False

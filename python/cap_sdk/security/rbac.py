# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""RBAC enforcement for CAP protocol messages.

Implements the Role × Message authorization matrix from Ch09 §9.3.2.
"""

from __future__ import annotations

import enum
import logging
from typing import NamedTuple

from cap.v0.core import runtime_pb2, common_pb2

logger = logging.getLogger(__name__)


class Role(enum.Enum):
    """CAP roles per Ch09 §9.3.1."""
    SITE_ADMIN = "site_admin"
    OPERATOR = "operator"
    MACHINE_AGENT = "machine_agent"
    OBSERVER = "observer"


class AuthDecision(NamedTuple):
    allowed: bool
    reason: str


# Body field names as returned by CapFrame.WhichOneof("body")
_BODY_FIELDS = {
    # Site Agent → Machine Agent
    "work_order", "cancel_work_order", "reservation_request",
    "reservation_release", "mode_command",
    # Machine Agent → Site Agent
    "capability_manifest", "heartbeat", "work_order_ack",
    # Events
    "reservation_status", "progress_event", "fault_event",
    "handover_event", "safety_event", "audit_event",
    # ALO
    "alo_state_update", "alo_interaction",
    # Dialogue
    "agent_dialogue",
    # Error
    "cap_error",
}

# Authorization matrix: role → set of allowed body field names.
# Derived from Ch09 §9.3.2 table.
_ALLOW_MATRIX: dict[Role, set[str]] = {
    Role.SITE_ADMIN: {
        "work_order", "cancel_work_order", "reservation_request",
        "reservation_release", "mode_command",
        "audit_event", "agent_dialogue", "cap_error",
        "reservation_status",
    },
    Role.OPERATOR: {
        "work_order", "cancel_work_order", "mode_command",
        "audit_event", "agent_dialogue", "cap_error",
    },
    Role.MACHINE_AGENT: {
        "reservation_request", "reservation_release",
        "capability_manifest", "heartbeat", "work_order_ack",
        "progress_event", "fault_event", "handover_event",
        "safety_event", "audit_event",
        "alo_state_update", "alo_interaction",
        "agent_dialogue", "cap_error",
    },
    Role.OBSERVER: set(),  # Read-only; cannot send any CapFrame body
}


class RBACEnforcer:
    """Enforces the CAP RBAC authorization matrix.

    Usage:
        enforcer = RBACEnforcer()
        decision = enforcer.check(Role.MACHINE_AGENT, frame)
        if not decision.allowed:
            # send CapError(3006)
    """

    def __init__(self) -> None:
        self._allow_matrix = dict(_ALLOW_MATRIX)

    def check(self, role: Role, frame: runtime_pb2.CapFrame) -> AuthDecision:
        """Check whether a role is authorized to send this frame.

        Args:
            role: The sender's role.
            frame: The CapFrame to check.

        Returns:
            AuthDecision with allowed flag and reason.
        """
        body_field = frame.WhichOneof("body")
        if body_field is None:
            return AuthDecision(False, "empty CapFrame body")

        allowed_fields = self._allow_matrix.get(role, set())

        if body_field not in allowed_fields:
            reason = f"role '{role.value}' cannot send '{body_field}'"
            logger.warning("RBAC DENY: %s (sender=%s)", reason, frame.header.sender_id)
            return AuthDecision(False, reason)

        # Special case: operator cannot send ModeCommand(AUTONOMY) — Ch09 §9.3.2 footnote 1
        if (
            role == Role.OPERATOR
            and body_field == "mode_command"
            and frame.mode_command.requested_mode == common_pb2.MACHINE_MODE_AUTONOMY
        ):
            reason = "operator cannot authorize AUTONOMY mode (site_admin required)"
            logger.warning("RBAC DENY: %s (sender=%s)", reason, frame.header.sender_id)
            return AuthDecision(False, reason)

        return AuthDecision(True, "")

    def role_for_machine_id(self, machine_id: str) -> Role:
        """Default role assignment: machine agents get MACHINE_AGENT role."""
        return Role.MACHINE_AGENT

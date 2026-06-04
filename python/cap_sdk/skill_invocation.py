# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Helpers for RFC-0001 typed ``SkillInvocation`` payloads.

The helpers are intentionally domain-agnostic: callers pass any protobuf
message from a Domain Pack, and CAP-Core carries it through
``SkillInvocation.typed_params`` as ``google.protobuf.Any``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from cap.v0.core import site_agent_pb2, skill_pb2
from google.protobuf.message import Message

_M = TypeVar("_M", bound=Message)


def make_skill_invocation(
    *,
    skill_id: str,
    typed_params: Message | None = None,
    skill_name: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> skill_pb2.SkillInvocation:
    """Create a ``SkillInvocation`` and optionally pack typed params into it."""
    if not str(skill_id).strip():
        raise ValueError("skill_id is required")
    invocation = skill_pb2.SkillInvocation(
        skill_id=str(skill_id),
        skill_name=str(skill_name or ""),
    )
    if typed_params is not None:
        pack_typed_params(invocation, typed_params)
    if metadata:
        invocation.metadata.update({str(k): str(v) for k, v in metadata.items()})
    return invocation


def pack_typed_params(
    invocation: skill_pb2.SkillInvocation,
    typed_params: Message,
) -> skill_pb2.SkillInvocation:
    """Pack a protobuf message into ``invocation.typed_params`` and return it."""
    if not isinstance(typed_params, Message):
        raise TypeError("typed_params must be a protobuf Message")
    invocation.typed_params.Pack(typed_params)
    return invocation


def typed_params_type_url(invocation: skill_pb2.SkillInvocation) -> str:
    """Return the ``Any.type_url`` for an invocation, or ``""`` when absent."""
    return str(invocation.typed_params.type_url)


def unpack_typed_params(
    invocation: skill_pb2.SkillInvocation,
    message_type: type[_M],
) -> _M | None:
    """Unpack typed params as ``message_type``.

    Returns ``None`` when ``Any`` is empty or the embedded type does not match.
    """
    out = message_type()
    if not invocation.typed_params.Unpack(out):
        return None
    return out


def require_typed_params(
    invocation: skill_pb2.SkillInvocation,
    message_type: type[_M],
) -> _M:
    """Unpack typed params as ``message_type`` or raise ``TypeError``."""
    out = unpack_typed_params(invocation, message_type)
    if out is not None:
        return out
    wanted = getattr(message_type, "DESCRIPTOR", None)
    wanted_name = getattr(wanted, "full_name", repr(message_type))
    raise TypeError(
        f"SkillInvocation typed_params {typed_params_type_url(invocation)!r} "
        f"cannot be unpacked as {wanted_name}"
    )


def attach_invocation(message: Message, invocation: skill_pb2.SkillInvocation) -> Message:
    """Copy ``invocation`` into a protobuf message that has an ``invocation`` field."""
    try:
        message.invocation.CopyFrom(invocation)  # type: ignore[attr-defined]
    except AttributeError as exc:
        raise TypeError("message does not have an invocation field") from exc
    return message


def set_work_order_invocation(
    work_order: site_agent_pb2.WorkOrder,
    *,
    skill_id: str | None = None,
    typed_params: Message | None = None,
    skill_name: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> site_agent_pb2.WorkOrder:
    """Populate ``WorkOrder.invocation`` without touching legacy fields."""
    invocation = make_skill_invocation(
        skill_id=skill_id or work_order.skill,
        skill_name=work_order.skill if skill_name is None else skill_name,
        typed_params=typed_params,
        metadata=metadata,
    )
    work_order.invocation.CopyFrom(invocation)
    return work_order


def set_skill_execution_invocation(
    execution: skill_pb2.SkillExecution,
    *,
    skill_id: str | None = None,
    typed_params: Message | None = None,
    skill_name: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> skill_pb2.SkillExecution:
    """Populate ``SkillExecution.invocation`` without touching legacy fields."""
    invocation = make_skill_invocation(
        skill_id=skill_id or execution.skill_id,
        skill_name=skill_name,
        typed_params=typed_params,
        metadata=metadata,
    )
    execution.invocation.CopyFrom(invocation)
    return execution


__all__ = [
    "attach_invocation",
    "make_skill_invocation",
    "pack_typed_params",
    "require_typed_params",
    "set_skill_execution_invocation",
    "set_work_order_invocation",
    "typed_params_type_url",
    "unpack_typed_params",
]

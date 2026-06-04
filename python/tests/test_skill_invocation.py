# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 CAP Authors
"""Tests for RFC-0001 typed SkillInvocation helpers."""

from __future__ import annotations

import pytest
from cap.v0.core import site_agent_pb2, skill_pb2
from cap.v0.domains.construction import skills_pb2 as construction
from cap_sdk.skill_invocation import (
    attach_invocation,
    make_skill_invocation,
    require_typed_params,
    set_skill_execution_invocation,
    set_work_order_invocation,
    typed_params_type_url,
    unpack_typed_params,
)


def test_make_skill_invocation_packs_domain_params_without_core_coupling() -> None:
    params = construction.ExcavateBatchParams(
        target_zone_id="dig-A",
        target_volume_m3=9.0,
        max_cycles=3,
    )

    invocation = make_skill_invocation(
        skill_id="construction.excavate_batch",
        skill_name="excavate",
        typed_params=params,
        metadata={"planner": "site"},
    )

    assert invocation.skill_id == "construction.excavate_batch"
    assert invocation.skill_name == "excavate"
    assert invocation.metadata["planner"] == "site"
    assert typed_params_type_url(invocation).endswith(
        "cap.v0.domains.construction.ExcavateBatchParams")
    out = require_typed_params(invocation, construction.ExcavateBatchParams)
    assert out.target_zone_id == "dig-A"
    assert out.target_volume_m3 == 9.0
    assert out.max_cycles == 3


def test_unpack_typed_params_returns_none_for_mismatch() -> None:
    invocation = make_skill_invocation(
        skill_id="construction.dump",
        typed_params=construction.DumpParams(dump_zone_id="dump-A", volume_m3=3.0),
    )

    assert unpack_typed_params(invocation, construction.HaulRouteParams) is None
    with pytest.raises(TypeError, match="cannot be unpacked"):
        require_typed_params(invocation, construction.HaulRouteParams)


def test_set_work_order_invocation_preserves_legacy_parameters() -> None:
    wo = site_agent_pb2.WorkOrder(
        task_id="t1",
        target_machine_id="mst110cr",
        skill="construction.dump",
        parameters={"volume_m3": "legacy"},
    )

    set_work_order_invocation(
        wo,
        typed_params=construction.DumpParams(dump_zone_id="dump-A", volume_m3=3.0),
        metadata={"legacy": "kept"},
    )
    wo2 = site_agent_pb2.WorkOrder.FromString(wo.SerializeToString())

    assert wo2.parameters["volume_m3"] == "legacy"
    assert wo2.invocation.skill_id == "construction.dump"
    assert wo2.invocation.skill_name == "construction.dump"
    assert wo2.invocation.metadata["legacy"] == "kept"
    out = require_typed_params(wo2.invocation, construction.DumpParams)
    assert out.dump_zone_id == "dump-A"
    assert out.volume_m3 == 3.0


def test_set_skill_execution_invocation_preserves_legacy_parameters() -> None:
    execution = skill_pb2.SkillExecution(
        execution_id="exec-1",
        skill_id="construction.haul_route",
        machine_id="mst110cr",
        task_id="t1",
        parameters={"total_volume_m3": "legacy"},
    )

    set_skill_execution_invocation(
        execution,
        typed_params=construction.HaulRouteParams(
            source_zone_id="dig-A",
            dump_zone_id="dump-A",
            total_volume_m3=6.0,
        ),
    )
    execution2 = skill_pb2.SkillExecution.FromString(execution.SerializeToString())

    assert execution2.parameters["total_volume_m3"] == "legacy"
    out = require_typed_params(execution2.invocation, construction.HaulRouteParams)
    assert out.source_zone_id == "dig-A"
    assert out.dump_zone_id == "dump-A"
    assert out.total_volume_m3 == 6.0


def test_attach_invocation_rejects_messages_without_invocation_field() -> None:
    invocation = make_skill_invocation(
        skill_id="construction.dump",
        typed_params=construction.DumpParams(dump_zone_id="dump-A", volume_m3=3.0),
    )

    with pytest.raises(TypeError, match="invocation field"):
        attach_invocation(construction.DumpParams(), invocation)

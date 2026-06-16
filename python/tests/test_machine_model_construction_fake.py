# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for cap_sdk.machine_model and cap_sdk.machine_model_construction_fake."""

import pytest

from cap_sdk.machine_model import (
    MachineModelInterface,
    SituationAssessment,
    AdjustmentProposal,
    create_machine_model,
)
from cap_sdk.machine_model_construction_fake import FakeMachineModel


class TestCreateMachineModel:
    def test_default_returns_fake(self):
        model = create_machine_model()
        assert isinstance(model, FakeMachineModel)

    def test_explicit_fake(self, monkeypatch):
        monkeypatch.setenv("CAP_MACHINE_MODEL_BACKEND", "fake")
        model = create_machine_model()
        assert isinstance(model, FakeMachineModel)

    def test_non_fake_raises(self, monkeypatch):
        monkeypatch.setenv("CAP_MACHINE_MODEL_BACKEND", "claude")
        with pytest.raises(ValueError, match="not available"):
            create_machine_model()

    def test_unknown_backend_returns_fake(self, monkeypatch):
        monkeypatch.setenv("CAP_MACHINE_MODEL_BACKEND", "nonexistent")
        with pytest.raises(ValueError, match="not available"):
            create_machine_model()


class TestFakeMachineModel:
    @pytest.fixture()
    def model(self):
        return FakeMachineModel()

    @pytest.mark.asyncio()
    async def test_assess_situation(self, model):
        result = await model.assess_situation(
            machine_state={"fuel_percent": 80, "mode": "idle"},
            task_context={"task_id": "t-1", "skill": "excavate"},
        )
        assert isinstance(result, SituationAssessment)
        assert result.summary
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.asyncio()
    async def test_assess_low_fuel_warning(self, model):
        result = await model.assess_situation(
            machine_state={"fuel_percent": 15, "mode": "idle"},
            task_context={},
        )
        assert "燃料" in result.summary  # Should mention fuel in warning

    @pytest.mark.asyncio()
    async def test_propose_adjustment(self, model):
        result = await model.propose_adjustment(
            machine_state={"fuel_percent": 50},
            task_context={"skill": "excavate"},
            issue="Hard soil detected",
        )
        assert isinstance(result, AdjustmentProposal)
        assert result.proposal_summary

    @pytest.mark.asyncio()
    async def test_generate_state_description(self, model):
        desc = await model.generate_state_description(
            machine_state={"fuel_percent": 90, "mode": "idle", "position": {"x": 10, "y": 20}},
        )
        assert isinstance(desc, str)
        assert len(desc) > 0

    @pytest.mark.asyncio()
    async def test_generate_entity_descriptor(self, model):
        info = {
            "machine_id": "exc-01",
            "machine_type": "MACHINE_TYPE_EXCAVATOR",
            "capabilities": [
                {"skill": "construction.excavate_batch", "limits": [{"key": "bucket_capacity_m3", "value": "0.8"}]},
            ],
        }
        result = await model.generate_entity_descriptor(info)
        assert isinstance(result, dict)

    @pytest.mark.asyncio()
    async def test_update_manager(self, model):
        result = await model.update_manager(
            machine_state={"mode": "running"},
            task_context={"skill": "excavate"},
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio()
    async def test_validate_state(self, model):
        result = await model.validate_state(
            entity_descriptor={"entity_id": "exc-01"},
            machine_state={"fuel_percent": 80},
        )
        assert isinstance(result, dict)
        assert "valid" in result

    @pytest.mark.asyncio()
    async def test_simulate_interaction(self, model):
        result = await model.simulate_interaction(
            self_entity={"entity_id": "exc-01"},
            target_entity={"entity_id": "zone-A"},
            task_context={"skill": "excavate"},
        )
        assert isinstance(result, dict)

    def test_model_id(self, model):
        assert "fake" in model.model_id

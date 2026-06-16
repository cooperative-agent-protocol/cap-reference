# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for cap_sdk.entity_generator."""

import json

import pytest

from cap_sdk.entity_generator import (
    build_entity_user_prompt,
    dict_to_entity_descriptor,
    generate_fake_entity,
    parse_entity_json,
)


class TestParseEntityJson:
    def test_plain_json(self):
        data = parse_entity_json('{"entity_id": "exc-01"}')
        assert data["entity_id"] == "exc-01"

    def test_markdown_code_block(self):
        text = '```json\n{"entity_id": "exc-01"}\n```'
        data = parse_entity_json(text)
        assert data["entity_id"] == "exc-01"

    def test_markdown_without_lang(self):
        text = '```\n{"entity_id": "exc-01"}\n```'
        data = parse_entity_json(text)
        assert data["entity_id"] == "exc-01"

    def test_surrounding_whitespace(self):
        data = parse_entity_json('  \n {"entity_id": "test"} \n ')
        assert data["entity_id"] == "test"

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            parse_entity_json("not json at all")

    def test_nested_json(self):
        text = json.dumps({
            "entity_id": "exc-01",
            "sub_objects": [{"sub_obj_id": "boom"}],
            "manager": {"available_skills": ["dig"]},
        })
        data = parse_entity_json(text)
        assert len(data["sub_objects"]) == 1
        assert data["manager"]["available_skills"] == ["dig"]


class TestDictToEntityDescriptor:
    def test_minimal_dict(self):
        data = {"entity_id": "exc-01", "entity_type": "machine", "canonical_name": "Excavator"}
        desc = dict_to_entity_descriptor(data)
        assert desc.entity_id == "exc-01"
        assert desc.entity_type == "machine"
        assert desc.canonical_name == "Excavator"

    def test_with_properties(self):
        data = {
            "entity_id": "exc-01",
            "properties": [
                {"key": "weight_kg", "value": "20000", "unit": "kg", "dtype": "float"},
            ],
        }
        desc = dict_to_entity_descriptor(data)
        assert len(desc.properties) == 1
        assert desc.properties[0].key == "weight_kg"
        assert desc.properties[0].value == "20000"

    def test_with_sub_objects(self):
        data = {
            "entity_id": "exc-01",
            "sub_objects": [
                {
                    "sub_obj_id": "boom",
                    "sub_obj_type": "work_equipment",
                    "description": "Main boom",
                    "properties": [
                        {"key": "length_m", "value": "5.7", "unit": "m", "dtype": "float"},
                    ],
                },
            ],
        }
        desc = dict_to_entity_descriptor(data)
        assert len(desc.sub_objects) == 1
        assert desc.sub_objects[0].sub_obj_id == "boom"
        assert len(desc.sub_objects[0].properties) == 1

    def test_with_manager(self):
        data = {
            "entity_id": "exc-01",
            "manager": {
                "available_skills": ["excavate", "load"],
                "interaction_rules": ["Keep 3m distance"],
                "relations": [
                    {"relation_type": "cooperates_with", "target_entity_id": "truck-01", "description": "Loading partner"},
                ],
            },
        }
        desc = dict_to_entity_descriptor(data)
        assert desc.manager.available_skills == ["excavate", "load"]
        assert len(desc.manager.relations) == 1

    def test_empty_dict_returns_descriptor(self):
        desc = dict_to_entity_descriptor({})
        assert desc.entity_id == ""
        assert desc.entity_type == "machine"

    def test_owner_agent_id(self):
        desc = dict_to_entity_descriptor({"entity_id": "exc-01"}, owner_agent_id="agent-01")
        assert desc.owner_agent_id == "agent-01"

    def test_updated_at_is_set(self):
        desc = dict_to_entity_descriptor({"entity_id": "test"})
        assert desc.updated_at.seconds > 0


class TestGenerateFakeEntity:
    def test_excavator(self):
        info = {
            "machine_id": "exc-01",
            "machine_type": "MACHINE_TYPE_EXCAVATOR",
            "capabilities": [
                {"skill": "construction.excavate_batch", "limits": [{"key": "bucket_capacity_m3", "value": "0.8"}]},
            ],
        }
        result = generate_fake_entity(info)
        assert result["entity_id"] == "exc-01"
        assert "バックホウ" in result["canonical_name"]
        assert len(result["sub_objects"]) >= 2
        assert any("excavate" in s for s in result["manager"]["available_skills"])

    def test_dump_truck(self):
        info = {
            "machine_id": "truck-01",
            "machine_type": "MACHINE_TYPE_DUMP_TRUCK",
            "capabilities": [{"skill": "construction.haul_route", "limits": []}],
        }
        result = generate_fake_entity(info)
        assert result["entity_id"] == "truck-01"
        assert "ダンプトラック" in result["canonical_name"]
        assert len(result["sub_objects"]) >= 2

    def test_unknown_machine_type(self):
        info = {
            "machine_id": "robot-01",
            "machine_type": "MACHINE_TYPE_UNKNOWN",
            "capabilities": [],
        }
        result = generate_fake_entity(info)
        assert result["entity_id"] == "robot-01"


class TestBuildEntityUserPrompt:
    def test_basic_prompt(self):
        info = {
            "machine_id": "exc-01",
            "machine_type": "MACHINE_TYPE_EXCAVATOR",
            "capabilities": [{"skill": "dig"}],
        }
        prompt = build_entity_user_prompt(info)
        assert "exc-01" in prompt
        assert "EXCAVATOR" in prompt
        assert "dig" in prompt

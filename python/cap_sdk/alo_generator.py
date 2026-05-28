# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""ALO Generator — converts machine info into ALODescriptor using LLM.

Implements the ALO methodology from Ochiai et al. (2304.04498):
  Step 1: Define mainObj with subObjList
  Step 2: Add skills and knowledge to subObjList
  Step 3: Set specific states for subObjList
  Step 4: Validate initial state meets conditions

The generator provides:
  - System prompt for ALO creation (adapted for construction machinery)
  - Parser to convert LLM JSON output into ALODescriptor proto
  - Fallback template-based generation for FakeMachineModel
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from google.protobuf.timestamp_pb2 import Timestamp

from cap.v0.core import alo_pb2

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# ALO Generation System Prompt (adapted from paper's Prompt 1, Steps 1-4)
# --------------------------------------------------------------------------- #

ALO_SYSTEM_PROMPT = """\
あなたは建設機械の Abstract Language Object (ALO) を生成する AI です。
ALO は人間が読める言語的記述と、機械が参照可能な型付きプロパティの両方を持つ
オブジェクト表現です（Ochiai et al., 2304.04498）。

以下の手順で ALO を生成してください:

Step 1: mainObj を定義し、subObjList を列挙する
  - mainObj: 機械の識別情報（ID、型、名前）
  - subObjList: 機械の構成要素（外観、性能、センサ、アクチュエータ、安全装置 等）

Step 2: skills と knowledge を追加する
  - skills: この機械が実行できるスキル（capabilities から導出）
  - knowledge: この機械が持つドメイン知識（作業手順、安全規則 等）

Step 3: 各 subObj に具体的な状態を設定する
  - 数値プロパティには単位とデータ型を付与
  - 初期状態を記述

Step 4: 初期状態が妥当か検証する
  - プロパティ間の矛盾がないことを確認

入力される機械情報に基づき、以下の JSON 形式で ALO を出力してください。
JSON のみを出力し、説明は不要です。

{
  "alo_id": "機械ID",
  "alo_type": "machine",
  "canonical_name": "人間が読める日本語名",
  "properties": [
    {"key": "プロパティ名", "value": "値", "unit": "単位", "dtype": "float|int|string|enum|bool"}
  ],
  "sub_objects": [
    {
      "sub_obj_id": "コンポーネントID",
      "sub_obj_type": "コンポーネント種別",
      "description": "自然言語による説明",
      "properties": [
        {"key": "名前", "value": "値", "unit": "単位", "dtype": "型"}
      ]
    }
  ],
  "state_description": "現在の状態を自然言語で記述",
  "manager": {
    "available_skills": ["スキル1", "スキル2"],
    "interaction_rules": ["ルール1（自然言語）", "ルール2"],
    "relations": []
  }
}
"""

ALO_USER_PROMPT_TEMPLATE = """\
以下の建設機械の ALO を生成してください。

機械ID: {machine_id}
機械タイプ: {machine_type}
HALプロファイル: {hal_profile}
ソフトウェアバージョン: {software_version}
スキル一覧:
{capabilities_text}
メタデータ:
{metadata_text}
"""


def build_alo_user_prompt(machine_info: dict[str, Any]) -> str:
    """Build the user prompt for ALO generation from machine info."""
    caps_lines = []
    for cap in machine_info.get("capabilities", []):
        limits_str = ", ".join(
            f"{lim['key']}={lim['value']}" for lim in cap.get("limits", [])
        )
        caps_lines.append(f"  - {cap['skill']} ({limits_str})" if limits_str else f"  - {cap['skill']}")

    meta_lines = []
    for kv in machine_info.get("metadata", []):
        meta_lines.append(f"  - {kv['key']}: {kv['value']}")

    return ALO_USER_PROMPT_TEMPLATE.format(
        machine_id=machine_info.get("machine_id", "unknown"),
        machine_type=machine_info.get("machine_type", "unknown"),
        hal_profile=machine_info.get("hal_profile", "unknown"),
        software_version=machine_info.get("software_version", "0.0.0"),
        capabilities_text="\n".join(caps_lines) or "  (なし)",
        metadata_text="\n".join(meta_lines) or "  (なし)",
    )


# --------------------------------------------------------------------------- #
# Phase 2: Dynamic Manager Update Prompt (Paper Steps 5-8)
# --------------------------------------------------------------------------- #

MANAGER_UPDATE_SYSTEM_PROMPT = """\
あなたは建設機械の ALO (Abstract Language Object) のマネージャーオブジェクトを
動的に更新する AI です（Ochiai et al., 2304.04498 Step 5-8）。

機械の現在状態とタスクコンテキストに基づき、以下を更新してください:
- interaction_rules: 現在の状況に適した行動ルール
- state_transition_rules: 状態遷移条件（例: "燃料 < 20% → 給油要請"）
- current_knowledge: 現在の観測から得たドメイン知識

JSON のみを出力してください:
{
  "interaction_rules": ["ルール1", "ルール2"],
  "state_transition_rules": ["遷移ルール1", "遷移ルール2"],
  "current_knowledge": ["知識1", "知識2"]
}
"""

VALIDATE_STATE_SYSTEM_PROMPT = """\
あなたは建設機械の ALO 状態を検証する AI です（Ochiai et al., 2304.04498 Step 5）。

ALO のプロパティと機械の実際の状態を比較し、矛盾や異常を検出してください。

JSON のみを出力してください:
{
  "valid": true/false,
  "anomalies": ["異常1", "異常2"],
  "suggestions": ["提案1", "提案2"]
}
"""

# --------------------------------------------------------------------------- #
# Phase 3: ALO Interaction Prompt (Paper Steps 9-10)
# --------------------------------------------------------------------------- #

INTERACTION_SYSTEM_PROMPT = """\
あなたは建設機械の ALO 間インタラクションをシミュレートする AI です
（Ochiai et al., 2304.04498 Step 9-10）。

2 つの ALO（機械と対象）のプロパティ・スキル・状態を見て、
インタラクションの結果を予測し、実行手順（stepObjList）を生成してください。

JSON のみを出力してください:
{
  "interaction_type": "掘削/積込/搬出/排土 等",
  "predicted_outcome": "予測される結果の自然言語記述",
  "expected_state_changes": [
    {"alo_id": "対象ALO ID", "property": "変化するプロパティ", "from": "現在値", "to": "予測値"}
  ],
  "step_list": ["手順1", "手順2", "手順3"],
  "confidence": 0.0-1.0
}
"""


def build_manager_update_prompt(machine_state: dict, task_context: dict) -> str:
    """Build prompt for dynamic manager update."""
    return (
        f"機械状態: {json.dumps(machine_state, ensure_ascii=False)}\n"
        f"タスク情報: {json.dumps(task_context, ensure_ascii=False)}\n\n"
        "現在の状況に適した managerObj の更新内容を生成してください。"
    )


def build_validate_state_prompt(alo_descriptor: dict, machine_state: dict) -> str:
    """Build prompt for state validation."""
    return (
        f"ALO記述: {json.dumps(alo_descriptor, ensure_ascii=False)}\n"
        f"実際の機械状態: {json.dumps(machine_state, ensure_ascii=False)}\n\n"
        "ALO の状態と実際の状態に矛盾や異常がないか検証してください。"
    )


def build_interaction_prompt(self_alo: dict, target_alo: dict, task_context: dict) -> str:
    """Build prompt for ALO interaction simulation."""
    return (
        f"機械 ALO: {json.dumps(self_alo, ensure_ascii=False)}\n"
        f"対象 ALO: {json.dumps(target_alo, ensure_ascii=False)}\n"
        f"タスク情報: {json.dumps(task_context, ensure_ascii=False)}\n\n"
        "この機械が対象に対して実行するインタラクションを予測し、実行手順を生成してください。"
    )


# --------------------------------------------------------------------------- #
# Dict → Proto converter
# --------------------------------------------------------------------------- #

def _now_ts() -> Timestamp:
    ts = Timestamp()
    ts.FromDatetime(datetime.now(timezone.utc))
    return ts


def dict_to_alo_descriptor(data: dict[str, Any], owner_agent_id: str = "") -> alo_pb2.ALODescriptor:
    """Convert a dict (from LLM JSON output) into an ALODescriptor proto message."""
    properties = [
        alo_pb2.ALOProperty(
            key=p.get("key", ""),
            value=str(p.get("value", "")),
            unit=p.get("unit", ""),
            dtype=p.get("dtype", "string"),
        )
        for p in data.get("properties", [])
    ]

    sub_objects = [
        alo_pb2.ALOSubObject(
            sub_obj_id=so.get("sub_obj_id", ""),
            sub_obj_type=so.get("sub_obj_type", ""),
            description=so.get("description", ""),
            properties=[
                alo_pb2.ALOProperty(
                    key=sp.get("key", ""),
                    value=str(sp.get("value", "")),
                    unit=sp.get("unit", ""),
                    dtype=sp.get("dtype", "string"),
                )
                for sp in so.get("properties", [])
            ],
        )
        for so in data.get("sub_objects", [])
    ]

    manager_data = data.get("manager", {})
    manager = alo_pb2.ALOManager(
        available_skills=manager_data.get("available_skills", []),
        interaction_rules=manager_data.get("interaction_rules", []),
        relations=[
            alo_pb2.ALORelation(
                relation_type=r.get("relation_type", ""),
                target_alo_id=r.get("target_alo_id", ""),
                description=r.get("description", ""),
            )
            for r in manager_data.get("relations", [])
        ],
    )

    return alo_pb2.ALODescriptor(
        alo_id=data.get("alo_id", ""),
        alo_type=data.get("alo_type", "machine"),
        canonical_name=data.get("canonical_name", ""),
        properties=properties,
        sub_objects=sub_objects,
        state_description=data.get("state_description", ""),
        manager=manager,
        updated_at=_now_ts(),
        owner_agent_id=owner_agent_id or data.get("alo_id", ""),
    )


def parse_alo_json(text: str) -> dict[str, Any]:
    """Parse LLM response text into ALO dict, handling markdown code blocks."""
    import re
    json_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    text = text.strip()
    return json.loads(text)


# --------------------------------------------------------------------------- #
# Template-based ALO generation (for FakeMachineModel)
# --------------------------------------------------------------------------- #

# Machine type name mapping
_MACHINE_TYPE_NAMES: dict[str, tuple[str, str]] = {
    "MACHINE_TYPE_EXCAVATOR": ("バックホウ", "excavator"),
    "MACHINE_TYPE_DUMP_TRUCK": ("ダンプトラック", "dump_truck"),
    "MACHINE_TYPE_DOZER": ("ブルドーザー", "dozer"),
    "MACHINE_TYPE_GRADER": ("グレーダー", "grader"),
    "MACHINE_TYPE_LOADER": ("ローダー", "loader"),
    "MACHINE_TYPE_ROLLER": ("ローラー", "roller"),
    "MACHINE_TYPE_CRANE": ("クレーン", "crane"),
}

# Excavator-specific sub-objects template
_EXCAVATOR_SUB_OBJECTS = [
    {
        "sub_obj_id": "boom_arm_bucket",
        "sub_obj_type": "work_equipment",
        "description": "ブーム・アーム・バケットの作業装置。掘削・積込の主要機構。",
        "properties": [
            {"key": "boom_length_m", "value": "5.7", "unit": "m", "dtype": "float"},
            {"key": "arm_length_m", "value": "2.9", "unit": "m", "dtype": "float"},
            {"key": "bucket_type", "value": "standard", "unit": "", "dtype": "enum"},
        ],
    },
    {
        "sub_obj_id": "undercarriage",
        "sub_obj_type": "mobility",
        "description": "クローラ式走行装置。不整地走行と旋回を担当。",
        "properties": [
            {"key": "track_type", "value": "crawler", "unit": "", "dtype": "enum"},
            {"key": "max_travel_speed_kmh", "value": "5.5", "unit": "km/h", "dtype": "float"},
        ],
    },
    {
        "sub_obj_id": "cab",
        "sub_obj_type": "operator_interface",
        "description": "オペレータキャブ。手動操作・テレオペ・自律切替の操作インターフェース。",
        "properties": [
            {"key": "has_ac", "value": "true", "unit": "", "dtype": "bool"},
            {"key": "rops_certified", "value": "true", "unit": "", "dtype": "bool"},
        ],
    },
]

_DUMP_SUB_OBJECTS = [
    {
        "sub_obj_id": "vessel",
        "sub_obj_type": "cargo",
        "description": "ダンプベッセル（荷台）。土砂の積載・排土を担当。",
        "properties": [
            {"key": "capacity_m3", "value": "6.0", "unit": "m³", "dtype": "float"},
            {"key": "dump_angle_deg", "value": "70", "unit": "°", "dtype": "float"},
        ],
    },
    {
        "sub_obj_id": "drivetrain",
        "sub_obj_type": "mobility",
        "description": "駆動系。搬出路での走行を担当。",
        "properties": [
            {"key": "drive_type", "value": "6x4", "unit": "", "dtype": "enum"},
            {"key": "max_speed_kmh", "value": "30", "unit": "km/h", "dtype": "float"},
        ],
    },
]


def generate_fake_alo(machine_info: dict[str, Any]) -> dict[str, Any]:
    """Generate ALO using templates (no LLM). For FakeMachineModel."""
    machine_id = machine_info.get("machine_id", "unknown")
    machine_type = machine_info.get("machine_type", "MACHINE_TYPE_UNSPECIFIED")
    hal_profile = machine_info.get("hal_profile", "unknown")

    ja_name, _ = _MACHINE_TYPE_NAMES.get(machine_type, ("不明な機械", "unknown"))
    # Append a number suffix if present in machine_id
    suffix = machine_id.split("-")[-1] if "-" in machine_id else ""
    canonical_name = f"{ja_name}{suffix}号機" if suffix and suffix.isdigit() else ja_name

    skills = [cap["skill"] for cap in machine_info.get("capabilities", [])]

    # Build properties from capabilities limits
    properties = []
    for cap in machine_info.get("capabilities", []):
        for lim in cap.get("limits", []):
            properties.append({
                "key": lim["key"],
                "value": lim["value"],
                "unit": lim.get("unit", ""),
                "dtype": "float",
            })

    for meta in machine_info.get("metadata", []):
        properties.append({
            "key": meta["key"],
            "value": meta["value"],
            "unit": "",
            "dtype": "string",
        })

    # Add standard properties
    properties.extend([
        {"key": "hal_profile", "value": hal_profile, "unit": "", "dtype": "string"},
        {"key": "machine_type", "value": machine_type, "unit": "", "dtype": "enum"},
    ])

    # Select sub-objects based on type
    if "EXCAVATOR" in machine_type:
        sub_objects = _EXCAVATOR_SUB_OBJECTS
        interaction_rules = [
            "掘削は指定ゾーン内のみで実施",
            "地中障害物検知時はテレオペに切替",
            "積込時はダンプトラックの停止を確認してから旋回",
        ]
    elif "DUMP" in machine_type:
        sub_objects = _DUMP_SUB_OBJECTS
        interaction_rules = [
            "積込地点では掘削機の積込完了を待機",
            "搬出路上の障害物検知時は減速または停止",
            "排土はダンプゾーン内のみで実施",
        ]
    else:
        sub_objects = []
        interaction_rules = []

    return {
        "alo_id": machine_id,
        "alo_type": "machine",
        "canonical_name": canonical_name,
        "properties": properties,
        "sub_objects": sub_objects,
        "state_description": f"{canonical_name}: 初期状態、待機中",
        "manager": {
            "available_skills": skills,
            "interaction_rules": interaction_rules,
            "relations": [],
        },
    }

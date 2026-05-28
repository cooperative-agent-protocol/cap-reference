# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""FakeMachineModel — rule-based implementation for testing.

No external dependencies. Uses simple heuristics and Japanese templates
to generate situation assessments, adjustment proposals, and state descriptions.
"""

from __future__ import annotations

from typing import Any

from .machine_model import MachineModelInterface, SituationAssessment, AdjustmentProposal
from .alo_generator import generate_fake_alo


class FakeMachineModel(MachineModelInterface):
    """Rule-based model for testing and development."""

    def __init__(self, model_id: str = "fake-rule-based") -> None:
        self.model_id = model_id

    async def assess_situation(
        self,
        machine_state: dict[str, Any],
        task_context: dict[str, Any],
    ) -> SituationAssessment:
        facts: dict[str, str] = {}
        warnings: list[str] = []

        # Check fuel
        fuel = machine_state.get("fuel_percent", 100.0)
        facts["fuel_percent"] = f"{fuel:.1f}"
        if fuel < 20:
            warnings.append(f"燃料残量低下({fuel:.0f}%)")

        # Check task progress
        progress = task_context.get("completion_ratio", 0.0)
        facts["completion_ratio"] = f"{progress:.2f}"

        # Check mode
        mode = machine_state.get("mode", "unknown")
        facts["mode"] = mode

        if warnings:
            summary = "注意事項あり: " + "; ".join(warnings)
            action = "Site Agent に報告し、指示を待つ"
            confidence = 0.8
        elif progress > 0.8:
            summary = f"タスク順調に進行中（進捗 {progress*100:.0f}%）、完了間近"
            action = "現在の計画を継続"
            confidence = 0.9
        else:
            summary = f"通常稼働中（進捗 {progress*100:.0f}%）"
            action = "現在の計画を継続"
            confidence = 0.95

        return SituationAssessment(
            summary=summary,
            recommended_action=action,
            confidence=confidence,
            observed_facts=facts,
        )

    async def propose_adjustment(
        self,
        machine_state: dict[str, Any],
        task_context: dict[str, Any],
        issue: str,
    ) -> AdjustmentProposal:
        if "硬" in issue or "hard" in issue.lower():
            return AdjustmentProposal(
                proposal_summary="掘削深度を0.3m浅くすることを提案。土質が硬いため、効率改善が見込まれる。",
                proposed_parameters={"depth_reduction_m": "0.3"},
                expected_outcome="サイクルタイム短縮、バケット負荷低減",
                confidence=0.7,
            )

        if "障害" in issue or "obstacle" in issue.lower():
            return AdjustmentProposal(
                proposal_summary="障害物を回避するため、作業範囲の調整を提案。",
                proposed_parameters={"avoid_obstacle": "true"},
                expected_outcome="安全な作業継続",
                confidence=0.6,
            )

        return AdjustmentProposal(
            proposal_summary=f"問題「{issue}」に対して、作業パラメータの見直しを提案。",
            proposed_parameters={},
            expected_outcome="状況改善",
            confidence=0.5,
        )

    async def generate_alo_descriptor(
        self,
        machine_info: dict[str, Any],
    ) -> dict[str, Any]:
        return generate_fake_alo(machine_info)

    async def update_manager(
        self,
        machine_state: dict[str, Any],
        task_context: dict[str, Any],
    ) -> dict[str, Any]:
        rules = []
        knowledge = []

        fuel = machine_state.get("fuel_percent", 100.0)
        if fuel < 30:
            rules.append(f"燃料残量 {fuel:.0f}% — 長時間作業は避け、給油を優先")
            knowledge.append("低燃料状態を検知")

        task = task_context.get("skill", "")
        if task == "construction.excavate_batch":
            rules.append("掘削中: バケット満載で旋回速度を制限")
            rules.append("掘削深度が目標に達したらサイクル完了を報告")
            knowledge.append("掘削タスクの標準手順を適用中")
        elif task == "construction.haul_route":
            rules.append("搬出中: 積載時は最高速度を 20km/h に制限")
            rules.append("ダンプゾーン到着時は排土手順に遷移")
            knowledge.append("搬出タスクの標準手順を適用中")

        return {
            "interaction_rules": rules,
            "state_transition_rules": rules,
            "current_knowledge": knowledge,
        }

    async def validate_state(
        self,
        alo_descriptor: dict[str, Any],
        machine_state: dict[str, Any],
    ) -> dict[str, Any]:
        anomalies = []
        suggestions = []

        fuel = machine_state.get("fuel_percent", 100.0)
        if fuel < 10:
            anomalies.append(f"燃料残量危険 ({fuel:.0f}%)")
            suggestions.append("即座に safe_stop し給油を要請")

        mode = machine_state.get("mode", "")
        if mode == "safe_stop":
            anomalies.append("安全停止状態")
            suggestions.append("原因を確認し Site Agent に報告")

        return {
            "valid": len(anomalies) == 0,
            "anomalies": anomalies,
            "suggestions": suggestions,
        }

    async def simulate_interaction(
        self,
        self_alo: dict[str, Any],
        target_alo: dict[str, Any],
        task_context: dict[str, Any],
    ) -> dict[str, Any]:
        self_name = self_alo.get("canonical_name", "機械")
        target_name = target_alo.get("canonical_name", "対象")
        skill = task_context.get("skill", "作業")
        volume = task_context.get("target_volume_m3", 0)

        steps = [
            f"{self_name}が{target_name}に接近",
            f"{skill}を開始",
            f"作業パラメータに従い実行",
            f"完了後に ProgressEvent を送信",
        ]

        return {
            "interaction_type": skill,
            "predicted_outcome": f"{self_name}が{target_name}で{skill}を実行。目標: {volume}m³",
            "expected_state_changes": [
                {"alo_id": target_alo.get("alo_id", ""), "property": "volume_m3", "from": "current", "to": f"-{volume}"},
            ],
            "step_list": steps,
            "confidence": 0.8,
        }

    async def think(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Rule-based think: dynamically selects tools from the available set.

        Uses the `tools` argument to resolve machine-type-specific tool names.
        Excavator has: move_to_dig_point, dig, swing_to_load, load_truck, wait_for_truck
        Dump truck has: drive_to, wait_for_load, haul_to_dump, dump_payload, return_to_load
        """
        available = {t["name"] for t in (tools or [])}
        resolver = _ToolResolver(available)

        last_user = _extract_last_user_message(messages)
        instruction = _extract_instruction(messages)

        tool_calls: list[dict[str, Any]] = []
        text = ""

        # No instruction → idle
        if not instruction:
            return {"text": "指示待機中。現在の状態を監視。", "tool_calls": []}

        # New instruction received → first read state
        if "new_instruction" in last_user or "WorkOrder" in last_user:
            tool_calls.append({"tool_name": "read_state", "arguments": {}})
            return {"text": "新しい指示を受信。まず自機の状態を確認。", "tool_calls": tool_calls}

        has_state = "position" in last_user.lower() or "State:" in last_user
        has_tool_result = "Tool result" in last_user
        instruction_lower = instruction.lower()

        # Classify instruction
        is_move = any(kw in instruction for kw in ["直進", "前進", "移動", "進め"])
        is_move = is_move or any(kw in instruction_lower for kw in ["move", "forward", "go straight"])
        is_excavate = any(kw in instruction for kw in ["掘", "掘削", "積"])
        is_excavate = is_excavate or "excavat" in instruction_lower
        is_haul = any(kw in instruction for kw in ["運", "搬", "ダンプ"])
        is_haul = is_haul or "haul" in instruction_lower

        # After state read, decide action using available tools
        if has_state and has_tool_result:
            if is_move:
                if "read_environment" not in last_user:
                    tool_calls.append({"tool_name": "read_environment", "arguments": {}})
                    text = "移動指示。周辺環境を確認。"
                else:
                    # Prefer semantic tools (return_to_load) over drive_to
                    move_tool = resolver.find_return_tool() or resolver.find_move_tool()
                    if move_tool:
                        tool_calls.append({
                            "tool_name": move_tool,
                            "arguments": resolver.move_args(move_tool),
                        })
                        tool_calls.append({
                            "tool_name": "report_to_site",
                            "arguments": {"report_type": "milestone", "summary": "移動開始"},
                        })
                        text = "環境確認完了。移動を開始。"
            elif is_excavate:
                dig_tool = resolver.find_dig_tool()
                if dig_tool:
                    tool_calls.append({"tool_name": dig_tool, "arguments": {}})
                    tool_calls.append({
                        "tool_name": "report_to_site",
                        "arguments": {"report_type": "milestone", "summary": "掘削開始"},
                    })
                    text = "掘削を開始。"
            elif is_haul:
                haul_tool = resolver.find_haul_tool()
                if haul_tool:
                    tool_calls.append({"tool_name": haul_tool, "arguments": {}})
                    tool_calls.append({
                        "tool_name": "report_to_site",
                        "arguments": {"report_type": "milestone", "summary": "運搬開始"},
                    })
                    text = "運搬を開始。"
            else:
                text = f"指示を解釈中: {instruction}"

        # Completion signals
        if "到着" in last_user or "完了" in last_user or "SUCCEEDED" in last_user:
            tool_calls.append({
                "tool_name": "report_to_site",
                "arguments": {"report_type": "completion", "summary": "タスク完了"},
            })
            return {"text": "タスク完了を報告。", "tool_calls": tool_calls, "done": True}

        if not tool_calls and not text:
            text = "状態を監視中。進行中のアクションの完了を待機。"

        return {"text": text, "tool_calls": tool_calls}

    async def summarize(self, text: str) -> str:
        """Rule-based summarization: keep key lines, discard details."""
        lines = text.strip().split("\n")
        if len(lines) <= 15:
            return text

        # Keep lines with key information
        key_lines = []
        for line in lines:
            line_lower = line.lower()
            is_important = any(kw in line_lower for kw in [
                "instruction", "指示", "milestone", "error", "エラー",
                "completed", "完了", "failed", "失敗", "approval", "承認",
                "obstacle", "障害", "warning", "警告", "decision", "判断",
            ])
            if is_important:
                key_lines.append(line)

        if not key_lines:
            key_lines = lines[:3] + lines[-3:]

        return (
            f"[Summary of {len(lines)} lines, {len(key_lines)} key events retained]\n"
            + "\n".join(key_lines)
        )

    async def generate_state_description(  # noqa: C901 — kept flat for readability
        self,
        machine_state: dict[str, Any],
    ) -> str:
        machine_id = machine_state.get("machine_id", "不明")
        mode = machine_state.get("mode", "不明")
        fuel = machine_state.get("fuel_percent", 0.0)
        task = machine_state.get("active_task", "なし")

        pos_x = machine_state.get("position_x", 0.0)
        pos_y = machine_state.get("position_y", 0.0)

        return (
            f"{machine_id}: モード={mode}, 燃料={fuel:.0f}%, "
            f"位置=({pos_x:.1f}, {pos_y:.1f}), タスク={task}"
        )


# ---------------------------------------------------------------------------
# Helpers for think() — tool resolution and message parsing
# ---------------------------------------------------------------------------


def _extract_last_user_message(messages: list[dict[str, str]]) -> str:
    """Extract the last user message content."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    return ""


def _extract_instruction(messages: list[dict[str, str]]) -> str:
    """Extract active instruction from system prompt pinned state."""
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            for line in content.split("\n"):
                if "active_instruction" in line:
                    return line.split(":", 1)[-1].strip()
            break
    return ""


class _ToolResolver:
    """Resolves abstract actions to actual available tool names.

    Machine types have different tools:
      Excavator: move_to_dig_point, dig, swing_to_load, load_truck, wait_for_truck
      Dump truck: drive_to, wait_for_load, haul_to_dump, dump_payload, return_to_load
      Common: read_state, read_environment, report_to_site, request_approval
    """

    # Keywords to match tool names by category
    _MOVE_KEYWORDS = ("move_to", "drive_to", "dig_point")
    _DIG_KEYWORDS = ("dig", "excavate", "start_dig")
    _HAUL_KEYWORDS = ("haul", "dump_payload")
    _LOAD_KEYWORDS = ("load_truck", "wait_for_load")
    _RETURN_KEYWORDS = ("return",)

    def __init__(self, available: set[str]) -> None:
        self._available = available

    def _find(self, keywords: tuple[str, ...]) -> str | None:
        """Find first available tool matching any keyword."""
        for tool_name in self._available:
            if any(kw in tool_name for kw in keywords):
                return tool_name
        return None

    def find_move_tool(self) -> str | None:
        return self._find(self._MOVE_KEYWORDS)

    def find_dig_tool(self) -> str | None:
        return self._find(self._DIG_KEYWORDS)

    def find_haul_tool(self) -> str | None:
        return self._find(self._HAUL_KEYWORDS)

    def find_load_tool(self) -> str | None:
        return self._find(self._LOAD_KEYWORDS)

    def find_return_tool(self) -> str | None:
        return self._find(self._RETURN_KEYWORDS)

    def move_args(self, tool_name: str) -> dict[str, Any]:
        """Generate default arguments for a move tool."""
        if "dig_point" in tool_name:
            return {"target_row": 4, "target_col": 5}
        # drive_to requires explicit coordinates from the instruction.
        # Do not provide defaults — the tool will return an error
        # guiding the agent to use semantic tools instead.
        return {}

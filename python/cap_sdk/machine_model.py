# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Language Model interface for Machine Agent tactical layer.

Defines the abstract interface (MachineModelInterface) that all machine
model implementations must follow.

Layer [B] in the 3-layer architecture:
  [A] Site Agent — large LLM (strategic planning, scheduling)
  [B] Machine Agent — LLM/SLM (situation assessment, advisory only)
  [C] Safety Supervisor — deterministic control (no LLM)

IMPORTANT: The model is advisory only — it NEVER directly controls actuators.
All actuator control goes through Layer [C] (deterministic safety layer).

This package provides:
  - MachineModelInterface (ABC)
  - FakeMachineModel (rule-based reference implementation, no API key needed)

Production LLM backends (Claude, OpenAI, Gemini, Ollama) are outside
the scope of cap-reference and live in implementation repos.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SituationAssessment:
    """Result of model situation assessment."""

    summary: str  # Natural language situation description
    recommended_action: str
    confidence: float  # 0.0–1.0
    observed_facts: dict[str, str] = field(default_factory=dict)


@dataclass
class AdjustmentProposal:
    """Result of model adjustment proposal."""

    proposal_summary: str
    proposed_parameters: dict[str, str] = field(default_factory=dict)
    expected_outcome: str = ""
    confidence: float = 0.5


class MachineModelInterface(ABC):
    """Abstract interface for language models on machine agents.

    Implementations:
      - FakeMachineModel: rule-based, for testing (no external dependencies)
      - ClaudeMachineModel: Anthropic Claude API
      - GeminiMachineModel: Google Gemini API
      - OpenAIMachineModel: OpenAI API
      - OllamaMachineModel: local Ollama (Phi-3, Gemma, etc.)
    """

    model_id: str = "unknown"

    @abstractmethod
    async def assess_situation(
        self,
        machine_state: dict[str, Any],
        task_context: dict[str, Any],
    ) -> SituationAssessment:
        """Assess current situation and recommend action."""
        ...

    @abstractmethod
    async def propose_adjustment(
        self,
        machine_state: dict[str, Any],
        task_context: dict[str, Any],
        issue: str,
    ) -> AdjustmentProposal:
        """Propose a parameter adjustment for the current task."""
        ...

    @abstractmethod
    async def generate_state_description(
        self,
        machine_state: dict[str, Any],
    ) -> str:
        """Generate natural language description of machine state for heartbeat.

        This is used to populate Heartbeat.alo_state_summary.
        """
        ...

    @abstractmethod
    async def generate_alo_descriptor(
        self,
        machine_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate an ALODescriptor for a machine using ALO methodology.

        Implements ALO paper (Ochiai et al., 2304.04498) Steps 1-4:
          Step 1: Define mainObj with subObjList
          Step 2: Add skills and knowledge to subObjList
          Step 3: Set specific states for subObjList
          Step 4: Validate initial state

        Args:
            machine_info: Dict with machine_id, machine_type, hal_profile,
                          capabilities (list of {skill, limits}), sensors, etc.

        Returns:
            Dict matching ALODescriptor proto structure:
            {
                "alo_id": str,
                "alo_type": "machine",
                "canonical_name": str,
                "properties": [{"key": str, "value": str, "unit": str, "dtype": str}],
                "sub_objects": [{"sub_obj_id": str, "sub_obj_type": str, "description": str, "properties": [...]}],
                "state_description": str,
                "manager": {
                    "available_skills": [str],
                    "interaction_rules": [str],
                    "relations": [{"relation_type": str, "target_alo_id": str, "description": str}]
                }
            }
        """
        ...


    # --- Phase 2: Dynamic Manager (Paper Steps 5-8) ---

    @abstractmethod
    async def update_manager(
        self,
        machine_state: dict[str, Any],
        task_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Dynamically update ALOManager based on current state and task.

        Implements ALO paper Steps 5-8:
          Step 5: Validate current state meets conditions
          Step 6: Update subObjList for state detection
          Step 7: Update managerObj state using skills and knowledge
          Step 8: Generate stepObjList

        Returns:
            Dict with updated manager fields:
            {
                "interaction_rules": [str],     # Updated rules for current context
                "state_transition_rules": [str], # LLM-generated transition rules
                "current_knowledge": [str],      # Domain knowledge observations
            }
        """
        ...

    @abstractmethod
    async def validate_state(
        self,
        alo_descriptor: dict[str, Any],
        machine_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate that ALO state is consistent and detect anomalies.

        Implements ALO paper Step 5: Validate initial state meets conditions.

        Returns:
            Dict with validation result:
            {
                "valid": bool,
                "anomalies": [str],      # Detected issues
                "suggestions": [str],    # Recommended actions
            }
        """
        ...

    # --- Agent Loop: Multi-turn thinking (Claude Code-style) ---

    async def think(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Multi-turn think cycle for the Agent Loop.

        Unlike single-shot methods (assess_situation, etc.), this maintains
        a full conversation with the LLM, enabling tool-use loops.

        Args:
            messages: Conversation history (system + user + assistant messages).
            tools: Optional list of tool schemas (JSON Schema format).

        Returns:
            Dict with:
            {
                "text": str,             # LLM's text response
                "tool_calls": [          # Zero or more tool calls
                    {"tool_name": str, "arguments": dict},
                ],
            }

        Default implementation: returns a no-op response. Subclasses with
        LLM access override this for real multi-turn reasoning.
        """
        # Default: extract last user message and return simple assessment
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = msg.get("content", "")
                break

        return {
            "text": f"Acknowledged. Current observation processed.",
            "tool_calls": [],
        }

    async def summarize(self, text: str) -> str:
        """Summarize text for context compacting.

        Used by AgentLoop when conversation history exceeds the token threshold.

        Args:
            text: The text to summarize (old conversation messages).

        Returns:
            A concise summary preserving key facts, decisions, and state.
        """
        # Default: simple truncation-based summary
        lines = text.strip().split("\n")
        if len(lines) <= 10:
            return text
        # Keep first 3 and last 5 lines with a note
        return "\n".join([
            *lines[:3],
            f"\n[... {len(lines) - 8} lines summarized ...]\n",
            *lines[-5:],
        ])

    # --- Phase 3: ALO Interaction (Paper Steps 9-10) ---

    @abstractmethod
    async def simulate_interaction(
        self,
        self_alo: dict[str, Any],
        target_alo: dict[str, Any],
        task_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Simulate interaction between two ALOs using LLM.

        Implements ALO paper Steps 9-10:
          Step 9: "ALOs(A) meets ALOs(B)" — predict interaction outcome
          Step 10: Generate execution steps (stepObjList)

        Args:
            self_alo: This machine's ALO descriptor dict
            target_alo: Target ALO descriptor dict (zone, material, other machine)
            task_context: Current task parameters

        Returns:
            Dict describing the predicted interaction:
            {
                "interaction_type": str,      # e.g. "excavate", "load", "haul"
                "predicted_outcome": str,     # Natural language prediction
                "expected_state_changes": [{"alo_id": str, "property": str, "from": str, "to": str}],
                "step_list": [str],           # Ordered execution steps (stepObjList)
                "confidence": float,
            }
        """
        ...


def create_machine_model() -> MachineModelInterface:
    """Create machine model based on CAP_MACHINE_MODEL_BACKEND env var.

    This reference factory only supports "fake" (rule-based, no API key).
    LLM-backed implementations (claude, gemini, openai, ollama) live in
    downstream implementation repos and are not exposed here.
    """
    backend = os.getenv("CAP_MACHINE_MODEL_BACKEND", "fake").lower()
    if backend in ("fake", ""):
        from .machine_model_construction_fake import FakeMachineModel
        return FakeMachineModel()

    msg = (
        f"Backend '{backend}' is not available in cap-reference. "
        "Only 'fake' is bundled. LLM-backed implementations live in "
        "downstream implementation repos."
    )
    raise ValueError(msg)

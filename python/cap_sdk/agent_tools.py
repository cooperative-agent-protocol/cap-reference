# Copyright 2026 CAP Authors
# SPDX-License-Identifier: Apache-2.0

"""Agent Tool definitions — analogous to Claude Code's Read/Bash/Grep tools.

Each tool has a name, description (for LLM system prompt), JSON schema for
arguments, and an async handler function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Result of executing a tool."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class AgentTool:
    """Tool available to the agent's cognitive layer.

    Analogous to Claude Code's tools (Read, Bash, Grep, etc.).

    Attributes:
        name: Tool identifier (e.g., "read_state", "move_to", "report_to_site").
        description: Human-readable description for the LLM's system prompt.
        parameters_schema: JSON Schema dict describing expected arguments.
        handler: Async function that executes the tool and returns ToolResult.
        requires_approval: If True, needs site agent approval before execution.
        is_movement: If True, delegates to reactive layer (non-blocking).
        max_frequency_hz: Rate limit (0 = unlimited).
    """

    name: str
    description: str
    parameters_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[ToolResult]]
    requires_approval: bool = False
    is_movement: bool = False
    max_frequency_hz: float = 0.0

    def to_llm_schema(self) -> dict[str, Any]:
        """Convert to LLM function-calling schema format."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }

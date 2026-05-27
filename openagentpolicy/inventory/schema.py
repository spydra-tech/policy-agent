from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ArgumentSchema(BaseModel):
    type: str
    description: str | None = None
    allowed_values: list[Any] | None = None
    aliases: list[str] | None = None


class Application(BaseModel):
    id: str
    name: str | None = None
    environment: str | None = None


class Agent(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None
    framework: str | None = None


class Tool(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None
    side_effect: bool = False
    risk_level: RiskLevel | None = None
    arguments: dict[str, ArgumentSchema] = Field(default_factory=dict)


class Inventory(BaseModel):
    application: Application | None = None
    agents: list[Agent] = Field(default_factory=list)
    tools: list[Tool] = Field(default_factory=list)

    def get_tool(self, tool_id: str) -> Tool | None:
        for tool in self.tools:
            if tool.id == tool_id:
                return tool
            if tool.name == tool_id:
                return tool
        return None


# Backward-compatible aliases
ToolDefinition = Tool
ToolInventory = Inventory

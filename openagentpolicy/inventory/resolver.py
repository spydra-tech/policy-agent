from __future__ import annotations

import logging
from pathlib import Path

from openagentpolicy.config import InventoryConfig
from openagentpolicy.inventory.providers import (
    AnnotationInventoryProvider,
    create_inventory_provider,
)
from openagentpolicy.inventory.schema import Inventory, Tool

logger = logging.getLogger(__name__)


class InventoryResolver:
    """Resolve tool inventory from configured providers."""

    def __init__(self, config: InventoryConfig, base_path: Path) -> None:
        self.config = config
        self.base_path = base_path
        self._provider = create_inventory_provider(config, base_path)
        self._cached: Inventory | None = None

    def resolve(self) -> Inventory:
        """Load inventory and merge with annotation-derived tools."""
        base_inventory = self._provider.load()
        annotation_inventory = AnnotationInventoryProvider().load()
        inventory = _merge_inventories(
            base_inventory=base_inventory,
            annotation_inventory=annotation_inventory,
            strategy=self.config.conflict_strategy,
        )
        self._cached = inventory
        return inventory

    def resolve_for_compiler(self) -> Inventory:
        """Inventory snapshot used by the English policy compiler."""
        if self._cached is not None:
            return self._cached
        return self.resolve()

    def preload(self) -> Inventory:
        """Eagerly load and cache inventory (e.g. before policy compilation)."""
        return self.resolve()


def _merge_inventories(
    *,
    base_inventory: Inventory,
    annotation_inventory: Inventory,
    strategy: str,
) -> Inventory:
    normalized = strategy.strip().lower()
    if normalized not in {
        "fail",
        "prefer_static",
        "prefer_annotations",
        "merge_with_warning",
    }:
        raise ValueError(
            "inventory.conflict_strategy must be one of "
            "fail|prefer_static|prefer_annotations|merge_with_warning"
        )

    merged_tools: dict[str, Tool] = {tool.id: tool for tool in base_inventory.tools}
    for ann_tool in annotation_inventory.tools:
        existing = merged_tools.get(ann_tool.id)
        if existing is None:
            merged_tools[ann_tool.id] = ann_tool
            continue

        if _tools_equal(existing, ann_tool):
            continue

        if normalized == "fail":
            raise ValueError(
                f"Inventory conflict for tool {ann_tool.id!r} between configured "
                "inventory and annotations"
            )
        if normalized == "prefer_static":
            continue
        if normalized == "prefer_annotations":
            merged_tools[ann_tool.id] = ann_tool
            continue
        if normalized == "merge_with_warning":
            logger.warning(
                "Inventory conflict for tool %s: merging static+annotations with warning",
                ann_tool.id,
            )
            merged_tools[ann_tool.id] = _merge_tools(existing, ann_tool)
            continue

    merged_application = base_inventory.application
    merged_agents = base_inventory.agents
    if not merged_application:
        merged_application = annotation_inventory.application
    if not merged_agents:
        merged_agents = annotation_inventory.agents

    return Inventory(
        application=merged_application,
        agents=merged_agents,
        tools=list(merged_tools.values()),
    )


def _tools_equal(a: Tool, b: Tool) -> bool:
    return a.model_dump(mode="json") == b.model_dump(mode="json")


def _merge_tools(static_tool: Tool, annotation_tool: Tool) -> Tool:
    merged_args = dict(static_tool.arguments)
    for name, arg in annotation_tool.arguments.items():
        if name in merged_args:
            static_arg = merged_args[name]
            if static_arg.model_dump(mode="json") != arg.model_dump(mode="json"):
                logger.warning(
                    "Argument conflict for tool %s argument %s; keeping static definition",
                    static_tool.id,
                    name,
                )
            continue
        merged_args[name] = arg

    return static_tool.model_copy(
        update={
            "name": static_tool.name or annotation_tool.name,
            "description": static_tool.description or annotation_tool.description,
            "side_effect": static_tool.side_effect or annotation_tool.side_effect,
            "risk_level": static_tool.risk_level or annotation_tool.risk_level,
            "arguments": merged_args,
        }
    )

from __future__ import annotations

import pytest

from openagentpolicy.inventory.resolver import _merge_inventories
from openagentpolicy.inventory.schema import ArgumentSchema, Inventory, Tool


def _static_inventory() -> Inventory:
    return Inventory(
        tools=[
            Tool(
                id="approve_loan",
                name="Approve Loan Static",
                arguments={"amount": ArgumentSchema(type="number")},
            )
        ]
    )


def _annotation_inventory() -> Inventory:
    return Inventory(
        tools=[
            Tool(
                id="approve_loan",
                name="Approve Loan Annotation",
                arguments={"risk_score": ArgumentSchema(type="number")},
            )
        ]
    )


def test_conflict_strategy_fail_raises() -> None:
    with pytest.raises(ValueError, match="Inventory conflict"):
        _merge_inventories(
            base_inventory=_static_inventory(),
            annotation_inventory=_annotation_inventory(),
            strategy="fail",
        )


def test_conflict_strategy_prefer_static() -> None:
    merged = _merge_inventories(
        base_inventory=_static_inventory(),
        annotation_inventory=_annotation_inventory(),
        strategy="prefer_static",
    )
    tool = merged.get_tool("approve_loan")
    assert tool is not None
    assert tool.name == "Approve Loan Static"
    assert "amount" in tool.arguments
    assert "risk_score" not in tool.arguments


def test_conflict_strategy_prefer_annotations() -> None:
    merged = _merge_inventories(
        base_inventory=_static_inventory(),
        annotation_inventory=_annotation_inventory(),
        strategy="prefer_annotations",
    )
    tool = merged.get_tool("approve_loan")
    assert tool is not None
    assert tool.name == "Approve Loan Annotation"
    assert "amount" not in tool.arguments
    assert "risk_score" in tool.arguments


def test_conflict_strategy_merge_with_warning_merges_arguments() -> None:
    merged = _merge_inventories(
        base_inventory=_static_inventory(),
        annotation_inventory=_annotation_inventory(),
        strategy="merge_with_warning",
    )
    tool = merged.get_tool("approve_loan")
    assert tool is not None
    assert tool.name == "Approve Loan Static"
    assert "amount" in tool.arguments
    assert "risk_score" in tool.arguments

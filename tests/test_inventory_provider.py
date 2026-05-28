from pathlib import Path

import pytest
import yaml

from openagentpolicy.config import InventoryConfig, resolve_config_path
from openagentpolicy.inventory.providers import (
    AnnotationInventoryProvider,
    FileInventoryProvider,
    HTTPInventoryProvider,
    create_inventory_provider,
)
from openagentpolicy.inventory.registry import clear_registered_tools


def test_file_inventory_provider_loads_yaml(tmp_path: Path) -> None:
    data = {
        "application": {"id": "loan-app", "name": "Loan App"},
        "agents": [{"id": "agent-1", "framework": "custom"}],
        "tools": [
            {
                "id": "approve_loan",
                "name": "Approve Loan",
                "description": "Approve loans",
                "risk_level": "high",
                "arguments": {
                    "amount": {"type": "number"},
                    "risk_score": {"type": "number"},
                },
            }
        ],
    }
    path = tmp_path / "inventory.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    inventory = FileInventoryProvider(path).load()
    assert inventory.application is not None
    assert inventory.application.id == "loan-app"
    assert len(inventory.agents) == 1
    assert len(inventory.tools) == 1
    tool = inventory.tools[0]
    assert tool.id == "approve_loan"
    assert "amount" in tool.arguments


def test_file_inventory_provider_loads_json(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"
    path.write_text(
        '{"tools": [{"id": "send_email", "arguments": {"to": {"type": "string"}}}]}',
        encoding="utf-8",
    )
    inventory = FileInventoryProvider(path).load()
    assert inventory.tools[0].id == "send_email"


def test_create_file_inventory_provider_resolves_relative_path(tmp_path: Path) -> None:
    config_dir = tmp_path / "app"
    config_dir.mkdir()
    inventory_path = config_dir / "inventory.yaml"
    inventory_path.write_text(
        yaml.dump({"tools": [{"id": "tool_a"}]}),
        encoding="utf-8",
    )

    provider = create_inventory_provider(
        InventoryConfig(provider="file", path="./inventory.yaml"),
        config_dir,
    )
    inventory = provider.load()
    assert inventory.tools[0].id == "tool_a"
    assert resolve_config_path(config_dir, "./inventory.yaml") == inventory_path.resolve()


def test_http_inventory_provider_requires_requests() -> None:
    provider = HTTPInventoryProvider("https://example.com/inventory.yaml")
    with pytest.raises(ImportError, match="requests"):
        provider.load()


def test_annotation_inventory_provider_via_config_not_implemented() -> None:
    clear_registered_tools()
    provider = AnnotationInventoryProvider()
    inventory = provider.load()
    assert inventory.tools == []


def test_inventory_get_tool() -> None:
    from openagentpolicy.inventory.schema import Inventory, Tool

    inv = Inventory(tools=[Tool(id="a"), Tool(id="b", name="beta")])
    assert inv.get_tool("b") is not None
    assert inv.get_tool("beta") is not None
    assert inv.get_tool("missing") is None

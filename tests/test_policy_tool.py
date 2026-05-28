from openagentpolicy.annotations import get_tool_definition, policy_tool
from openagentpolicy.inventory.registry import clear_registered_tools, register_tool_definition
from openagentpolicy.inventory.providers import AnnotationInventoryProvider
from openagentpolicy.inventory.schema import RiskLevel
from typing import Optional


def setup_function() -> None:
    clear_registered_tools()
    definition = get_tool_definition(search_docs)
    if definition is not None:
        register_tool_definition(definition)


@policy_tool(name="search_docs", description="Search documentation", risk_level="low")
def search_docs(query: str) -> list[str]:
    return [query]


def test_policy_tool_attaches_definition() -> None:
    definition = get_tool_definition(search_docs)
    assert definition is not None
    assert definition.id == "search_docs"
    assert definition.description == "Search documentation"
    assert definition.risk_level == RiskLevel.LOW
    assert "query" in definition.arguments


def test_policy_tool_default_name() -> None:
    @policy_tool()
    def send_email(to: str, body: str) -> bool:
        return True

    definition = get_tool_definition(send_email)
    assert definition is not None
    assert definition.id == "send_email"


def test_annotation_inventory_provider() -> None:
    import tests.test_policy_tool as mod

    provider = AnnotationInventoryProvider(modules=[mod])
    inventory = provider.load()
    ids = {t.id for t in inventory.tools}
    assert "search_docs" in ids


def test_policy_tool_inferrs_types_from_annotations() -> None:
    @policy_tool()
    def infer_types(
        email: str,
        attempts: int,
        confidence: float,
        is_active: bool,
        tags: list[str],
        meta: dict[str, str],
        optional_count: Optional[int] = None,
    ) -> bool:
        return True

    definition = get_tool_definition(infer_types)
    assert definition is not None
    assert definition.arguments["email"].type == "string"
    assert definition.arguments["attempts"].type == "number"
    assert definition.arguments["confidence"].type == "number"
    assert definition.arguments["is_active"].type == "boolean"
    assert definition.arguments["tags"].type == "array"
    assert definition.arguments["meta"].type == "object"
    assert definition.arguments["optional_count"].type == "number"

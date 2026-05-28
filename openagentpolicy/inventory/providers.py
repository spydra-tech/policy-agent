from __future__ import annotations

import json
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

from openagentpolicy.config import InventoryConfig, resolve_config_path
from openagentpolicy.inventory.registry import get_tool_definition, registered_tools
from openagentpolicy.inventory.schema import Inventory, Tool


def load_data_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        data: Any = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Inventory file must contain a mapping: {path}")
    return data


class InventoryProvider(ABC):
    @abstractmethod
    def load(self) -> Inventory:
        """Load tool inventory from the provider source."""


class FileInventoryProvider(InventoryProvider):
    """Load inventory from a YAML or JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    def load(self) -> Inventory:
        return Inventory.model_validate(load_data_file(self.path))


class HTTPInventoryProvider(InventoryProvider):
    """Load inventory from a remote HTTP endpoint."""

    def __init__(self, url: str) -> None:
        self.url = url

    def load(self) -> Inventory:
        data = _http_get_json(self.url)
        if not isinstance(data, dict):
            raise ValueError(f"HTTP inventory response must be a mapping: {self.url}")
        return Inventory.model_validate(data)


class AnnotationInventoryProvider(InventoryProvider):
    """Collect tools from @policy_tool functions (direct use only for now)."""

    def __init__(self, modules: list[Any] | None = None) -> None:
        self.modules = modules

    def load(self) -> Inventory:
        if self.modules is not None:
            return _load_annotation_inventory(self.modules)
        return Inventory(tools=registered_tools())


# Backward-compatible alias
StaticInventoryProvider = FileInventoryProvider
RemoteInventoryProvider = HTTPInventoryProvider


def create_inventory_provider(
    config: InventoryConfig, base_path: Path
) -> InventoryProvider:
    provider = _normalize_inventory_provider(config.provider)

    if provider == "file":
        if not config.path:
            raise ValueError("inventory.provider 'file' requires path")
        path = resolve_config_path(base_path, config.path)
        return FileInventoryProvider(path)

    if provider == "http":
        if not config.url:
            raise ValueError("inventory.provider 'http' requires url")
        return HTTPInventoryProvider(config.url)

    if provider == "annotations":
        return AnnotationInventoryProvider()

    raise ValueError(f"Unknown inventory provider: {config.provider}")


def _normalize_inventory_provider(provider: str) -> str:
    aliases = {
        "static": "file",
        "remote": "http",
    }
    return aliases.get(provider, provider)


def _load_annotation_inventory(modules: list[Any]) -> Inventory:
    tools: list[Tool] = []
    seen: set[str] = set()
    for module in modules:
        if module is None:
            continue
        for obj in vars(module).values():
            if callable(obj):
                definition = get_tool_definition(obj)
                if definition and definition.id not in seen:
                    tools.append(definition)
                    seen.add(definition.id)
    return Inventory(tools=tools)


def _http_get_json(url: str) -> Any:
    try:
        import requests
    except ImportError as exc:
        raise ImportError(
            "HTTP inventory provider requires the 'requests' package. "
            "Install with: pip install requests"
        ) from exc

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    if "json" in content_type:
        return response.json()
    return yaml.safe_load(response.text) or {}

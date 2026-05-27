from __future__ import annotations

from pathlib import Path

from openagentpolicy.config import InventoryConfig
from openagentpolicy.inventory.providers import create_inventory_provider
from openagentpolicy.inventory.schema import Inventory


class InventoryResolver:
    """Resolve tool inventory from configured providers."""

    def __init__(self, config: InventoryConfig, base_path: Path) -> None:
        self.config = config
        self.base_path = base_path
        self._provider = create_inventory_provider(config, base_path)
        self._cached: Inventory | None = None

    def resolve(self) -> Inventory:
        """Load inventory from the configured provider."""
        inventory = self._provider.load()
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

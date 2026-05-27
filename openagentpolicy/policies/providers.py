from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

from openagentpolicy.config import PoliciesConfig, resolve_config_path
from openagentpolicy.inventory.schema import Inventory
from openagentpolicy.policies.compiler import PolicyCompiler
from openagentpolicy.policies.schema import (
    CompileStatus,
    Policy,
    PolicyCompileResult,
    PolicyDocument,
    PolicyType,
)

logger = logging.getLogger(__name__)

POLICY_FILE_EXTENSIONS = (".yaml", ".yml", ".json")


def load_policy_file(path: Path) -> list[PolicyDocument]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        data: Any = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if isinstance(data, list):
        return [PolicyDocument.model_validate(item) for item in data]
    return [PolicyDocument.model_validate(data)]


class PolicySourceProvider(ABC):
    @abstractmethod
    def load_documents(self) -> list[PolicyDocument]:
        """Load raw policy documents from the provider source."""


class FilePolicyProvider(PolicySourceProvider):
    """Load policies from a single YAML or JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    def load_documents(self) -> list[PolicyDocument]:
        return load_policy_file(self.path)


class DirectoryPolicyProvider(PolicySourceProvider):
    """Load all policy files from a directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        if not self.directory.is_dir():
            raise NotADirectoryError(
                f"Policy directory does not exist: {self.directory}"
            )

    def load_documents(self) -> list[PolicyDocument]:
        documents: list[PolicyDocument] = []
        for extension in POLICY_FILE_EXTENSIONS:
            for path in sorted(self.directory.glob(f"*{extension}")):
                documents.extend(load_policy_file(path))
        return documents


class HTTPPolicyProvider(PolicySourceProvider):
    """Load policies from a remote HTTP endpoint."""

    def __init__(self, url: str) -> None:
        self.url = url

    def load_documents(self) -> list[PolicyDocument]:
        from openagentpolicy.inventory.providers import _http_get_json

        data = _http_get_json(self.url)
        if isinstance(data, list):
            return [PolicyDocument.model_validate(item) for item in data]
        return [PolicyDocument.model_validate(data)]


def create_policy_source_provider(
    config: PoliciesConfig, base_path: Path
) -> PolicySourceProvider:
    provider = _normalize_policy_provider(config.provider)

    if provider == "file":
        if not config.path:
            raise ValueError("policies.provider 'file' requires path")
        path = resolve_config_path(base_path, config.path)
        if path.is_dir():
            return DirectoryPolicyProvider(path)
        return FilePolicyProvider(path)

    if provider == "directory":
        if not config.path:
            raise ValueError("policies.provider 'directory' requires path")
        path = resolve_config_path(base_path, config.path)
        return DirectoryPolicyProvider(path)

    if provider == "http":
        if not config.url:
            raise ValueError("policies.provider 'http' requires url")
        return HTTPPolicyProvider(config.url)

    if provider == "static":
        return _legacy_static_policy_provider(config, base_path)

    raise ValueError(f"Unknown policies provider: {config.provider}")


def _legacy_static_policy_provider(
    config: PoliciesConfig, base_path: Path
) -> PolicySourceProvider:
    if config.path:
        path = resolve_config_path(base_path, config.path)
        if path.is_dir():
            return DirectoryPolicyProvider(path)
        return FilePolicyProvider(path)
    if config.paths:
        return _MultiPathPolicyProvider(config, base_path)
    raise ValueError("static policy provider requires path or paths")


class _MultiPathPolicyProvider(PolicySourceProvider):
    def __init__(self, config: PoliciesConfig, base_path: Path) -> None:
        self.config = config
        self.base_path = base_path

    def load_documents(self) -> list[PolicyDocument]:
        documents: list[PolicyDocument] = []
        for entry in self.config.paths:
            path = resolve_config_path(self.base_path, entry)
            if path.is_dir():
                documents.extend(DirectoryPolicyProvider(path).load_documents())
            else:
                documents.extend(FilePolicyProvider(path).load_documents())
        return documents


def _normalize_policy_provider(provider: str) -> str:
    aliases = {
        "remote": "http",
    }
    return aliases.get(provider, provider)


class PolicyProvider:
    """Load and compile policies; only compiled structured policies are enforced."""

    def __init__(
        self,
        config: PoliciesConfig,
        base_path: Path,
        *,
        inventory: Inventory | None = None,
    ) -> None:
        self.config = config
        self.base_path = base_path
        self._source = create_policy_source_provider(config, base_path)
        self._inventory = inventory or Inventory()
        self._compiler = PolicyCompiler(self._inventory)
        self._last_compile_results: list[PolicyCompileResult] = []

    @property
    def compile_results(self) -> list[PolicyCompileResult]:
        return list(self._last_compile_results)

    def load_documents(self) -> list[PolicyDocument]:
        return self._source.load_documents()

    def load_policies(self) -> list[Policy]:
        """Load enforceable compiled policies only."""
        policies, _ = self.load_policies_with_results()
        return policies

    def load_policies_with_results(
        self,
    ) -> tuple[list[Policy], list[PolicyCompileResult]]:
        policies: list[Policy] = []
        results: list[PolicyCompileResult] = []

        for document in self.load_documents():
            if document.policy_type == PolicyType.ENGLISH:
                if not self.config.support_english:
                    logger.warning(
                        "Skipping english policy %s (support_english=false)",
                        document.id,
                    )
                    continue
                result = self._compiler.compile_document(document)
                results.append(result)
                self._log_compile_result(result)
                if (
                    result.compile_status == CompileStatus.COMPILED
                    and result.compiled_policy is not None
                ):
                    policies.append(result.compiled_policy)
                continue

            if document.rules or document.policy_type == PolicyType.STRUCTURED:
                result = self._compiler.compile_document(document)
                results.append(result)
                self._log_compile_result(result)
                if (
                    result.compile_status == CompileStatus.COMPILED
                    and result.compiled_policy
                ):
                    policies.append(result.compiled_policy)
                continue

        self._last_compile_results = results
        return policies, results

    def load_compiled(self) -> list[Policy]:
        """Backward-compatible alias for load_policies."""
        return self.load_policies()

    def _log_compile_result(self, result: PolicyCompileResult) -> None:
        if result.compile_status == CompileStatus.COMPILED:
            logger.info(
                "Compiled policy %s (confidence=%.2f, terms=%s)",
                result.policy_id,
                result.confidence,
                result.resolved_terms,
            )
            return
        if result.compile_status == CompileStatus.NOT_ENFORCEABLE:
            logger.warning(
                "Policy %s is not enforceable: %s; missing_fields=%s",
                result.policy_id,
                result.message,
                result.missing_fields,
            )
            return
        logger.warning(
            "Policy %s needs review: %s",
            result.policy_id,
            result.message,
        )

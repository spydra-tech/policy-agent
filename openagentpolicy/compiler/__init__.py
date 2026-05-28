from openagentpolicy.compiler.compile_result import (
    CompileResult,
    CompileResultStatus,
    Enforceability,
)
from openagentpolicy.compiler.english_policy_compiler import EnglishPolicyCompiler
from openagentpolicy.inventory.schema import Inventory


def compile_english_policy(
    *,
    english: str,
    inventory: Inventory,
    policy_id: str | None = None,
    action_hint: dict | None = None,
    hints: dict | None = None,
) -> CompileResult:
    compiler = EnglishPolicyCompiler(inventory=inventory)
    return compiler.compile(
        english=english,
        policy_id=policy_id,
        action_hint=action_hint,
        hints=hints,
    )


__all__ = [
    "CompileResult",
    "CompileResultStatus",
    "Enforceability",
    "EnglishPolicyCompiler",
    "compile_english_policy",
]

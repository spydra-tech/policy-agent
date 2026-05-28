from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from openagentpolicy import check_final_response_any, configure
from openagentpolicy.annotations import PolicyViolation, reset_runtime


@pytest.fixture(autouse=True)
def _reset_global_runtime() -> None:
    reset_runtime()
    yield
    reset_runtime()


def _write_response_policy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    policies_dir = root / "policies"
    policies_dir.mkdir(parents=True)

    (root / "inventory.yaml").write_text(yaml.dump({"tools": []}), encoding="utf-8")
    (policies_dir / "response.yaml").write_text(
        yaml.dump(
            {
                "id": "block-guarantee",
                "enabled": True,
                "policy_type": "structured",
                "trigger": {"event": "before_final_response"},
                "conditions": {
                    "field": "final_response",
                    "operator": "contains",
                    "value": "guaranteed approval",
                },
                "action": {
                    "type": "block",
                    "message": "Unsafe response language",
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "openagentpolicy.yaml").write_text(
        yaml.dump(
            {
                "inventory": {"provider": "file", "path": "./inventory.yaml"},
                "policies": {"provider": "directory", "path": "./policies"},
            }
        ),
        encoding="utf-8",
    )
    return root / "openagentpolicy.yaml"


def test_check_final_response_any_with_string(tmp_path: Path) -> None:
    configure(_write_response_policy_fixture(tmp_path))
    assert (
        check_final_response_any("Application submitted.")
        == "Application submitted."
    )


def test_check_final_response_any_with_dict(tmp_path: Path) -> None:
    configure(_write_response_policy_fixture(tmp_path))
    payload = {"content": "Application submitted.", "id": "r-1"}
    checked = check_final_response_any(payload)
    assert checked["content"] == "Application submitted."
    assert checked["id"] == "r-1"


def test_check_final_response_any_with_model(tmp_path: Path) -> None:
    class Reply(BaseModel):
        content: str
        kind: str = "assistant"

    configure(_write_response_policy_fixture(tmp_path))
    reply = Reply(content="Application submitted.")
    checked = check_final_response_any(reply)
    assert isinstance(checked, Reply)
    assert checked.content == "Application submitted."
    assert checked.kind == "assistant"


def test_check_final_response_any_with_object_attr(tmp_path: Path) -> None:
    class Reply:
        def __init__(self, content: str) -> None:
            self.content = content
            self.kind = "assistant"

    configure(_write_response_policy_fixture(tmp_path))
    reply = Reply(content="Application submitted.")
    checked = check_final_response_any(reply)
    assert checked is reply
    assert checked.content == "Application submitted."
    assert checked.kind == "assistant"


def test_check_final_response_any_blocks_unsafe_text(tmp_path: Path) -> None:
    configure(_write_response_policy_fixture(tmp_path))
    with pytest.raises(PolicyViolation, match="Unsafe response language"):
        check_final_response_any({"content": "We provide guaranteed approval."})


def test_check_final_response_any_rejects_unsupported_shape(
    tmp_path: Path,
) -> None:
    configure(_write_response_policy_fixture(tmp_path))
    with pytest.raises(TypeError, match="expected"):
        check_final_response_any({"payload": {"text": "nested"}})

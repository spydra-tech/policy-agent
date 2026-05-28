from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_agentic_loan_desk_demo_runs() -> None:
    demo_dir = Path(__file__).resolve().parents[1] / "examples" / "agentic_loan_desk"
    result = subprocess.run(
        [sys.executable, "demo.py"],
        cwd=demo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "Scenario A" in result.stdout
    assert "ALLOWED" in result.stdout
    assert "BLOCKED" in result.stdout
    assert "compile_status" in result.stdout

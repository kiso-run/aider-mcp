"""Live integration test — runs real aider against a tiny fixture repo.

Runs only when ``OPENROUTER_API_KEY`` is set in the environment. Exercises
the full end-to-end path: ``aider_codegen`` → aider subprocess → OpenRouter
→ on-disk file edits → ``git diff`` capture.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from kiso_aider_mcp.aider_runner import run_aider_codegen


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("OPENROUTER_API_KEY"),
        reason="OPENROUTER_API_KEY required for live aider test",
    ),
]


def _init_git_repo(workspace: Path, file_name: str, contents: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=workspace, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=workspace, check=True,
    )
    (workspace / file_name).write_text(contents)
    subprocess.run(["git", "add", file_name], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial"], cwd=workspace, check=True,
    )


def test_aider_fixes_an_obvious_bug(tmp_path: Path):
    """Prompt aider to fix an intentionally-broken function, verify the diff."""
    _init_git_repo(
        tmp_path,
        "buggy.py",
        # The body has a typo: `retrun` instead of `return`.
        "def add(a, b):\n    retrun a + b\n",
    )

    result = run_aider_codegen(
        prompt=(
            "Fix the typo in buggy.py: `retrun` should be `return`. "
            "Do not change anything else."
        ),
        editable_files=["buggy.py"],
        mode="code",
        workspace=str(tmp_path),
    )

    # Aider may occasionally need a retry; don't fail the suite on a flake,
    # but the typical pass path should produce success + a meaningful diff.
    assert result["success"], (
        f"aider run failed: stderr={result['stderr']!r}, "
        f"output={result['output'][:200]!r}"
    )
    assert "return" in (tmp_path / "buggy.py").read_text()
    assert "retrun" not in (tmp_path / "buggy.py").read_text()
    # Diff should show the edit (exact format varies by aider version).
    assert result["diff"], "expected git diff to be non-empty after edit"

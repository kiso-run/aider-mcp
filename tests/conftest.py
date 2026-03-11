"""Shared fixtures for tool-aider tests."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).parent.parent
RUN_PY = TOOL_DIR / "run.py"


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def full_config():
    return {
        "provider": "openrouter",
        "mode": "architect",
        "architect_model": "openrouter/z-ai/glm-5",
        "editor_model": "openrouter/deepseek/deepseek-v3.2",
        "weak_model": "openrouter/deepseek/deepseek-v3.2",
        "map_tokens": 4096,
        "editor_edit_format": "udiff",
        "auto_commits": True,
        "commit_language": "en",
    }


@pytest.fixture
def minimal_config():
    return {
        "provider": "openrouter",
    }


@pytest.fixture
def no_config():
    return {}


# ---------------------------------------------------------------------------
# Stdin data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def full_stdin_data():
    return {
        "args": {
            "message": "refactor the auth module to use JWT tokens",
            "files": "src/auth.py,src/middleware.py",
            "mode": "architect",
            "read_only_files": "src/models.py",
        },
        "session": "dev-backend",
        "workspace": "/tmp/test-workspace",
        "session_secrets": {},
        "plan_outputs": [],
    }


@pytest.fixture
def minimal_stdin_data():
    return {
        "args": {
            "message": "add a docstring to main()",
        },
        "session": "test",
        "workspace": "/tmp/test-workspace",
        "session_secrets": {},
        "plan_outputs": [],
    }


# ---------------------------------------------------------------------------
# Helper: run run.py as subprocess
# ---------------------------------------------------------------------------

def run_tool(stdin_data: dict, env_extra: dict | None = None, mock_aider: Path | None = None) -> subprocess.CompletedProcess:
    """Run run.py as a subprocess with injected stdin and env."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
        "KISO_SKILL_AIDER_API_KEY": "test-api-key",
    }
    if env_extra:
        env.update(env_extra)

    if mock_aider:
        # Prepend mock aider's directory to PATH so it shadows the real aider
        env["PATH"] = str(mock_aider.parent) + ":" + env["PATH"]

    return subprocess.run(
        [sys.executable, str(RUN_PY)],
        input=json.dumps(stdin_data),
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def mock_aider_ok(tmp_path) -> Path:
    """A fake aider binary that exits 0 and prints its args."""
    aider = tmp_path / "aider"
    aider.write_text(
        "#!/bin/sh\necho 'aider ok'\necho \"args: $*\"\n",
        encoding="utf-8",
    )
    aider.chmod(0o755)
    return aider


@pytest.fixture
def mock_aider_fail(tmp_path) -> Path:
    """A fake aider binary that exits 1."""
    aider = tmp_path / "aider"
    aider.write_text(
        "#!/bin/sh\necho 'aider error' >&2\nexit 1\n",
        encoding="utf-8",
    )
    aider.chmod(0o755)
    return aider

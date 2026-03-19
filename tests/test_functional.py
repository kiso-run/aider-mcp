"""Functional tests — subprocess contract for run.py."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

TOOL_DIR = Path(__file__).parent.parent
RUN_PY = TOOL_DIR / "run.py"
AIDER_BIN = Path(sys.executable).parent / "aider"


@pytest.fixture
def _swap_aider(tmp_path):
    """Context-manager fixture that swaps .venv/bin/aider with a mock script.

    Yields a callable: call it with the shell script body to install the mock.
    Restores the original binary on teardown.
    """
    backup = tmp_path / "aider.bak"
    if AIDER_BIN.exists():
        backup.write_bytes(AIDER_BIN.read_bytes())
        backup.chmod(AIDER_BIN.stat().st_mode)

    installed = False

    def _install(script_body: str):
        nonlocal installed
        AIDER_BIN.write_text(script_body, encoding="utf-8")
        AIDER_BIN.chmod(0o755)
        installed = True

    yield _install

    # Restore original
    if backup.exists():
        AIDER_BIN.write_bytes(backup.read_bytes())
        AIDER_BIN.chmod(backup.stat().st_mode)
    elif installed:
        AIDER_BIN.unlink(missing_ok=True)


def _run(stdin_data: dict, env_override: dict | None = None) -> subprocess.CompletedProcess:
    """Run run.py as subprocess with controlled env."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
        "KISO_TOOL_AIDER_API_KEY": "test-api-key",
    }
    if env_override:
        env.update(env_override)
    return subprocess.run(
        [sys.executable, str(RUN_PY)],
        input=json.dumps(stdin_data) if isinstance(stdin_data, dict) else stdin_data,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_raw(stdin_text: str, env_override: dict | None = None) -> subprocess.CompletedProcess:
    """Run run.py with raw stdin text (for malformed input tests)."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
        "KISO_TOOL_AIDER_API_KEY": "test-api-key",
    }
    if env_override:
        env.update(env_override)
    return subprocess.run(
        [sys.executable, str(RUN_PY)],
        input=stdin_text,
        capture_output=True,
        text=True,
        env=env,
    )


# ---- 1. Happy path — architect mode with files ----

def test_happy_path_architect(full_stdin_data, _swap_aider):
    _swap_aider("#!/bin/sh\necho 'Applied changes to auth.py'\n")
    result = _run(full_stdin_data)
    assert result.returncode == 0
    assert "Mode: architect" in result.stdout
    assert "Files:" in result.stdout
    assert "Applied changes" in result.stdout


# ---- 2. Happy path — code mode ----

def test_happy_path_code(minimal_stdin_data, _swap_aider):
    _swap_aider("#!/bin/sh\necho 'code changes done'\n")
    minimal_stdin_data["args"]["mode"] = "code"
    result = _run(minimal_stdin_data)
    assert result.returncode == 0
    assert "Mode: code" in result.stdout


# ---- 3. Happy path — ask mode with read_only_files ----

def test_happy_path_ask_readonly(minimal_stdin_data, _swap_aider):
    _swap_aider("#!/bin/sh\necho 'answer provided'\n")
    minimal_stdin_data["args"]["mode"] = "ask"
    minimal_stdin_data["args"]["read_only_files"] = "src/models.py"
    result = _run(minimal_stdin_data)
    assert result.returncode == 0
    assert "Mode: ask" in result.stdout
    assert "Read-only:" in result.stdout


# ---- 4. Error — aider fails ----

def test_aider_failure(_swap_aider, full_stdin_data):
    _swap_aider("#!/bin/sh\necho 'aider error' >&2\nexit 1\n")
    result = _run(full_stdin_data)
    assert result.returncode == 1
    # Header still printed on failure
    assert "Mode: architect" in result.stdout


# ---- 5. Error — missing API key ----

def test_missing_api_key(full_stdin_data, _swap_aider):
    _swap_aider("#!/bin/sh\necho 'should not run'\n")
    # Run without KISO_TOOL_AIDER_API_KEY in env
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
    }
    result = subprocess.run(
        [sys.executable, str(RUN_PY)],
        input=json.dumps(full_stdin_data),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1
    assert "API key" in result.stdout


# ---- 6. Error — invalid mode ----

def test_invalid_mode(full_stdin_data, _swap_aider):
    _swap_aider("#!/bin/sh\necho 'should not run'\n")
    full_stdin_data["args"]["mode"] = "destroy"
    result = _run(full_stdin_data)
    assert result.returncode == 1
    assert "unknown mode" in result.stdout


# ---- 7. Error — aider binary not found ----

def test_aider_not_found(full_stdin_data, tmp_path):
    # Remove aider binary temporarily
    backup = tmp_path / "aider.bak"
    if AIDER_BIN.exists():
        backup.write_bytes(AIDER_BIN.read_bytes())
        mode = AIDER_BIN.stat().st_mode
        AIDER_BIN.unlink()

    try:
        result = _run(full_stdin_data)
        assert result.returncode == 1
        assert "not found" in result.stdout
    finally:
        if backup.exists():
            AIDER_BIN.write_bytes(backup.read_bytes())
            AIDER_BIN.chmod(mode)


# ---- 8. Malformed input — invalid JSON ----

def test_invalid_json():
    result = _run_raw("not json at all")
    assert result.returncode != 0


# ---- 9. Malformed input — missing message key ----

def test_missing_message_key(_swap_aider):
    _swap_aider("#!/bin/sh\necho 'should not run'\n")
    data = {
        "args": {},  # no "message"
        "session": "test",
        "workspace": "/tmp/test-workspace",
        "session_secrets": {},
        "plan_outputs": [],
    }
    result = _run(data)
    assert result.returncode != 0


# ---- 10. ANSI stripping ----

def test_ansi_stripping(minimal_stdin_data, _swap_aider):
    _swap_aider("#!/bin/sh\necho -e '\\033[32mgreen text\\033[0m'\n")
    result = _run(minimal_stdin_data)
    assert result.returncode == 0
    assert "\033[" not in result.stdout
    assert "green text" in result.stdout


# ---- 11. SIGTERM graceful shutdown ----

def test_sigterm_forwarding(tmp_path, full_stdin_data, _swap_aider):
    # Mock aider that sleeps 30s (will be killed via SIGTERM)
    _swap_aider("#!/bin/sh\nsleep 30\n")

    proc = subprocess.Popen(
        [sys.executable, str(RUN_PY)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/root"),
            "KISO_TOOL_AIDER_API_KEY": "test-api-key",
        },
    )
    proc.stdin.write(json.dumps(full_stdin_data))
    proc.stdin.close()
    time.sleep(1)
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=15)
    assert proc.returncode == 0

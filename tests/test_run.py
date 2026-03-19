"""Unit and integration tests for the run() function (stdin/stdout contract)."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from run import run

RUN_PY = str(Path(__file__).parent.parent / "run.py")


def _ctx(args: dict) -> dict:
    return {
        "args": args,
        "session": "test",
        "workspace": "/tmp/test-workspace",
        "session_secrets": {},
        "plan_outputs": [],
    }


def _ok(stdout: str = "Changes applied.\n") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, stdout, "")


def _fail(stdout: str = "", stderr: str = "aider error") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 1, stdout, stderr)


# ---------------------------------------------------------------------------
# Unit tests: call run() directly, mock internals
# ---------------------------------------------------------------------------

def test_invalid_mode_exits_1(monkeypatch):
    monkeypatch.setenv("KISO_TOOL_AIDER_API_KEY", "key")
    args = {"message": "hi", "mode": "bad"}
    with patch("run.load_config", return_value={}), \
         patch.object(Path, "exists", return_value=True):
        with pytest.raises(SystemExit) as exc:
            run(args, _ctx(args))
    assert exc.value.code == 1


def test_missing_api_key_exits_1(monkeypatch):
    monkeypatch.delenv("KISO_TOOL_AIDER_API_KEY", raising=False)
    args = {"message": "hi"}
    with patch("run.load_config", return_value={}), \
         patch.object(Path, "exists", return_value=True):
        with pytest.raises(SystemExit) as exc:
            run(args, _ctx(args))
    assert exc.value.code == 1


def test_missing_binary_exits_1(monkeypatch):
    monkeypatch.setenv("KISO_TOOL_AIDER_API_KEY", "key")
    args = {"message": "hi"}
    with patch("run.load_config", return_value={}), \
         patch.object(Path, "exists", return_value=False):
        with pytest.raises(SystemExit) as exc:
            run(args, _ctx(args))
    assert exc.value.code == 1


def test_success_returns_string(monkeypatch):
    monkeypatch.setenv("KISO_TOOL_AIDER_API_KEY", "key")
    args = {"message": "refactor auth", "files": "src/auth.py"}
    with patch("run.load_config", return_value={"provider": "openrouter"}), \
         patch.object(Path, "exists", return_value=True), \
         patch("run.run_aider", return_value=_ok("Done.")):
        result = run(args, _ctx(args))
    assert isinstance(result, str)
    assert "Mode: architect" in result
    assert "Files: src/auth.py" in result
    assert "Done." in result


def test_success_ask_mode_with_read_only(monkeypatch):
    monkeypatch.setenv("KISO_TOOL_AIDER_API_KEY", "key")
    args = {"message": "explain", "mode": "ask", "read_only_files": "src/models.py"}
    with patch("run.load_config", return_value={"provider": "openrouter"}), \
         patch.object(Path, "exists", return_value=True), \
         patch("run.run_aider", return_value=_ok("Explanation.")):
        result = run(args, _ctx(args))
    assert "Mode: ask" in result
    assert "Read-only: src/models.py" in result
    assert "Explanation." in result


def test_success_no_files_no_read_only(monkeypatch):
    monkeypatch.setenv("KISO_TOOL_AIDER_API_KEY", "key")
    args = {"message": "what does main do?", "mode": "ask"}
    with patch("run.load_config", return_value={"provider": "openrouter"}), \
         patch.object(Path, "exists", return_value=True), \
         patch("run.run_aider", return_value=_ok("It's the entry point.")):
        result = run(args, _ctx(args))
    assert "Mode: ask" in result
    assert "Files:" not in result
    assert "Read-only:" not in result


def test_aider_failure_exits_1(monkeypatch):
    monkeypatch.setenv("KISO_TOOL_AIDER_API_KEY", "key")
    args = {"message": "refactor"}
    with patch("run.load_config", return_value={"provider": "openrouter"}), \
         patch.object(Path, "exists", return_value=True), \
         patch("run.run_aider", return_value=_fail()):
        with pytest.raises(SystemExit) as exc:
            run(args, _ctx(args))
    assert exc.value.code == 1


def test_aider_failure_with_output_shows_output(monkeypatch, capsys):
    """When aider exits 1 but produces stdout, that output should appear in the printed result."""
    monkeypatch.setenv("KISO_TOOL_AIDER_API_KEY", "key")
    args = {"message": "refactor"}
    with patch("run.load_config", return_value={"provider": "openrouter"}), \
         patch.object(Path, "exists", return_value=True), \
         patch("run.run_aider", return_value=_fail(stdout="Partial changes applied.")):
        with pytest.raises(SystemExit) as exc:
            run(args, _ctx(args))
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Partial changes applied." in captured.out


def test_success_code_mode_header(monkeypatch):
    """Verify 'Mode: code' appears in output for code mode."""
    monkeypatch.setenv("KISO_TOOL_AIDER_API_KEY", "key")
    args = {"message": "fix bug", "mode": "code", "files": "app.py"}
    with patch("run.load_config", return_value={"provider": "openrouter"}), \
         patch.object(Path, "exists", return_value=True), \
         patch("run.run_aider", return_value=_ok("Bug fixed.")):
        result = run(args, _ctx(args))
    assert "Mode: code" in result
    assert "Bug fixed." in result


def test_context_fields_accepted(monkeypatch):
    """run() accepts a full context dict without errors."""
    monkeypatch.setenv("KISO_TOOL_AIDER_API_KEY", "key")
    args = {"message": "fix bug", "files": "app.py"}
    context = {
        "args": args,
        "session": "prod",
        "workspace": "/root/.kiso/sessions/prod",
        "session_secrets": {"github_token": "ghp_xxx"},
        "plan_outputs": [{"index": 1, "type": "exec", "output": "ok", "status": "done"}],
    }
    with patch("run.load_config", return_value={"provider": "anthropic"}), \
         patch.object(Path, "exists", return_value=True), \
         patch("run.run_aider", return_value=_ok()):
        result = run(args, context)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Integration tests: stdin/stdout contract via subprocess
# ---------------------------------------------------------------------------

def _base_env() -> dict:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
    }


def test_contract_missing_api_key(full_stdin_data):
    result = subprocess.run(
        [sys.executable, RUN_PY],
        input=json.dumps(full_stdin_data),
        capture_output=True, text=True,
        env=_base_env(),
    )
    assert result.returncode == 1
    assert "API key" in result.stdout


def test_contract_invalid_mode(minimal_stdin_data):
    data = {**minimal_stdin_data, "args": {**minimal_stdin_data["args"], "mode": "invalid"}}
    result = subprocess.run(
        [sys.executable, RUN_PY],
        input=json.dumps(data),
        capture_output=True, text=True,
        env={**_base_env(), "KISO_TOOL_AIDER_API_KEY": "test-key"},
    )
    assert result.returncode == 1
    assert "invalid" in result.stdout


def test_contract_output_goes_to_stdout(full_stdin_data):
    """On any exit, stdout must be non-empty (planner/reviewer reads it)."""
    result = subprocess.run(
        [sys.executable, RUN_PY],
        input=json.dumps(full_stdin_data),
        capture_output=True, text=True,
        env=_base_env(),
    )
    assert result.stdout.strip()

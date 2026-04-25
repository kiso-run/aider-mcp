"""Unit tests for kiso_aider_mcp.aider_runner."""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from kiso_aider_mcp.aider_runner import (
    build_command,
    build_env,
    check_health,
    run_aider_codegen,
)


class TestBuildCommand:
    """Command assembly from tool args."""

    def test_architect_mode_adds_flag(self):
        cmd = build_command(prompt="fix bug", editable_files=["a.py"], mode="architect")
        assert "--architect" in cmd

    def test_code_mode_has_no_mode_flag(self):
        cmd = build_command(prompt="fix bug", editable_files=["a.py"], mode="code")
        assert "--architect" not in cmd
        assert "--ask" not in cmd

    def test_ask_mode_adds_flag(self):
        cmd = build_command(prompt="what does x do", mode="ask")
        assert "--ask" in cmd

    def test_prompt_goes_to_message(self):
        cmd = build_command(prompt="fix the race condition", mode="code")
        idx = cmd.index("--message")
        assert cmd[idx + 1] == "fix the race condition"

    def test_editable_files_are_positional(self):
        cmd = build_command(
            prompt="x", editable_files=["a.py", "b.py"], mode="code",
        )
        assert "a.py" in cmd
        assert "b.py" in cmd

    def test_readonly_files_use_read_flag(self):
        cmd = build_command(
            prompt="x", readonly_files=["ref.md"], mode="code",
        )
        idx = cmd.index("--read")
        assert cmd[idx + 1] == "ref.md"

    def test_model_override_adds_model_flag(self):
        cmd = build_command(
            prompt="x",
            architect_model="openrouter/anthropic/claude-4",
            mode="code",
        )
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "openrouter/anthropic/claude-4"

    def test_no_model_means_no_model_flag(self):
        cmd = build_command(prompt="x", mode="code")
        assert "--model" not in cmd

    def test_non_interactive_flags_always_present(self):
        cmd = build_command(prompt="x", mode="code")
        assert "--yes" in cmd
        assert "--no-pretty" in cmd
        assert "--no-fancy-input" in cmd
        assert "--no-suggest-shell-commands" in cmd

    def test_auto_commits_forced_off(self):
        cmd = build_command(prompt="x", mode="code")
        assert "--no-auto-commits" in cmd
        assert "--auto-commits" not in cmd

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="mode"):
            build_command(prompt="x", mode="bogus")

    def test_empty_prompt_raises(self):
        with pytest.raises(ValueError, match="prompt"):
            build_command(prompt="", mode="code")


class TestArchitectEditorModelSplit:
    """M11: distinct architect_model + editor_model parameters.

    Aider's architect mode uses two LLMs internally — a planner and an
    editor. The MCP surface should expose them separately so callers
    (notably Kiso's runtime) can route each role to the right model.
    """

    def test_architect_model_emits_model_flag(self):
        cmd = build_command(
            prompt="x", architect_model="openrouter/A", mode="architect",
        )
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "openrouter/A"

    def test_editor_model_emits_editor_model_flag_in_architect_mode(self):
        cmd = build_command(
            prompt="x",
            architect_model="openrouter/A",
            editor_model="openrouter/E",
            mode="architect",
        )
        idx = cmd.index("--editor-model")
        assert cmd[idx + 1] == "openrouter/E"

    def test_editor_model_ignored_in_code_mode(self):
        """editor_model is meaningless without --architect; drop it
        silently rather than passing a useless flag."""
        cmd = build_command(
            prompt="x",
            architect_model="openrouter/A",
            editor_model="openrouter/E",
            mode="code",
        )
        assert "--editor-model" not in cmd

    def test_editor_model_ignored_in_ask_mode(self):
        cmd = build_command(
            prompt="x",
            architect_model="openrouter/A",
            editor_model="openrouter/E",
            mode="ask",
        )
        assert "--editor-model" not in cmd

    def test_editor_model_only_no_architect(self):
        """Caller can override only the editor; aider keeps default
        architect."""
        cmd = build_command(
            prompt="x", editor_model="openrouter/E", mode="architect",
        )
        assert "--model" not in cmd
        idx = cmd.index("--editor-model")
        assert cmd[idx + 1] == "openrouter/E"

    def test_legacy_model_alias_maps_to_architect(self):
        """`model` is the deprecated alias of `architect_model`."""
        with pytest.warns(DeprecationWarning, match="architect_model"):
            cmd = build_command(
                prompt="x", model="openrouter/legacy", mode="architect",
            )
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "openrouter/legacy"

    def test_architect_model_wins_over_legacy_model(self):
        """Caller passing both: explicit architect_model takes precedence."""
        with pytest.warns(DeprecationWarning):
            cmd = build_command(
                prompt="x",
                architect_model="openrouter/new",
                model="openrouter/old",
                mode="architect",
            )
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "openrouter/new"
        assert "openrouter/old" not in cmd


class TestBuildEnv:
    """Environment wiring for aider subprocess."""

    def test_api_key_from_openrouter_env(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
        env = build_env()
        assert env["OPENROUTER_API_KEY"] == "sk-test-123"

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            build_env()

    def test_env_has_path_and_home(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        env = build_env()
        assert "PATH" in env
        assert "HOME" in env


class TestRunAiderCodegen:
    """End-to-end runner with mocked subprocess."""

    def _fake_completed(self, returncode=0, stdout="", stderr=""):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def test_success_returns_diff_from_git(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")

        with patch("kiso_aider_mcp.aider_runner._run_aider") as run_aider, \
             patch("kiso_aider_mcp.aider_runner._capture_diff") as capture_diff, \
             patch("kiso_aider_mcp.aider_runner._aider_binary_exists", return_value=True):
            run_aider.return_value = self._fake_completed(0, "edits applied", "")
            capture_diff.return_value = "--- a/foo.py\n+++ b/foo.py\n@@ +x = 1"
            result = run_aider_codegen(
                prompt="fix x", editable_files=["foo.py"], mode="code",
                workspace=str(tmp_path),
            )
            assert result["success"] is True
            assert "x = 1" in result["diff"]
            assert result["output"] == "edits applied"
            assert result["stderr"] == ""

    def test_failure_sets_success_false_and_reports_stderr(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        with patch("kiso_aider_mcp.aider_runner._run_aider") as run_aider, \
             patch("kiso_aider_mcp.aider_runner._capture_diff", return_value=""), \
             patch("kiso_aider_mcp.aider_runner._aider_binary_exists", return_value=True):
            run_aider.return_value = self._fake_completed(1, "", "boom")
            result = run_aider_codegen(
                prompt="x", mode="code", workspace=str(tmp_path),
            )
            assert result["success"] is False
            assert "boom" in result["stderr"]

    def test_missing_api_key_fails_before_subprocess(self, monkeypatch, tmp_path):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with patch("kiso_aider_mcp.aider_runner._run_aider") as run_aider:
            result = run_aider_codegen(
                prompt="x", mode="code", workspace=str(tmp_path),
            )
            assert result["success"] is False
            assert "OPENROUTER_API_KEY" in result["stderr"]
            run_aider.assert_not_called()

    def test_missing_aider_binary_fails_cleanly(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        with patch("kiso_aider_mcp.aider_runner._aider_binary_exists", return_value=False), \
             patch("kiso_aider_mcp.aider_runner._run_aider") as run_aider:
            result = run_aider_codegen(
                prompt="x", mode="code", workspace=str(tmp_path),
            )
            assert result["success"] is False
            assert "aider" in result["stderr"].lower()
            run_aider.assert_not_called()

    def test_affordable_cap_retry_on_openrouter_402(self, monkeypatch, tmp_path):
        """OpenRouter 402 `can only afford N` error triggers a single retry
        with --model-settings-file capping max_tokens to N."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        stderr_402 = (
            "Error: 402 — You requested up to 65536 tokens, "
            "but can only afford 4096 tokens for this request."
        )
        with patch("kiso_aider_mcp.aider_runner._aider_binary_exists", return_value=True), \
             patch("kiso_aider_mcp.aider_runner._capture_diff", return_value=""), \
             patch("kiso_aider_mcp.aider_runner._run_aider") as run_aider:
            run_aider.side_effect = [
                self._fake_completed(1, "", stderr_402),
                self._fake_completed(0, "ok", ""),
            ]
            result = run_aider_codegen(
                prompt="x", mode="code", architect_model="openrouter/x",
                workspace=str(tmp_path),
            )
            assert result["success"] is True
            assert run_aider.call_count == 2
            # Second call MUST contain --model-settings-file
            retry_cmd = run_aider.call_args_list[1].args[0]
            assert "--model-settings-file" in retry_cmd

    def test_no_retry_without_affordable_cap_phrase(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        with patch("kiso_aider_mcp.aider_runner._aider_binary_exists", return_value=True), \
             patch("kiso_aider_mcp.aider_runner._capture_diff", return_value=""), \
             patch("kiso_aider_mcp.aider_runner._run_aider") as run_aider:
            run_aider.return_value = self._fake_completed(1, "", "generic network error")
            result = run_aider_codegen(
                prompt="x", mode="code", workspace=str(tmp_path),
            )
            assert result["success"] is False
            assert run_aider.call_count == 1


class TestCheckHealth:
    """Doctor tool — environment and binary health checks."""

    def test_healthy_when_binary_and_key_present(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        with patch("kiso_aider_mcp.aider_runner._aider_binary_exists", return_value=True), \
             patch("kiso_aider_mcp.aider_runner._aider_version", return_value="0.82.0"):
            result = check_health()
            assert result["healthy"] is True
            assert result["issues"] == []
            assert result["version"] == "0.82.0"

    def test_unhealthy_when_binary_missing(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        with patch("kiso_aider_mcp.aider_runner._aider_binary_exists", return_value=False):
            result = check_health()
            assert result["healthy"] is False
            assert any("aider" in i.lower() for i in result["issues"])

    def test_unhealthy_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with patch("kiso_aider_mcp.aider_runner._aider_binary_exists", return_value=True), \
             patch("kiso_aider_mcp.aider_runner._aider_version", return_value="0.82.0"):
            result = check_health()
            assert result["healthy"] is False
            assert any("OPENROUTER_API_KEY" in i for i in result["issues"])

    def test_reports_all_issues_together(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with patch("kiso_aider_mcp.aider_runner._aider_binary_exists", return_value=False):
            result = check_health()
            assert result["healthy"] is False
            assert len(result["issues"]) >= 2

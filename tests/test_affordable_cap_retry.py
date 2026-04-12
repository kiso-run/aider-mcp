"""Tests for the OpenRouter per-request affordable-cap retry path.

When aider exits non-zero with an OpenRouter 402 error of the form
"can only afford N", the wrapper parses N from stderr and retries
aider exactly once with a model-settings-file YAML override that
caps ``extra_params.max_tokens`` to N for every configured model
name. Any other failure mode (parse miss, non-402 error, retry
also failing) falls through to the original error path unchanged.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run as tool_run  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


_OPENROUTER_402_STDERR = (
    "litellm.BadRequestError: OpenrouterException - "
    "This request requires more credits, or fewer max_tokens. "
    "You requested up to 64000 tokens, but can only afford 49423. "
    "To increase, visit https://openrouter.ai/settings/"
)


# ---------------------------------------------------------------------------
# _parse_openrouter_affordable_cap — pure deterministic parser
# ---------------------------------------------------------------------------


class TestParseAffordableCap:
    def test_parses_integer_after_can_only_afford(self):
        assert (
            tool_run._parse_openrouter_affordable_cap(_OPENROUTER_402_STDERR)
            == 49423
        )

    def test_returns_none_on_empty_stderr(self):
        assert tool_run._parse_openrouter_affordable_cap("") is None

    def test_returns_none_when_pattern_missing(self):
        assert (
            tool_run._parse_openrouter_affordable_cap(
                "Some other unrelated aider error"
            )
            is None
        )

    def test_returns_none_on_malformed_number(self):
        assert (
            tool_run._parse_openrouter_affordable_cap(
                "can only afford infinity"
            )
            is None
        )

    def test_extracts_first_match_if_multiple(self):
        stderr = (
            "first try: can only afford 10000\n"
            "retry: can only afford 5000\n"
        )
        assert (
            tool_run._parse_openrouter_affordable_cap(stderr) == 10000
        )

    def test_returns_none_on_none_input(self):
        assert tool_run._parse_openrouter_affordable_cap(None) is None


# ---------------------------------------------------------------------------
# _build_model_settings_override — YAML file construction
# ---------------------------------------------------------------------------


class TestBuildModelSettingsOverride:
    def test_writes_one_entry_per_configured_model(self, tmp_path):
        config = {
            "architect_model": "openrouter/anthropic/claude-sonnet-4.5",
            "editor_model": "openrouter/deepseek/deepseek-v3.2",
            "weak_model": "openrouter/deepseek/deepseek-v3.2",
        }
        path = tool_run._build_model_settings_override(
            config, cap=49423, tmp_dir=tmp_path,
        )
        data = yaml.safe_load(Path(path).read_text())
        names = sorted({entry["name"] for entry in data})
        assert names == sorted(
            {
                "openrouter/anthropic/claude-sonnet-4.5",
                "openrouter/deepseek/deepseek-v3.2",
            }
        )
        for entry in data:
            assert entry["extra_params"]["max_tokens"] == 49423

    def test_skips_unset_models(self, tmp_path):
        config = {
            "architect_model": "openrouter/anthropic/claude-sonnet-4.5",
        }
        path = tool_run._build_model_settings_override(
            config, cap=1000, tmp_dir=tmp_path,
        )
        data = yaml.safe_load(Path(path).read_text())
        assert len(data) == 1
        assert data[0]["name"] == "openrouter/anthropic/claude-sonnet-4.5"
        assert data[0]["extra_params"]["max_tokens"] == 1000

    def test_returns_none_when_no_models_configured(self, tmp_path):
        """If the config has no model names, there is nothing to override
        — aider is using its defaults and we cannot target an entry."""
        assert (
            tool_run._build_model_settings_override(
                {}, cap=1000, tmp_dir=tmp_path,
            )
            is None
        )


# ---------------------------------------------------------------------------
# run() — end-to-end: retry happens on 402, only once, under the right gates
# ---------------------------------------------------------------------------


def _stdin_data() -> dict:
    return {
        "args": {"message": "do the thing"},
        "session": "s",
        "workspace": "/tmp",
        "session_secrets": {},
        "plan_outputs": [],
    }


def _ok_result(stdout: str = "Applied changes", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["aider"], 0, stdout, stderr)


def _fail_result(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["aider"], 1, stdout, stderr)


def _env_patch():
    return patch.dict(
        "os.environ",
        {"KISO_WRAPPER_AIDER_API_KEY": "fake-key"},
    )


def _config_with_models() -> dict:
    return {
        "provider": "openrouter",
        "architect_model": "openrouter/anthropic/claude-sonnet-4.5",
        "editor_model": "openrouter/deepseek/deepseek-v3.2",
        "weak_model": "openrouter/deepseek/deepseek-v3.2",
    }


class TestRunRetryBehavior:
    def test_402_triggers_single_retry_with_override_flag(self, tmp_path, capsys):
        """First call: 402 with parseable cap. Second call: success.
        Run must invoke run_aider exactly twice, and the second call's
        cmd must include --model-settings-file pointing to a real YAML
        containing the configured model names with max_tokens = cap."""
        calls: list[list[str]] = []
        results = [
            _fail_result(stderr=_OPENROUTER_402_STDERR),
            _ok_result(stdout="Applied changes on retry"),
        ]

        def fake_run_aider(cmd, env):
            calls.append(list(cmd))
            return results.pop(0)

        with _env_patch(), \
             patch("run.load_config", return_value=_config_with_models()), \
             patch("run.run_aider", side_effect=fake_run_aider), \
             patch("pathlib.Path.exists", return_value=True):
            result = tool_run.run({"message": "hi"}, {})

        assert len(calls) == 2
        second_cmd = calls[1]
        assert "--model-settings-file" in second_cmd
        idx = second_cmd.index("--model-settings-file")
        settings_path = Path(second_cmd[idx + 1])
        assert settings_path.exists()
        data = yaml.safe_load(settings_path.read_text())
        # Every entry must carry the parsed cap
        for entry in data:
            assert entry["extra_params"]["max_tokens"] == 49423
        # Final output reflects the successful retry
        assert "retry" in result.lower() or "applied" in result.lower()

    def test_non_402_error_does_not_retry(self, tmp_path, capsys):
        """A non-OpenRouter error must NOT trigger the retry path.
        run_aider is called exactly once and the wrapper exits 1."""
        calls: list[list[str]] = []

        def fake_run_aider(cmd, env):
            calls.append(list(cmd))
            return _fail_result(stderr="generic aider crash, not 402")

        with _env_patch(), \
             patch("run.load_config", return_value=_config_with_models()), \
             patch("run.run_aider", side_effect=fake_run_aider), \
             patch("pathlib.Path.exists", return_value=True):
            with pytest.raises(SystemExit) as exc_info:
                tool_run.run({"message": "hi"}, {})

        assert exc_info.value.code == 1
        assert len(calls) == 1

    def test_402_with_unparseable_format_does_not_retry(self, tmp_path, capsys):
        """OpenRouter-like error without the 'can only afford N' phrase
        (e.g. format change or different error class) must NOT retry."""
        calls: list[list[str]] = []

        def fake_run_aider(cmd, env):
            calls.append(list(cmd))
            return _fail_result(
                stderr="OpenrouterException - different error format"
            )

        with _env_patch(), \
             patch("run.load_config", return_value=_config_with_models()), \
             patch("run.run_aider", side_effect=fake_run_aider), \
             patch("pathlib.Path.exists", return_value=True):
            with pytest.raises(SystemExit):
                tool_run.run({"message": "hi"}, {})

        assert len(calls) == 1

    def test_402_retry_also_fails_exits_with_original_error(self, tmp_path, capsys):
        """If the retry also fails, the wrapper exits 1. The retry is
        exactly ONE shot — never two retries."""
        calls: list[list[str]] = []
        results = [
            _fail_result(stderr=_OPENROUTER_402_STDERR),
            _fail_result(stderr="second attempt also failed"),
        ]

        def fake_run_aider(cmd, env):
            calls.append(list(cmd))
            return results.pop(0)

        with _env_patch(), \
             patch("run.load_config", return_value=_config_with_models()), \
             patch("run.run_aider", side_effect=fake_run_aider), \
             patch("pathlib.Path.exists", return_value=True):
            with pytest.raises(SystemExit):
                tool_run.run({"message": "hi"}, {})

        assert len(calls) == 2
        # Second call still carried the override
        assert "--model-settings-file" in calls[1]

    def test_402_without_configured_models_does_not_retry(self, tmp_path, capsys):
        """If no model names are set in config, the override YAML has
        nothing to target — the wrapper cannot safely retry without
        knowing which model entries to override. Falls through to the
        existing error path."""
        calls: list[list[str]] = []

        def fake_run_aider(cmd, env):
            calls.append(list(cmd))
            return _fail_result(stderr=_OPENROUTER_402_STDERR)

        with _env_patch(), \
             patch("run.load_config", return_value={"provider": "openrouter"}), \
             patch("run.run_aider", side_effect=fake_run_aider), \
             patch("pathlib.Path.exists", return_value=True):
            with pytest.raises(SystemExit):
                tool_run.run({"message": "hi"}, {})

        assert len(calls) == 1

    def test_successful_first_call_does_not_retry(self, tmp_path, capsys):
        """Happy path is untouched: a successful first call returns
        directly without any retry logic firing."""
        calls: list[list[str]] = []

        def fake_run_aider(cmd, env):
            calls.append(list(cmd))
            return _ok_result(stdout="Applied changes immediately")

        with _env_patch(), \
             patch("run.load_config", return_value=_config_with_models()), \
             patch("run.run_aider", side_effect=fake_run_aider), \
             patch("pathlib.Path.exists", return_value=True):
            result = tool_run.run({"message": "hi"}, {})

        assert len(calls) == 1
        assert "Applied" in result
        # Successful first call must NOT carry a settings-file override
        assert "--model-settings-file" not in calls[0]

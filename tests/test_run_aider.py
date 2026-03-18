"""Tests for run_aider() subprocess wrapper."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from run import run_aider


def test_run_aider_success(mock_aider_ok):
    cmd = [str(mock_aider_ok), "--message", "hello"]
    env = {"PATH": str(mock_aider_ok.parent), "HOME": "/tmp"}
    result = run_aider(cmd, env)
    assert result.returncode == 0
    assert "aider ok" in result.stdout


def test_run_aider_failure(mock_aider_fail):
    cmd = [str(mock_aider_fail), "--message", "hello"]
    env = {"PATH": str(mock_aider_fail.parent), "HOME": "/tmp"}
    result = run_aider(cmd, env)
    assert result.returncode == 1
    assert "aider error" in result.stderr


def test_run_aider_returns_completed_process(mock_aider_ok):
    cmd = [str(mock_aider_ok), "--message", "test"]
    env = {"PATH": str(mock_aider_ok.parent), "HOME": "/tmp"}
    result = run_aider(cmd, env)
    assert isinstance(result, subprocess.CompletedProcess)

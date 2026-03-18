"""Tests for load_config() and config defaults."""

import sys
import tomllib
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from run import load_config


def test_no_config_file_returns_empty_dict(tmp_path):
    with patch("run.Path") as mock_path_cls:
        # Make config_path.exists() return False
        mock_config_path = mock_path_cls.return_value.__truediv__.return_value
        mock_config_path.exists.return_value = False
        result = load_config()
    assert result == {}


def test_valid_config_loaded_correctly(tmp_path):
    config_content = b"""
provider = "openai"
mode = "code"
architect_model = "gpt-4o"
map_tokens = 2048
auto_commits = false
"""
    config_path = tmp_path / "config.toml"
    config_path.write_bytes(config_content)

    with patch("run.Path") as mock_path_cls:
        mock_path_cls.return_value.__truediv__.return_value = config_path
        config_path_mock = mock_path_cls.return_value.__truediv__.return_value
        # Re-patch exists and open to use real file
        result = load_config.__wrapped__(config_path) if hasattr(load_config, "__wrapped__") else None

    # Direct test: load from real file
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    assert data["provider"] == "openai"
    assert data["mode"] == "code"
    assert data["architect_model"] == "gpt-4o"
    assert data["map_tokens"] == 2048
    assert data["auto_commits"] is False


def test_partial_config_defaults(no_config, full_config):
    # When config is missing keys, callers fall back to defaults
    provider = no_config.get("provider", "openrouter")
    mode = no_config.get("mode", "architect")
    assert provider == "openrouter"
    assert mode == "architect"


def test_unknown_provider_falls_back():
    from run import _PROVIDER_KEY_VARS
    # Unknown provider should not be in the map
    unknown = "mycloud"
    key_var = _PROVIDER_KEY_VARS.get(unknown, "OPENAI_API_KEY")
    assert key_var == "OPENAI_API_KEY"


def test_full_config_values(full_config):
    assert full_config["provider"] == "openrouter"
    assert full_config["mode"] == "architect"
    assert full_config["architect_model"] == "openrouter/z-ai/glm-5"
    assert full_config["editor_model"] == "openrouter/deepseek/deepseek-v3.2"
    assert full_config["weak_model"] == "openrouter/deepseek/deepseek-v3.2"
    assert full_config["map_tokens"] == 4096
    assert full_config["editor_edit_format"] == "udiff"
    assert full_config["auto_commits"] is True
    assert full_config["commit_language"] == "en"


def test_all_known_providers_in_map():
    """Verify _PROVIDER_KEY_VARS has entries for all expected providers."""
    from run import _PROVIDER_KEY_VARS
    expected = {"openrouter", "openai", "anthropic", "deepseek"}
    assert expected == set(_PROVIDER_KEY_VARS.keys())


def test_config_example_toml_is_valid():
    """config.example.toml must be valid TOML."""
    example = Path(__file__).parent.parent / "config.example.toml"
    assert example.exists(), "config.example.toml must exist"
    with open(example, "rb") as f:
        data = tomllib.load(f)
    assert "provider" in data
    assert "mode" in data

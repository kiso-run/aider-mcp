"""Tests for kiso.toml manifest consistency."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
KISO_TOML = ROOT / "kiso.toml"
RUN_PY = ROOT / "run.py"


def test_kiso_toml_is_valid():
    with open(KISO_TOML, "rb") as f:
        data = tomllib.load(f)
    assert data["kiso"]["type"] == "wrapper"
    assert data["kiso"]["name"] == "aider"
    assert "version" in data["kiso"]
    assert "summary" in data["kiso"]["wrapper"]


def test_all_declared_args_used_in_code():
    with open(KISO_TOML, "rb") as f:
        data = tomllib.load(f)
    args = data["kiso"]["wrapper"]["args"]
    source = RUN_PY.read_text()
    for arg_name in args:
        assert arg_name in source, f"Declared arg '{arg_name}' not found in run.py"


def test_required_sections_exist():
    with open(KISO_TOML, "rb") as f:
        data = tomllib.load(f)
    assert "kiso" in data
    assert "wrapper" in data["kiso"]
    assert "args" in data["kiso"]["wrapper"]

import json
import os
import pwd
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import tomllib


# Map provider name → env var that aider/litellm expects
_PROVIDER_KEY_VARS = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


# Regex for the OpenRouter 402 per-request affordable-cap error.
# OpenRouter enforces max_tokens_per_request ≤ balance/per_token_cost
# and reports the affordable ceiling in the error text. When aider
# requests the full model max (typically 64k for high-max models)
# and the balance does not cover it, OpenRouter rejects with:
#   "You requested up to X tokens, but can only afford Y"
# The wrapper parses Y to retry once with max_tokens capped to Y.
_AFFORDABLE_CAP_RE = re.compile(r"can only afford (\d+)")


# Model-name keys in config.toml that identify which aider model
# entries need a per-run max_tokens override when the affordable-cap
# retry fires.
_CONFIG_MODEL_KEYS = ("architect_model", "editor_model", "weak_model")


def run(args: dict, context: dict) -> str:
    config = load_config()
    provider = config.get("provider", "openrouter")
    mode = args.get("mode", config.get("mode", "architect"))

    # Validate mode
    if mode not in ("architect", "code", "ask"):
        print(f"Aider failed: unknown mode '{mode}'")
        sys.exit(1)

    # Get API key — prefer tool-specific, fall back to kiso's shared LLM key
    api_key = os.environ.get("KISO_WRAPPER_AIDER_API_KEY") or os.environ.get("KISO_LLM_API_KEY", "")
    if not api_key:
        print("No API key found. Set KISO_WRAPPER_AIDER_API_KEY or KISO_LLM_API_KEY.", file=sys.stderr)
        print("Aider failed: API key not configured.")
        sys.exit(1)

    # Check aider binary exists
    aider_bin = str(Path(sys.executable).parent / "aider")
    if not Path(aider_bin).exists():
        print("Aider failed: aider binary not found.")
        sys.exit(1)

    cmd = build_command(args, config, mode)
    env = build_env(api_key, provider, config)

    # Build header
    files = parse_file_list(args.get("files", ""))
    read_only = parse_file_list(args.get("read_only_files", ""))
    parts = [f"Mode: {mode}"]
    if files:
        parts.append(f"Files: {', '.join(files)}")
    if read_only:
        parts.append(f"Read-only: {', '.join(read_only)}")
    parts.append("")  # blank line after header

    result = run_aider(cmd, env)

    # If aider hit the OpenRouter per-request affordable-cap error,
    # retry ONCE with a model-settings file that caps max_tokens to
    # the affordable ceiling the provider reported. The cap value
    # comes from the provider, not from a hard-coded constant, so
    # this respects the project policy against artificial caps.
    if result.returncode != 0:
        cap = _parse_openrouter_affordable_cap(result.stderr)
        if cap is not None:
            override_path = _build_model_settings_override(
                config, cap=cap, tmp_dir=None,
            )
            if override_path is not None:
                retry_cmd = cmd + ["--model-settings-file", override_path]
                result = run_aider(retry_cmd, env)

    output = strip_ansi(result.stdout)
    if output.strip():
        parts.append(output)

    if result.returncode != 0:
        print(f"aider exited with code {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if not output.strip():
            parts.append("Aider failed: see stderr for details.")
        print("\n".join(parts))
        sys.exit(1)

    return "\n".join(parts)


def _parse_openrouter_affordable_cap(stderr: str | None) -> int | None:
    """Parse the affordable-tokens ceiling from an OpenRouter 402 error.

    Returns the integer N from the phrase "can only afford N" in
    *stderr*, or None if the phrase is absent / malformed / stderr
    is empty. The first match wins when multiple occurrences exist.
    The parser is intentionally narrow: it only fires on this
    specific OpenRouter error shape, so any other failure mode
    (including a format change on OpenRouter's side) is silently a
    no-op and falls through to the existing error path with no
    regression.
    """
    if not stderr:
        return None
    match = _AFFORDABLE_CAP_RE.search(stderr)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _build_model_settings_override(
    config: dict,
    cap: int,
    tmp_dir: Path | None,
) -> str | None:
    """Write a temporary aider model-settings YAML that caps max_tokens.

    Aider's ``register_models`` fully replaces any existing entry for
    a model name it already knows, so the override file must stand
    on its own. It contains one entry per configured model name
    (architect/editor/weak), each with ``extra_params.max_tokens``
    set to *cap*. The returned path can be passed to aider via
    ``--model-settings-file``.

    Returns None when no model names are configured — in that case
    aider is using its own defaults and we cannot target specific
    entries, so retrying would not change the outcome.
    """
    seen: set[str] = set()
    entries: list[dict] = []
    for key in _CONFIG_MODEL_KEYS:
        name = config.get(key)
        if not name or name in seen:
            continue
        seen.add(name)
        entries.append({
            "name": name,
            "extra_params": {"max_tokens": cap},
        })
    if not entries:
        return None

    # Minimal hand-written YAML so the wrapper stays dependency-free.
    # Aider loads this with yaml.safe_load, which accepts this shape.
    lines: list[str] = []
    for entry in entries:
        lines.append(f"- name: {entry['name']}")
        lines.append("  extra_params:")
        lines.append(f"    max_tokens: {entry['extra_params']['max_tokens']}")
    content = "\n".join(lines) + "\n"

    fd, path = tempfile.mkstemp(
        prefix="aider-cap-",
        suffix=".yml",
        dir=str(tmp_dir) if tmp_dir is not None else None,
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except Exception:
        os.unlink(path)
        raise
    return path


def load_config() -> dict:
    """Load config.toml from the tool directory (where run.py lives)."""
    config_path = Path(__file__).parent / "config.toml"
    if not config_path.exists():
        return {}
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def parse_file_list(value: str) -> list[str]:
    """Split comma-separated file list, strip whitespace, filter empty."""
    if not value:
        return []
    return [f.strip() for f in value.split(",") if f.strip()]


def build_command(args: dict, config: dict, mode: str) -> list[str]:
    """Build the aider CLI command."""
    aider_bin = str(Path(sys.executable).parent / "aider")
    cmd = [aider_bin]

    # Message (required)
    cmd.extend(["--message", args["message"]])

    # Mode
    if mode == "architect":
        cmd.append("--architect")
    elif mode == "ask":
        cmd.append("--ask")
    # "code" is aider's default — no flag needed

    # Models
    if config.get("architect_model"):
        cmd.extend(["--model", config["architect_model"]])
    if config.get("editor_model"):
        cmd.extend(["--editor-model", config["editor_model"]])
    if config.get("weak_model"):
        cmd.extend(["--weak-model", config["weak_model"]])

    # Settings
    if config.get("map_tokens"):
        cmd.extend(["--map-tokens", str(config["map_tokens"])])
    if config.get("editor_edit_format"):
        cmd.extend(["--editor-edit-format", config["editor_edit_format"]])
    if config.get("commit_language"):
        cmd.extend(["--commit-language", config["commit_language"]])

    # Auto-commits
    if config.get("auto_commits", True):
        cmd.append("--auto-commits")
    else:
        cmd.append("--no-auto-commits")

    # Non-interactive flags
    cmd.extend([
        "--yes",
        "--no-pretty",
        "--no-fancy-input",
        "--no-suggest-shell-commands",
    ])

    # Custom API base
    if config.get("api_base"):
        cmd.extend(["--openai-api-base", config["api_base"]])

    # Files to edit (positional args)
    files = parse_file_list(args.get("files", ""))
    cmd.extend(files)

    # Read-only files
    read_only = parse_file_list(args.get("read_only_files", ""))
    for f in read_only:
        cmd.extend(["--read", f])

    return cmd


def build_env(api_key: str, provider: str, config: dict) -> dict[str, str]:
    """Build environment for the aider subprocess.

    The tool subprocess gets a clean env from kiso (only PATH + KISO_WRAPPER_AIDER_API_KEY).
    Aider needs more: HOME (for git), and the provider-specific API key env var.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": pwd.getpwuid(os.getuid()).pw_dir,
    }

    # Map KISO_WRAPPER_AIDER_API_KEY → provider's expected env var
    key_var = _PROVIDER_KEY_VARS.get(provider, "OPENAI_API_KEY")
    env[key_var] = api_key

    # Custom base URL
    if config.get("api_base"):
        env["OPENAI_API_BASE"] = config["api_base"]

    return env


def run_aider(cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run aider subprocess, forwarding SIGTERM for graceful shutdown."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )

    # Forward SIGTERM to child so it can clean up
    def handle_sigterm(signum, frame):
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)

    stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return _ANSI_RE.sub("", text)


if __name__ == "__main__":
    data = json.load(sys.stdin)
    result = run(data["args"], data)
    print(result)

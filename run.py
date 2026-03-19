import json
import os
import pwd
import re
import signal
import subprocess
import sys
from pathlib import Path

import tomllib


# Map provider name → env var that aider/litellm expects
_PROVIDER_KEY_VARS = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def run(args: dict, context: dict) -> str:
    config = load_config()
    provider = config.get("provider", "openrouter")
    mode = args.get("mode", config.get("mode", "architect"))

    # Validate mode
    if mode not in ("architect", "code", "ask"):
        print(f"Aider failed: unknown mode '{mode}'")
        sys.exit(1)

    # Get API key
    api_key = os.environ.get("KISO_TOOL_AIDER_API_KEY", "")
    if not api_key:
        print("KISO_TOOL_AIDER_API_KEY is not set", file=sys.stderr)
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

    The tool subprocess gets a clean env from kiso (only PATH + KISO_TOOL_AIDER_API_KEY).
    Aider needs more: HOME (for git), and the provider-specific API key env var.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": pwd.getpwuid(os.getuid()).pw_dir,
    }

    # Map KISO_TOOL_AIDER_API_KEY → provider's expected env var
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

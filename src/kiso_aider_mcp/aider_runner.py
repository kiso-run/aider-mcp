"""Subprocess wrapper around the `aider` CLI.

Invoked by the MCP tool surface in :mod:`kiso_aider_mcp.server`. Kept in its
own module so the MCP transport layer stays a thin adapter.

Key contract:

- ``run_aider_codegen`` runs aider with ``--no-auto-commits`` and captures the
  resulting ``git diff`` from the workspace. The caller owns staging/committing.
- OpenRouter 402 ``can only afford N`` errors trigger one retry with
  ``--model-settings-file`` capping ``max_tokens`` to N.
- The only API key read from the environment is ``OPENROUTER_API_KEY`` (single-key
  invariant for the default preset).
"""
from __future__ import annotations

import os
import pwd
import re
import signal
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path


_VALID_MODES = ("architect", "code", "ask")
_AFFORDABLE_CAP_RE = re.compile(r"can only afford (\d+)")


def build_command(
    *,
    prompt: str,
    editable_files: list[str] | None = None,
    readonly_files: list[str] | None = None,
    architect_model: str | None = None,
    editor_model: str | None = None,
    model: str | None = None,
    mode: str = "architect",
) -> list[str]:
    if not prompt or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    if mode not in _VALID_MODES:
        raise ValueError(f"unknown mode: {mode!r}; expected one of {_VALID_MODES}")

    # `model` is the legacy alias of `architect_model`. Explicit
    # `architect_model` always wins; bare `model` triggers a
    # deprecation warning so callers know to migrate.
    if model is not None:
        warnings.warn(
            "`model` is deprecated; use `architect_model` instead.",
            DeprecationWarning, stacklevel=2,
        )
        if architect_model is None:
            architect_model = model

    cmd: list[str] = [_aider_binary_path(), "--message", prompt]

    if mode == "architect":
        cmd.append("--architect")
    elif mode == "ask":
        cmd.append("--ask")
    # "code" is aider's default — no flag needed.

    if architect_model:
        cmd.extend(["--model", architect_model])

    # editor_model is only meaningful in architect mode (aider's two-model
    # flow). Drop it silently in code/ask to avoid passing a useless flag.
    if editor_model and mode == "architect":
        cmd.extend(["--editor-model", editor_model])

    cmd.extend([
        "--yes",
        "--no-pretty",
        "--no-fancy-input",
        "--no-suggest-shell-commands",
        "--no-auto-commits",
    ])

    for f in readonly_files or []:
        cmd.extend(["--read", f])

    cmd.extend(editable_files or [])

    return cmd


def build_env() -> dict[str, str]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set — required to authenticate with OpenRouter."
        )
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": pwd.getpwuid(os.getuid()).pw_dir,
        "OPENROUTER_API_KEY": api_key,
    }


def run_aider_codegen(
    *,
    prompt: str,
    editable_files: list[str] | None = None,
    readonly_files: list[str] | None = None,
    architect_model: str | None = None,
    editor_model: str | None = None,
    model: str | None = None,
    mode: str = "architect",
    workspace: str | None = None,
) -> dict:
    ws = Path(workspace) if workspace else Path.cwd()

    if not _aider_binary_exists():
        return _fail("aider binary not found — install with `pip install aider-chat`")

    try:
        env = build_env()
    except RuntimeError as exc:
        return _fail(str(exc))

    try:
        cmd = build_command(
            prompt=prompt,
            editable_files=editable_files,
            readonly_files=readonly_files,
            architect_model=architect_model,
            editor_model=editor_model,
            model=model,
            mode=mode,
        )
    except ValueError as exc:
        return _fail(str(exc))

    result = _run_aider(cmd, env, ws)

    if result.returncode != 0:
        cap = _parse_openrouter_affordable_cap(result.stderr)
        # Affordable-cap retry targets the model that aider actually used.
        # `architect_model` is what we passed via `--model`; legacy `model`
        # is the same value at this point.
        cap_target = architect_model or model
        if cap is not None and cap_target:
            override = _build_model_settings_override(model=cap_target, cap=cap)
            if override is not None:
                retry_cmd = cmd + ["--model-settings-file", override]
                result = _run_aider(retry_cmd, env, ws)

    diff = _capture_diff(str(ws))
    success = result.returncode == 0
    return {
        "success": success,
        "diff": diff,
        "output": _strip_ansi(result.stdout or ""),
        "stderr": (result.stderr or "") if not success else "",
    }


def check_health() -> dict:
    issues: list[str] = []
    version: str | None = None

    if _aider_binary_exists():
        version = _aider_version()
    else:
        issues.append("aider binary not found — install with `pip install aider-chat`")

    if not os.environ.get("OPENROUTER_API_KEY"):
        issues.append("OPENROUTER_API_KEY is not set")

    return {
        "healthy": not issues,
        "issues": issues,
        "version": version,
    }


def _aider_binary_path() -> str:
    return str(Path(sys.executable).parent / "aider")


def _aider_binary_exists() -> bool:
    return Path(_aider_binary_path()).exists()


def _aider_version() -> str | None:
    try:
        result = subprocess.run(
            [_aider_binary_path(), "--version"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (result.stdout or result.stderr or "").strip()
    return out.splitlines()[0] if out else None


def _run_aider(
    cmd: list[str], env: dict[str, str], workspace: Path,
) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        cwd=str(workspace),
    )

    def _forward_sigterm(signum, frame):
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    previous = signal.signal(signal.SIGTERM, _forward_sigterm)
    try:
        stdout, stderr = proc.communicate()
    finally:
        signal.signal(signal.SIGTERM, previous)
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def _capture_diff(workspace: str) -> str:
    try:
        result = subprocess.run(
            ["git", "diff"],
            capture_output=True, text=True, cwd=workspace, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _parse_openrouter_affordable_cap(stderr: str | None) -> int | None:
    if not stderr:
        return None
    match = _AFFORDABLE_CAP_RE.search(stderr)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _build_model_settings_override(*, model: str, cap: int) -> str | None:
    content = (
        f"- name: {model}\n"
        f"  extra_params:\n"
        f"    max_tokens: {cap}\n"
    )
    fd, path = tempfile.mkstemp(prefix="aider-cap-", suffix=".yml")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except Exception:
        os.unlink(path)
        raise
    return path


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _fail(message: str) -> dict:
    return {"success": False, "diff": "", "output": "", "stderr": message}

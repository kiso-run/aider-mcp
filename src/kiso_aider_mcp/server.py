"""MCP server exposing aider codegen as a tool.

Run via the console script ``kiso-aider-mcp`` (registered in ``pyproject.toml``)
or ``python -m kiso_aider_mcp.server``.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import aider_runner


mcp = FastMCP("kiso-aider")


@mcp.tool()
def aider_codegen(
    prompt: str,
    editable_files: list[str] | None = None,
    readonly_files: list[str] | None = None,
    model: str | None = None,
    mode: str = "architect",
) -> dict:
    """Edit code with aider and return the resulting git diff.

    aider runs with ``--no-auto-commits`` so the caller owns staging and
    committing. OpenRouter is the LLM backend; set ``OPENROUTER_API_KEY``
    in the server environment.

    Args:
        prompt: Instruction for aider — what should change and why.
        editable_files: File paths aider may edit (relative to the server cwd).
        readonly_files: File paths aider may read but not modify.
        model: LLM override, e.g. ``openrouter/anthropic/claude-sonnet-4.6``.
            Defaults to aider's own defaults when omitted.
        mode: ``"architect"`` (default; planner + editor), ``"code"``
            (single-model direct edits), or ``"ask"`` (read-only Q&A).

    Returns:
        ``{"success": bool, "diff": str, "output": str, "stderr": str}``.
    """
    return aider_runner.run_aider_codegen(
        prompt=prompt,
        editable_files=editable_files,
        readonly_files=readonly_files,
        model=model,
        mode=mode,
    )


@mcp.tool()
def doctor() -> dict:
    """Check aider binary and OpenRouter credentials.

    Returns:
        ``{"healthy": bool, "issues": [str], "version": str | None}``.
    """
    return aider_runner.check_health()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

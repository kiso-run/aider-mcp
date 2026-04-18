"""Tests for the MCP tool surface exposed by kiso_aider_mcp.server."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest


def _decode(result) -> dict:
    """Extract the JSON payload from a FastMCP call_tool result."""
    # call_tool returns a list[ContentBlock]; the first block is the
    # serialized tool return value as TextContent.
    blocks = result if isinstance(result, list) else list(result)
    return json.loads(blocks[0].text)


def test_mcp_instance_exists_and_is_named():
    from kiso_aider_mcp import server
    assert server.mcp.name == "kiso-aider"


async def test_aider_codegen_tool_is_registered():
    from kiso_aider_mcp import server
    tools = await server.mcp.list_tools()
    names = [t.name for t in tools]
    assert "aider_codegen" in names


async def test_doctor_tool_is_registered():
    from kiso_aider_mcp import server
    tools = await server.mcp.list_tools()
    names = [t.name for t in tools]
    assert "doctor" in names


async def test_aider_codegen_description_mentions_code_editing():
    from kiso_aider_mcp import server
    tools = await server.mcp.list_tools()
    codegen = next(t for t in tools if t.name == "aider_codegen")
    desc = (codegen.description or "").lower()
    assert "aider" in desc
    assert any(word in desc for word in ("edit", "code", "refactor"))


async def test_aider_codegen_schema_declares_prompt_required():
    from kiso_aider_mcp import server
    tools = await server.mcp.list_tools()
    codegen = next(t for t in tools if t.name == "aider_codegen")
    schema = codegen.inputSchema
    assert "prompt" in schema.get("properties", {})
    assert "prompt" in schema.get("required", [])


async def test_aider_codegen_delegates_to_runner():
    from kiso_aider_mcp import server
    stub = {"success": True, "diff": "+x", "output": "ok", "stderr": ""}
    with patch(
        "kiso_aider_mcp.server.aider_runner.run_aider_codegen", return_value=stub,
    ) as run:
        result = await server.mcp.call_tool(
            "aider_codegen",
            {
                "prompt": "fix race",
                "editable_files": ["a.py"],
                "readonly_files": ["b.md"],
                "model": "openrouter/x",
                "mode": "code",
            },
        )
    run.assert_called_once_with(
        prompt="fix race",
        editable_files=["a.py"],
        readonly_files=["b.md"],
        model="openrouter/x",
        mode="code",
    )
    assert _decode(result) == stub


async def test_doctor_delegates_to_runner():
    from kiso_aider_mcp import server
    stub = {"healthy": True, "issues": [], "version": "0.82.0"}
    with patch(
        "kiso_aider_mcp.server.aider_runner.check_health", return_value=stub,
    ) as health:
        result = await server.mcp.call_tool("doctor", {})
    health.assert_called_once_with()
    assert _decode(result) == stub


def test_main_entry_point_exists_and_calls_run():
    from kiso_aider_mcp import server
    with patch.object(server.mcp, "run") as run:
        server.main()
    run.assert_called_once()

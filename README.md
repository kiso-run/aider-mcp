# kiso-aider-mcp

[aider](https://aider.chat) codegen exposed as a
[Model Context Protocol](https://modelcontextprotocol.io) server.

Runs aider as a subprocess against the configured workspace and returns
a structured `{success, diff, output, stderr}` payload. The caller owns
staging and committing — aider runs with `--no-auto-commits`.

Part of the [`kiso-run`](https://github.com/kiso-run) project. Works
with any MCP client; consumed in particular by
[`kiso-run/core`](https://github.com/kiso-run/core).

## Install

No PyPI publishing. Consume directly from GitHub via `uvx`:

```sh
uvx --from git+https://github.com/kiso-run/aider-mcp@v0.1.0 kiso-aider-mcp
```

`uv` caches the clone; pin to a tag (`v0.1.0`, `v0.2.0`, …) for
reproducibility.

## Required environment

| Variable              | Required | Purpose                                  |
|-----------------------|----------|------------------------------------------|
| `OPENROUTER_API_KEY`  | yes      | aider backend via OpenRouter             |

Single-key by design: OpenRouter fronts every supported LLM provider.
No fallback to raw OpenAI / Anthropic / DeepSeek env vars — the
single-key invariant is documented in the `kiso-run/core` v0.10
devplan.

## MCP client config

Minimal entry for an MCP client (`mcp.json` shape):

```json
{
  "mcpServers": {
    "aider": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/kiso-run/aider-mcp@v0.1.0",
        "kiso-aider-mcp"
      ],
      "env": { "OPENROUTER_API_KEY": "${env:OPENROUTER_API_KEY}" }
    }
  }
}
```

## Tools

### `aider_codegen`

Edit code with aider and return the resulting git diff.

| Parameter         | Type           | Default       | Notes                                            |
|-------------------|----------------|---------------|--------------------------------------------------|
| `prompt`          | string         | required      | Instruction for aider                            |
| `editable_files`  | list[string]   | `[]`          | Files aider may modify                           |
| `readonly_files`  | list[string]   | `[]`          | Files aider may read but not modify              |
| `architect_model` | string         | aider default | Architect (planner) LLM, e.g. `openrouter/anthropic/claude-sonnet-4.6`. Passed as `--model`. |
| `editor_model`    | string         | aider default | Editor LLM in architect mode. Passed as `--editor-model`. Ignored in `code`/`ask`. |
| `model`           | string         | —             | **Deprecated** alias of `architect_model`. If both set, `architect_model` wins. |
| `mode`            | string         | `"architect"` | `"architect"`, `"code"`, or `"ask"`              |

**Kiso integration**. When invoked from a Kiso runtime, `architect_model`
defaults to `MODEL_DEFAULTS["planner"]` and `editor_model` defaults to
`MODEL_DEFAULTS["worker"]`. The server itself never auto-selects a
model — Kiso's runtime injects the defaults pre-call. Standalone or
non-Kiso clients get aider's bundled defaults instead.

Returns:

```json
{
  "success": true,
  "diff":    "--- a/foo.py\n+++ b/foo.py\n@@ ...",
  "output":  "aider stdout (ANSI-stripped)",
  "stderr":  ""
}
```

The diff is captured with `git diff` in the server's working directory
after aider finishes. `--no-auto-commits` is always forced, so the
changes live in the working tree until the caller stages/commits them.

### `doctor`

Health check. Returns:

```json
{
  "healthy": true,
  "issues":  [],
  "version": "aider 0.86.2"
}
```

`healthy` is `false` if the `aider` binary is missing or
`OPENROUTER_API_KEY` is not set; `issues` enumerates each.

## Modes

| Mode          | When to use                                                  |
|---------------|--------------------------------------------------------------|
| `architect`   | Complex edits. Planner model designs, editor model applies   |
| `code`        | Direct single-model edits; faster, cheaper                   |
| `ask`         | Read-only Q&A about code; aider makes no changes             |

## Reliability

- **OpenRouter affordable-cap retry**: when OpenRouter returns a 402
  with `can only afford N tokens`, the server retries once with
  `--model-settings-file` capping `max_tokens` to `N`. No extra knobs
  to configure.

## Development

```sh
# Install deps
uv sync

# Unit tests (no network)
uv run pytest tests/ -q

# Include the live test (real aider + OpenRouter round-trip)
OPENROUTER_API_KEY=sk-... uv run pytest tests/ -q -m live
```

## License

MIT (see `LICENSE`).

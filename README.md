# tool-aider

Code editing tool for [kiso](https://github.com/kiso-run/core), powered by [aider](https://aider.chat). Supports any LLM backend via OpenRouter, OpenAI, Anthropic, DeepSeek, or a custom endpoint.

## Installation

```sh
kiso tool install aider
```

This clones the repo to `~/.kiso/tools/aider/`, runs `uv sync`, and copies `config.example.toml` → `config.toml`.

## Configuration

### API key

If `KISO_LLM_API_KEY` is already set (the shared kiso LLM key), aider uses it automatically -- no extra configuration needed.

To use a separate key for aider (overrides the shared key):

```sh
kiso env set KISO_TOOL_AIDER_API_KEY "<aider-specific-key>"
kiso env reload
```

### Config file

Edit `~/.kiso/tools/aider/config.toml` to set the provider, models, and mode. The defaults use OpenRouter with architect mode (GLM-5 as architect, DeepSeek v3.2 as editor).

## Supported providers

| Provider | Config value | Env var set by run.py |
|---|---|---|
| OpenRouter (default) | `openrouter` | `OPENROUTER_API_KEY` |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` |
| Custom endpoint | any + `api_base` | `OPENAI_API_KEY` + `OPENAI_API_BASE` |

## Modes

| Mode | Description |
|---|---|
| **architect** (default) | Two models: architect plans changes, editor applies them |
| **code** | Single model edits files directly |
| **ask** | Read-only — answers questions about code without making changes |

## How it works

1. The kiso planner decides to use the `aider` tool and provides a message and file list
2. `run.py` is invoked as a subprocess with JSON on stdin
3. aider edits files in the session workspace and commits the changes
4. The output (aider's response) is returned to the kiso reviewer

## Args reference

| Arg | Required | Description |
|---|---|---|
| `message` | yes | Instruction or question for aider |
| `files` | no | Comma-separated file paths to edit |
| `mode` | no | `architect` (default), `code`, or `ask` |
| `read_only_files` | no | Comma-separated files for read-only context |

## Config reference

| Key | Default | Description |
|---|---|---|
| `provider` | `openrouter` | LLM provider (`openrouter`, `openai`, `anthropic`, `deepseek`) |
| `api_base` | — | Custom base URL for self-hosted or proxy endpoints |
| `mode` | `architect` | Default mode when not specified in args |
| `architect_model` | `openrouter/z-ai/glm-5` | Model for the architect role |
| `editor_model` | `openrouter/deepseek/deepseek-v3.2` | Model for the editor role |
| `weak_model` | `openrouter/deepseek/deepseek-v3.2` | Weak/cheap model for minor tasks |
| `map_tokens` | `4096` | Token budget for the repo map |
| `editor_edit_format` | `udiff` | Edit format used by the editor model in architect mode |
| `auto_commits` | `true` | Whether aider commits changes automatically |
| `commit_language` | `en` | Language for commit messages |

## Development

```sh
uv run --group dev pytest tests/ -v
```

## License

MIT

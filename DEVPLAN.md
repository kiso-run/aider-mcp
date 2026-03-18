# tool-aider — Dev Plan

## Overview

Code editing tool for kiso that wraps [aider](https://aider.chat/) as a subprocess.
Provides architect, code, and ask modes for LLM-driven code changes within kiso sessions.

## Architecture

- **`run.py`** — Single-file tool implementation
  - `run(args, context)` — Entry point; validates inputs, builds command/env, invokes aider, formats output
  - `load_config()` — Reads `config.toml` from tool directory
  - `build_command(args, config, mode)` — Constructs aider CLI arguments
  - `build_env(api_key, provider, config)` — Builds clean subprocess environment with provider-specific API key mapping
  - `run_aider(cmd, env)` — Runs aider subprocess with SIGTERM forwarding
  - `parse_file_list(value)` — Splits comma-separated file lists
  - `strip_ansi(text)` — Removes ANSI escape codes from output

## Capabilities

- Three editing modes: `architect` (plan + edit), `code` (direct edit), `ask` (read-only Q&A)
- Provider support: OpenRouter, OpenAI, Anthropic, DeepSeek (API key mapping via `_PROVIDER_KEY_VARS`)
- Configurable models (architect, editor, weak), map tokens, edit format, commit language
- Auto-commit toggle, read-only file support
- SIGTERM forwarding for graceful subprocess shutdown

## Milestones

### M1 — Core implementation ✅
- [x] `run()` entry point with mode validation, API key check, binary check
- [x] `build_command()` with all aider CLI flags
- [x] `build_env()` with provider key mapping
- [x] `run_aider()` with Popen + SIGTERM forwarding
- [x] `parse_file_list()` and `strip_ansi()` helpers

### M2 — Config + provider support ✅
- [x] `load_config()` from `config.toml`
- [x] Provider fallback (unknown provider → OPENAI_API_KEY)
- [x] `config.example.toml` with documented settings

### M3 — Test suite ✅
- [x] `test_run.py` — unit tests (invalid mode, missing key, missing binary, success, failure) + integration contract tests
- [x] `test_command.py` — `build_command()` comprehensive tests
- [x] `test_config.py` — `load_config()` tests, provider fallback
- [x] `test_env.py` — `build_env()` tests (all providers, HOME, PATH, api_base)
- [x] `test_output.py` — `strip_ansi()`, `parse_file_list()`, header formatting
- [x] `conftest.py` — shared fixtures (configs, stdin data, mock aider binaries, run_tool helper)

### M4 — Complete test coverage ✅
- [x] `test_run.py`: `test_aider_failure_with_output_shows_output` — failure with stdout shows output
- [x] `test_run.py`: `test_success_code_mode_header` — verify "Mode: code" in output
- [x] `test_run_aider.py`: `run_aider()` unit tests — success, failure, CompletedProcess type
- [x] `test_config.py`: `test_all_known_providers_in_map` — verify all providers in `_PROVIDER_KEY_VARS`

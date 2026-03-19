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

### M5 — Functional tests (subprocess contract) ✅

**Problem:** `test_run.py` has 3 integration tests via subprocess but they
only test error paths (missing API key, invalid mode, non-empty stdout).
No test exercises a **successful end-to-end flow**: JSON stdin → `run()` →
aider subprocess (mocked) → formatted stdout + exit 0. The `run_tool`
helper and `mock_aider_ok` fixture exist in conftest but are barely used.

**Files:** `tests/test_functional.py` (new)

**Change:**

1. **Happy path — architect mode:**
   - stdin: full data with message + files
   - Mock aider binary (mock_aider_ok) prints `"Applied changes to auth.py"`
   - Assert: stdout contains `Mode: architect`, `Files:`, and `Applied changes`
   - Assert: exit code 0

2. **Happy path — code mode:**
   - stdin: message only, mode=code
   - Assert: stdout contains `Mode: code`, exit code 0

3. **Happy path — ask mode with read-only files:**
   - stdin: message + read_only_files, mode=ask
   - Assert: stdout contains `Mode: ask`, `Read-only:`, exit code 0

4. **Error — aider binary fails:**
   - Use `mock_aider_fail` fixture (exits 1, stderr)
   - Assert: exit code 1, stdout still contains header

5. **Error — missing API key (no env var):**
   - Don't set `KISO_TOOL_AIDER_API_KEY`
   - Assert: stdout contains `API key`, exit code 1

6. **Error — invalid mode:**
   - stdin: mode="destroy"
   - Assert: stdout contains `unknown mode`, exit code 1

7. **Error — aider binary not found:**
   - Set PATH to empty (no aider binary)
   - Assert: stdout contains `not found`, exit code 1

8. **Malformed input — invalid JSON:**
   - Send `"not json"` on stdin
   - Assert: exit code 1

9. **Malformed input — missing message key:**
   - stdin: `{args: {}, ...}` (no `message`)
   - Assert: exit code 1 (KeyError)

10. **ANSI stripping in output:**
    - Mock aider prints ANSI escape codes
    - Assert: stdout does NOT contain escape sequences

- [x] Implement all 10 functional tests using `run_tool` helper + mock aider fixtures
- [x] All tests pass (unit + functional)

---

### M6 — SIGTERM graceful shutdown test ✅

**Problem:** `run_aider()` registers a SIGTERM handler that forwards the
signal to the aider child process. No test verifies this behavior:
- Parent receives SIGTERM → child gets SIGTERM → both exit cleanly
- If child doesn't respond within 10s → parent sends SIGKILL

**Files:** `tests/test_functional.py` (add)

**Change:**

1. Create a mock aider that sleeps 30s (simulates long-running edit)
2. Start `run.py` as subprocess
3. Send SIGTERM to parent after 1s
4. Assert: parent exits 0 within 12s
5. Assert: no orphan child process

- [x] Create slow mock aider fixture
- [x] Implement SIGTERM forwarding test
- [x] Passes on Linux

---

## Milestone Checklist

- [x] **M1** — Core implementation
- [x] **M2** — Config + provider support
- [x] **M3** — Test suite
- [x] **M4** — Complete test coverage
- [x] **M5** — Functional tests (subprocess contract)
- [x] **M6** — SIGTERM graceful shutdown test
- [x] **M7** — kiso.toml validation test
- [x] **M8** — Config error handling

### M7 — kiso.toml validation test

**Problem:** No test verifies `kiso.toml` consistency.

**Files:** `tests/test_manifest.py` (new)

**Change:**

1. Parse `kiso.toml`, extract declared arg names
2. Verify each appears in `run.py`
3. Verify TOML structure

- [x] Implement manifest validation test

---

### M8 — Config error handling: malformed TOML

**Problem:** `load_config()` reads config.toml but no test covers malformed files.

**Files:** `tests/test_config.py` (add)

**Change:**

1. Create malformed config.toml → verify `load_config()` raises `TOMLDecodeError`
2. Config.toml with extra unknown keys → verify they're silently ignored

- [x] Implement config error tests

## M-next — Fallback to KISO_LLM_API_KEY when KISO_TOOL_AIDER_API_KEY not set ✅

- [x] `run.py`: try `KISO_TOOL_AIDER_API_KEY` first, fall back to `KISO_LLM_API_KEY`
- [x] Error message updated to mention both env vars
- [x] Update kiso.toml comment + README (deferred — preset README already updated)

## History (from core plugins.md)

### env var prefix fix ✅
- [x] Fixed `KISO_SKILL_AIDER_` → `KISO_TOOL_AIDER_` in run.py, kiso.toml, live tests

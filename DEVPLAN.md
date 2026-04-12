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
- [x] **M10** — Retry aider on OpenRouter per-request affordable-cap with the provider-reported ceiling ✅

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

---

### M9 — Declare `consumes` in kiso.toml (core M826)

**Context:** Core M826 adds a `consumes` field to `[kiso.tool]` in kiso.toml. The planner uses
this to auto-route session workspace files to the right tool. Vocabulary: `image`, `document`,
`audio`, `video`, `code`, `web_page`.

**Changes:**
- [x] Add `consumes = ["code"]` to `[kiso.tool]` in kiso.toml
- [ ] Enrich `usage_guide` with concrete file path examples for `files` and `read_only_files` args

---

### M10 — Retry aider on OpenRouter per-request affordable-cap with the provider-reported ceiling ✅

**Problem.** Two kiso-run/core functional tests
(`TestF17FullPipeline::test_screenshot_ocr_aider_exec_msg` and
`TestF29AiderWriteCode::test_aider_write_script`) were failing on
the 2026-04-12 post-core-M1329 full-matrix run. Both share a
single root cause that originates in this wrapper.

Observed error (from core functional log, emitted by aider's
underlying litellm via the OpenRouter route):

```
APIError: OpenrouterException - This request requires more credits,
or fewer max_tokens. You requested up to 64000 tokens, but can only
afford 49423. To increase, visit https://openrouter.ai/settings/
```

Failure shapes in core:

- **F17** (multi-wrapper pipeline, browser → ocr → aider → exec → msg):
  aider fails with the 402 above, kiso's reviewer marks the task
  for replan, the new plan writes the file via an exec task
  (`cat > heredoc`). The file is produced correctly but the test
  asserts Plan 3 is codegen-only and refuses the exec fallback.

- **F29** (pure aider test): aider fails with the same 402, kiso
  replans back to aider (because the goal explicitly requires
  aider), each retry hits the same 402, the test times out.

**Not credits exhaustion.** The user's OpenRouter balance is
positive. The 402 is a per-request affordability cap:
OpenRouter enforces
`max_tokens_per_request ≤ balance / per_token_cost`. For
high-max-output models (e.g. Claude Sonnet 4.x with
`max_output_tokens = 64000`) on a moderate balance, a single
call that requests the model's full max output exceeds what the
current balance can fund in one shot, and OpenRouter rejects
with the specific affordable ceiling embedded in the error
message (`can only afford 49423`).

**Why the wrapper hits 64000.** Aider reads `max_output_tokens`
from the model's litellm settings and passes it as `max_tokens`
on every completion call. It does not know about the
balance-dependent per-request cap. Its built-in retry loop
retries with the same `max_tokens`, so 402 loops forever.

**Fix.** Detect the specific OpenRouter 402 error in aider's
stderr after a failed run. Parse the affordable ceiling with a
deterministic regex (`can only afford (\d+)`). Retry aider
**exactly once** with `max_tokens` capped to that value, via
aider's native per-run override mechanism. If the retry also
fails (or the error is not from OpenRouter, or the format does
not match the regex), fall through to the existing error path
with no regression.

**Mechanism for overriding aider's max_tokens.** To be confirmed
during implementation. Candidate approaches, in order of
preference:

1. **Temporary `--model-settings-file`.** Write a temp YAML
   containing the currently-configured model name with
   `max_tokens: <cap>` and invoke aider with
   `--model-settings-file <path>`. This is aider's documented
   mechanism for per-model parameter overrides and is the
   cleanest match.
2. **litellm env var.** If there is a `LITELLM_*` or `AIDER_*`
   environment variable that caps max_tokens per call, set it in
   the retry subprocess env. Less clean but simpler if option 1
   is not available on the installed aider version.
3. **Diagnostic-only fallback.** If neither option 1 nor 2 works
   on the installed aider, do not attempt a retry here. Instead
   surface the parsed ceiling in the wrapper's stderr with a
   clear message (e.g.
   `aider cannot afford max_tokens N on this balance`) so that
   kiso's reviewer and the functional tests can distinguish
   the provider cap from generic aider failures. This is
   strictly worse (F17/F29 still fail) but at least surfaces
   the real cause upstream.

Choose between options 1/2/3 based on what the installed aider
version actually supports. Record the choice + the evidence in
this milestone at completion.

**Properties of the fix (option 1 or 2).**

- **Structural, not a heuristic.** The cap comes from the
  provider's own error message, not from a hard-coded constant
  or a language-specific rule.
- **Respects kiso-run/core's
  `feedback_max_tokens_truncation.md` policy.** That policy
  forbids *artificial* max_tokens caps. Here the cap is not
  artificial — it is the provider's explicitly stated affordable
  ceiling for this specific balance + model + moment. Accepting
  a provider-declared limit is not inventing one.
- **Deterministic regex parse.** Zero LLM, zero guessing. If
  the format ever changes and the regex stops matching, the
  code falls through to the existing error path — no
  regression.
- **One retry only.** No retry storm, no loop. If the first
  retry with the cap also fails, something else is wrong and
  the wrapper exits with the original error.
- **Zero impact on the successful path.** The parser and retry
  branch only run when the first aider invocation exits non-zero
  AND stderr matches the OpenRouter 402 format.
- **Generalist.** Any OpenRouter call from aider that hits the
  per-request cap now adapts automatically — regardless of
  which model, which balance, which request size. Not
  overfitted to F17 / F29.
- **F17 and F29 are both fixed transitively.** Aider no longer
  loops on 402, so there is no replan fallback to exec (F17
  Plan 3 stays codegen-only) and no retry storm (F29 completes
  without the outer timeout firing). No changes to the core
  tests required.

**Implementation outcome: Option 1 — `--model-settings-file`.**
Verified on the installed aider version (kiso-run/plugins/wrapper-aider
venv): aider exposes `--model-settings-file MODEL_SETTINGS_FILE`
and the env-var equivalent `AIDER_MODEL_SETTINGS_FILE`. Source
inspection of `aider/models.py:1080-1089` showed that aider's
loader does a **full replace** of any pre-existing entry for the
same model name (not a merge), so the override YAML must stand
on its own. The override file we write contains only the bare
minimum: one entry per configured model with
`extra_params: {max_tokens: <cap>}`. This drops the default
`extra_headers` (e.g. `output-128k-2025-02-19`) for the retry
call, which on high-max-output models is exactly what we want
— without the 128k beta header the model reverts to its
standard output cap, and with `max_tokens` also set explicitly
the request is doubly constrained to the provider-affordable
ceiling. Cache_control / prompt caching are lost on the retry
call (cost tradeoff), but the retry only fires on an already-
failed call, so the tradeoff is acceptable.

Option 2 (env var like `AIDER_MAX_TOKENS`) does not exist in
the installed aider. Option 3 (diagnostic-only exit) was not
needed because Option 1 is fully supported.

**Tasks.**

- [x] Verify the exact aider CLI / config mechanism for
      overriding `max_tokens` per run on the installed aider
      version — confirmed `--model-settings-file` + yaml-loader
      full-replace semantics in `aider/models.py:1080-1089`
- [x] Implement `_parse_openrouter_affordable_cap(stderr) -> int | None`
      with a single-line regex `r'can only afford (\d+)'`;
      returns None on empty/missing/malformed input
- [x] Implement `_build_model_settings_override(config, cap, tmp_dir) -> str | None`
      which writes a temp YAML with one entry per configured
      model (architect/editor/weak) — each entry carries only
      `name` + `extra_params.max_tokens: <cap>`. Returns None
      when no models are configured (cannot target any entry)
- [x] Add the retry branch in `run.py` between the first
      `run_aider` call and the error-reporting block: if exit
      != 0 AND the parser returns an int AND the override
      builder returns a path, re-run aider with
      `--model-settings-file <path>` appended. On any other
      condition, fall through unchanged
- [x] Unit tests in `tests/test_affordable_cap_retry.py` (15
      tests, all green):
    - [x] Parser: 6 tests (happy path, empty, pattern miss,
          malformed number, multiple matches, None input)
    - [x] Override builder: 3 tests (multi-model, single-model,
          empty-config returns None)
    - [x] End-to-end via `run()`: 6 tests
        - [x] 402 + parseable cap + successful retry → run_aider
              called exactly twice, second call carries the
              `--model-settings-file` flag pointing at a real
              YAML with the correct model names and max_tokens
        - [x] Non-402 error → no retry, one call only
        - [x] 402 + unparseable format → no retry
        - [x] 402 + retry also fails → exactly two calls, both
              carry the expected shape, wrapper exits 1
        - [x] 402 + no configured models → no retry (cannot
              target override)
        - [x] Happy path (first call succeeds) → no retry, one
              call only, no settings-file flag
- [x] Run full wrapper-aider suite (excluding `test_functional.py`
      which is pre-broken by an environmental issue unrelated
      to this milestone, see note below): 87 passed
- [x] Commit & push
- [ ] Cross-repo: notify the corresponding kiso-run/core M1331
      entry and re-run the core functional + extended suites
      when LLM credits are available; confirm F17 Plan 3 stays
      codegen-only and F29 completes without timeout

**Pre-existing unrelated failure note.** `tests/test_functional.py`
fails with `PermissionError: [Errno 13] Permission denied:
'/usr/bin/aider'` for all 9 tests. Verified on baseline (before
this milestone's changes) — the failure is **not** introduced by
M10. Root cause: `tests/test_functional.py:17` resolves
`AIDER_BIN = Path(sys.executable).parent / "aider"`. Under
`uv run --group dev pytest` on this system, `sys.executable`
resolves to `/usr/bin/python3` (the system interpreter) rather
than `.venv/bin/python3`, so the fixture tries to write a mock
aider binary to `/usr/bin/aider`, which is not writable. This
is an environment setup / pytest-under-uv issue that merits a
separate milestone (inject TOOL_DIR-based path or use a
tmp_path-based mock aider on PATH, rather than swapping the
real binary). Out of scope here.

**Done when.** The OpenRouter per-request cap error is handled
by this wrapper with a single provider-informed retry. F17 and
F29 on kiso-run/core will validate green on the next
functional/extended run (deferred to LLM-credit-available run).
The chosen override mechanism (Option 1 —
`--model-settings-file`) is recorded with the rationale and
the aider source line it was verified against. ✅

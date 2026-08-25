# App Server Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prefer Codex App Server for session discovery and preview while preserving the read-only SQLite/JSONL implementation as a compatibility fallback.

**Architecture:** Add a focused synchronous JSON-RPC client backed by one reusable `codex app-server` subprocess. Wrap it and the existing local services with small hybrid adapters, then wire those adapters into the CLI and expose degraded-mode diagnostics in the TUI.

**Tech Stack:** Python 3.10 standard library (`subprocess`, `threading`, `queue`, `json`), `unittest`, Codex App Server JSONL protocol.

## Global Constraints

- Do not enable App Server experimental API capabilities.
- Request only non-archived CLI threads.
- A successful empty App Server result is authoritative.
- Never write to Codex databases, rollouts, authentication, or configuration.
- Keep Python 3.10+, Linux, and macOS support with no runtime dependencies.
- Preserve `codex resume <full session id>` as the handoff command.

---

### Task 1: App Server protocol client and parsers

**Files:**
- Create: `src/codex_session_manager/app_server.py`
- Create: `tests/test_app_server.py`

**Interfaces:**
- Produces: `AppServerError`, `AppServerClient(codex_path, codex_home, version, timeout=...)`, `list_sessions() -> list[Session]`, `get_preview(session) -> Preview`, and `close() -> None`.
- Consumes: existing `Session`, `Preview`, and `clean_user_text`.

- [ ] **Step 1: Write failing parser tests**

Add tests that pass representative `thread/list` dictionaries into pure parsing helpers and assert ID, preview/first question, cwd, path, created time, recency time, unknown-field tolerance, invalid-object rejection, and extraction of first/latest user plus latest agent messages from `thread/read` turns.

- [ ] **Step 2: Verify parser tests fail**

Run: `python3 -m unittest tests.test_app_server -v`

Expected: import failure because `codex_session_manager.app_server` does not exist.

- [ ] **Step 3: Implement pure response parsing**

Implement strict container validation with forward-compatible unknown fields. Normalize timestamps through existing helpers, clean injected context from user messages, use `preview` as the first question when available, and derive it from the first user item otherwise.

- [ ] **Step 4: Verify parser tests pass**

Run: `python3 -m unittest tests.test_app_server -v`

Expected: parser tests pass.

- [ ] **Step 5: Write failing transport tests**

Create an executable fake Python App Server fixture in a temporary directory. Assert the client sends `initialize`, then `initialized`, paginates `thread/list` with `sourceKinds=["cli"]` and `archived=false`, correlates response IDs while ignoring notifications, propagates JSON-RPC errors, times out, passes `CODEX_HOME`, and closes idempotently.

- [ ] **Step 6: Verify transport tests fail**

Run: `python3 -m unittest tests.test_app_server.AppServerClientTests -v`

Expected: failures for missing subprocess request implementation.

- [ ] **Step 7: Implement the transport**

Use `subprocess.Popen` with piped stdin/stdout and discarded stderr. A daemon reader thread parses newline-delimited responses into a queue. Permit one synchronous outstanding request, use monotonic deadlines, treat exit/EOF/malformed messages as `AppServerError`, and shut down gracefully with terminate/kill fallback.

- [ ] **Step 8: Verify Task 1**

Run: `python3 -m unittest tests.test_app_server -v`

Expected: all App Server tests pass with no leaked child process.

- [ ] **Step 9: Commit Task 1**

```bash
git add src/codex_session_manager/app_server.py tests/test_app_server.py
git commit -m "feat: read sessions through codex app server"
```

### Task 2: Hybrid compatibility adapters

**Files:**
- Create: `src/codex_session_manager/compatibility.py`
- Create: `tests/test_compatibility.py`

**Interfaces:**
- Produces: `CompatibleSessionRepository(primary, fallback)` with `list_sessions()` and `warning`; `CompatiblePreviewService(primary, fallback)` with `get(session)`.
- Consumes: App Server service methods and existing local repository/preview protocols.

- [ ] **Step 1: Write failing repository adapter tests**

Assert primary results win, primary empty results remain empty, expected `AppServerError` triggers local fallback, fallback success sets a localized degraded-mode warning, and empty fallback sets an actionable upgrade warning.

- [ ] **Step 2: Verify repository tests fail**

Run: `python3 -m unittest tests.test_compatibility.CompatibleSessionRepositoryTests -v`

Expected: import failure for the new adapter.

- [ ] **Step 3: Implement repository adapter**

Catch only `AppServerError`, preserve successful empty results, and expose warning state without changing the TUI repository method signature.

- [ ] **Step 4: Verify repository tests pass**

Run: `python3 -m unittest tests.test_compatibility.CompatibleSessionRepositoryTests -v`

Expected: all repository adapter tests pass.

- [ ] **Step 5: Write failing preview adapter tests**

Assert App Server preview success wins and `AppServerError` falls back to the local `PreviewService`, including sessions whose rollout path is absent.

- [ ] **Step 6: Implement preview adapter and verify Task 2**

Run: `python3 -m unittest tests.test_compatibility -v`

Expected: all hybrid adapter tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/codex_session_manager/compatibility.py tests/test_compatibility.py
git commit -m "feat: add storage compatibility fallback"
```

### Task 3: CLI lifecycle and TUI diagnostics

**Files:**
- Modify: `src/codex_session_manager/cli.py`
- Modify: `src/codex_session_manager/tui.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_tui.py`

**Interfaces:**
- Consumes: `AppServerClient`, compatible adapters, existing `run_tui` and `resume_command`.
- Produces: App Server-first service construction and a visible non-fatal compatibility warning.

- [ ] **Step 1: Write failing CLI lifecycle tests**

Patch constructors and assert Codex-present execution builds hybrid services with the resolved Codex path/home, closes the client on quit and before resume, and Codex-absent execution stays local without constructing App Server.

- [ ] **Step 2: Verify CLI tests fail**

Run: `python3 -m unittest tests.test_cli -v`

Expected: assertions fail because CLI still constructs local services directly.

- [ ] **Step 3: Implement CLI construction and cleanup**

Build the App Server client only when `codex` is on `PATH`; share it between hybrid repository and preview services; close in `finally` around TUI execution and before `os.execvp` handoff.

- [ ] **Step 4: Write failing warning-display tests**

Assert the event loop reads a repository `warning` after initial load and refresh, displays it with informational styling, and does not override a missing-Codex error.

- [ ] **Step 5: Implement warning display**

Use optional `getattr(repository, "warning", "")` so existing repository fakes and third-party adapters remain compatible.

- [ ] **Step 6: Verify Task 3**

Run: `python3 -m unittest tests.test_cli tests.test_tui -v`

Expected: all CLI and TUI tests pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/codex_session_manager/cli.py src/codex_session_manager/tui.py tests/test_cli.py tests/test_tui.py
git commit -m "feat: wire app server compatibility mode"
```

### Task 4: Documentation, version, and release verification

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `src/codex_session_manager/__init__.py`
- Modify: `tests/test_release_assets.py`
- Modify: `tests/verify_distribution.py` only if the new source modules reveal a packaging gap.

**Interfaces:**
- Produces: version `0.2.0` and user documentation for primary/fallback behavior and diagnostics.

- [ ] **Step 1: Write failing release/documentation tests**

Assert package/project versions are `0.2.0`, README describes App Server primary mode, local fallback, automatic behavior, and the no-code-change upgrade path.

- [ ] **Step 2: Verify release tests fail**

Run: `python3 -m unittest tests.test_release_assets -v`

Expected: version and documentation assertions fail.

- [ ] **Step 3: Update documentation and version**

Describe the compatibility hierarchy, degraded warning, `CODEX_HOME` propagation, privacy behavior, and advise users to update the package after a future incompatible Codex release.

- [ ] **Step 4: Run the complete local suite**

Run: `python3 -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 5: Verify build artifacts**

Run the repository's wheel/sdist build and `tests/verify_distribution.py`, install the wheel into a temporary virtual environment, and verify `codex-session --help` plus `codex-session --version` report `0.2.0`.

- [ ] **Step 6: Run read-only live smoke checks**

Use the installed Codex App Server to list non-archived CLI sessions without printing their content, fetch one preview without printing it, close the subprocess, and confirm fallback fixture tests still pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add README.md pyproject.toml src/codex_session_manager/__init__.py tests
git commit -m "docs: release app server compatibility"
```

### Task 5: Review, merge, and delivery

**Files:**
- Review all changes since the design commit.

- [ ] **Step 1: Request code review**

Provide the reviewer the design, plan, base SHA, and feature HEAD. Fix every verified Critical or Important finding with a regression test first.

- [ ] **Step 2: Run fresh final verification**

Run the complete test suite, compile check, `git diff --check`, distribution verification, installed-wheel smoke tests, and live read-only App Server smoke test.

- [ ] **Step 3: Merge and re-verify**

Fast-forward the feature branch into `master`, rerun the full suite on merged `master`, and remove the owned worktree only after success.

- [ ] **Step 4: Push and monitor CI**

Push `master` to `origin`, verify local and remote SHA equality, and wait for all GitHub Actions matrix jobs to finish successfully.

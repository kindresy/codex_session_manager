# Cloud Session Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manual upload of normalized Codex history to a user-owned Cloudflare R2 service, plus read-only Android/PWA and terminal viewers.

**Architecture:** Extend the existing App Server client with full-thread reads, normalize supported items into a versioned project schema, and synchronize them through a standard-library HTTP client. A framework-free Cloudflare Worker stores one JSON object per session plus a small index and serves a lightweight same-origin PWA.

**Tech Stack:** Python 3.10 standard library, Codex App Server JSON-RPC, Cloudflare Workers/R2, browser HTML/CSS/JavaScript, Node.js built-in test runner, Wrangler.

## Global Constraints

- Keep the Python runtime dependency-free and compatible with Python 3.10 through 3.13.
- Preserve existing local TUI behavior and App Server/SQLite/JSONL fallbacks.
- Sync only non-archived Codex CLI sessions.
- Use manual sync only; do not add a daemon, timer, or automatic upload.
- Store plaintext versioned JSON in a private user-owned R2 bucket behind one Bearer token.
- Preserve cloud sessions missing locally and never re-upload IDs in `deleted_ids`.
- Never upload system prompts, injected environment context, internal reasoning, authentication data, or unknown item types.
- Do not add a large web framework or UI component library.

---

### Task 1: Full-thread normalization

**Files:**
- Create: `src/codex_session_manager/cloud_format.py`
- Modify: `src/codex_session_manager/app_server.py`
- Test: `tests/test_cloud_format.py`
- Test: `tests/test_app_server.py`

**Interfaces:**
- Produces: `AppServerClient.read_thread(session_id: str) -> dict[str, Any]`
- Produces: `normalize_cloud_session(session: Session, response: Any) -> dict[str, Any]`

- [ ] Write failing tests with synthetic `userMessage`, `agentMessage`, `commandExecution`, `fileChange`, reasoning, unknown, and injected-context items.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_cloud_format tests.test_app_server -v` and confirm the new imports or assertions fail.
- [ ] Add `read_thread()` as a public wrapper around `thread/read` with `includeTurns: true` and implement strict top-level validation plus tolerant omission of unsupported item variants.
- [ ] Emit schema version 1 with `id`, `question`, `created_at`, `updated_at`, `cwd`, and chronological `turns`; normalize commands to `command`, `cwd`, `status`, `output`, `exit_code`, and file changes to `path`, `kind`, `diff`.
- [ ] Rerun the focused tests and commit as `feat: normalize codex threads for cloud sync`.

### Task 2: Cloud configuration and HTTP API client

**Files:**
- Create: `src/codex_session_manager/cloud_client.py`
- Test: `tests/test_cloud_client.py`

**Interfaces:**
- Produces: `SyncConfig(worker_url: str, token: str)`
- Produces: `default_config_path() -> Path`, `load_config(path)`, `save_config(path, config)`
- Produces: `CloudClient.get_index()`, `get_session(id)`, `put_session(payload)`, `put_index(payload)`, `delete_session(id)`, and `health()`

- [ ] Write failing tests using a local `http.server.ThreadingHTTPServer` fixture for URL construction, UTF-8 JSON, Bearer headers, 401, malformed JSON, non-2xx responses, and config round trips.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_cloud_client -v` and confirm failure.
- [ ] Implement the client using `urllib.request`, normalize the Worker URL once, enforce schema version 1, and raise a single `CloudError` with user-facing messages.
- [ ] Save configuration atomically as UTF-8 JSON under `~/.config/codex-session/sync.json` and create parent directories as needed.
- [ ] Rerun the focused tests and commit as `feat: add cloud sync http client`.

### Task 3: Incremental synchronization engine

**Files:**
- Create: `src/codex_session_manager/sync.py`
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `AppServerClient.list_sessions()`, `read_thread()`, `normalize_cloud_session()`, and `CloudClient`
- Produces: `SyncResult(uploaded, skipped, failed)` and `sync_sessions(app_server, cloud, force_all=False)`

- [ ] Write failing tests for empty cloud state, incremental timestamps, `--all`, remote-only retention, tombstone skipping, one failed thread read, one failed upload, and failed final index write.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_sync -v` and confirm failure.
- [ ] Implement selection by full ID and `updated_at`, upload independently, retain remote-only entries, update `generated_at`, sort by update time descending, and update the index after all session attempts.
- [ ] Ensure failed items are absent from new index entries but prior successful remote entries are preserved.
- [ ] Rerun the focused tests and commit as `feat: add incremental cloud synchronization`.

### Task 4: CLI sync commands

**Files:**
- Modify: `src/codex_session_manager/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces subcommands: `sync setup`, `sync`, `sync --all`, `sync status`, and `cloud`

- [ ] Write failing CLI tests for parser help, interactive setup, missing configuration, missing Codex for upload, successful and partial sync summaries, status output, and client cleanup.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_cli -v` and confirm failure.
- [ ] Refactor local browsing into a helper without changing its arguments or behavior; dispatch sync subcommands before constructing the local TUI.
- [ ] Resolve configuration paths without changing `$CODEX_HOME`; use `getpass.getpass()` for token input and never print the token.
- [ ] Rerun CLI and existing compatibility tests and commit as `feat: expose cloud sync commands`.

### Task 5: Read-only cloud terminal mode

**Files:**
- Create: `src/codex_session_manager/cloud_repository.py`
- Modify: `src/codex_session_manager/tui.py`
- Modify: `src/codex_session_manager/cli.py`
- Test: `tests/test_cloud_repository.py`
- Test: `tests/test_tui.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `CloudSessionRepository.list_sessions()` and `CloudPreviewService.get(session)`
- Extends: `run_tui(..., allow_select: bool = True, empty_message: str | None = None)`

- [ ] Write failing tests that map cloud index/session JSON to existing `Session`/`Preview`, cache selected cloud sessions, disable Enter, and display cloud-specific help and empty text.
- [ ] Run the focused Python tests and confirm failure.
- [ ] Implement adapters using existing models; summarize full cloud records into first/latest user/assistant preview without adding new TUI models.
- [ ] Add the smallest TUI option needed to disable selection while retaining navigation, search, refresh, and quit.
- [ ] Wire `codex-session cloud` and commit as `feat: add read-only cloud terminal browser`.

### Task 6: Cloudflare Worker API

**Files:**
- Create: `cloud/package.json`
- Create: `cloud/wrangler.jsonc`
- Create: `cloud/src/worker.js`
- Create: `cloud/test/worker.test.js`

**Interfaces:**
- Implements: `/health`, `/api/sessions`, `/api/sessions/:id`, and `/api/index`
- Consumes: `env.SESSIONS` R2 binding, `env.SYNC_TOKEN`, and `env.ASSETS`

- [ ] Write Node tests with an in-memory fake R2 binding for unauthenticated requests, index defaults, upload/read, invalid IDs/payloads, deletion tombstones, unsupported schemas, and R2 failures.
- [ ] Run `cd cloud && npm test` and confirm failure before the handler exists.
- [ ] Implement a single exported Worker handler with small validation/response helpers; route `/api/*` before static assets.
- [ ] Make DELETE hide the ID in the index before deleting its object, and return success only after both operations finish.
- [ ] Rerun Node tests and commit as `feat: add cloudflare sync api`.

### Task 7: Responsive PWA viewer

**Files:**
- Create: `cloud/public/index.html`
- Create: `cloud/public/app.css`
- Create: `cloud/public/app.js`
- Create: `cloud/public/manifest.webmanifest`
- Create: `cloud/public/sw.js`
- Create: `cloud/test/app.test.js`

**Interfaces:**
- Consumes same-origin Worker endpoints and browser-local token storage.

- [ ] Write DOM-independent Node tests for metadata matching, chronological item rendering, HTML escaping, and collapsed command/file sections by exporting pure helpers from `app.js`.
- [ ] Run `cd cloud && npm test` and confirm failure.
- [ ] Build a framework-free list/detail app with token setup, refresh, search, delete confirmation, phone navigation, desktop two-pane layout, and restrained color styling.
- [ ] Add install manifest and an app-shell-only service worker that never caches `/api/` responses.
- [ ] Rerun Node tests and commit as `feat: add mobile cloud session viewer`.

### Task 8: Guided Cloudflare deployment

**Files:**
- Create: `cloud/deploy.sh`
- Test: `tests/test_cloud_deploy.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: repeatable `cloud/deploy.sh` that creates/selects `codex-session-history`, sets `SYNC_TOKEN`, and deploys.

- [ ] Write static and fake-command tests proving the script checks npm/npx, invokes Wrangler login and bucket creation safely, stores the token as a secret, deploys, and never echoes the token.
- [ ] Run `PYTHONPATH=src python3 -m unittest tests.test_cloud_deploy -v` and confirm failure.
- [ ] Implement the POSIX shell script with explicit errors and idempotent handling when the R2 bucket already exists.
- [ ] Rerun focused tests and commit as `feat: add guided cloud deployment`.

### Task 9: Documentation, release metadata, and end-to-end verification

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `MANIFEST.in`
- Modify: `tests/test_release_assets.py`
- Create: `tests/test_cloud_integration.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Documents deployment, setup, sync, cloud browsing, storage behavior, deletion, and limitations.

- [ ] Add a failing Python integration test that uses a local HTTP server and synthetic App Server response to upload, list, read, and delete one session.
- [ ] Add release-asset tests requiring cloud source, PWA, deployment script, and documentation in the source distribution.
- [ ] Update CI to run Python tests and `npm test` under `cloud/`; update package version to the next minor release and include cloud files in the sdist.
- [ ] Run `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v`, `python3 -m compileall -q src tests`, `cd cloud && npm test`, and `git diff --check`.
- [ ] Build wheel/sdist and verify their inventories plus installed `codex-session --version`.
- [ ] Perform a read-only live App Server normalization smoke test without printing session contents.
- [ ] Update README with official Codex App Server and Cloudflare deployment references and commit as `docs: release cloud session sync`.

### Task 10: Review, push, and CI closure

**Files:**
- Review all changes from the design commit through HEAD.

- [ ] Run a focused correctness review for data omission, retention, tombstones, partial failure behavior, API validation, and read-only cloud TUI behavior.
- [ ] Fix all Critical and Important findings with regression tests and rerun the complete verification suite.
- [ ] Push `master` to `origin`.
- [ ] Watch the GitHub Actions run through completion and inspect every failed job if any.
- [ ] Confirm local HEAD, `origin/master`, and the successful CI `headSha` are identical.

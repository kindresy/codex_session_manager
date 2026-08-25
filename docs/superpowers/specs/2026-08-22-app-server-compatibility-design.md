# Codex App Server Compatibility Design

## Goal

Reduce breakage from Codex session-storage migrations without removing the
existing read-only SQLite and JSONL compatibility path.

## Architecture

The application will use the Codex App Server as its primary session source.
One newline-delimited JSON-RPC subprocess is started lazily and reused for the
TUI lifetime. The client performs the required `initialize`/`initialized`
handshake, then uses only the non-experimental `thread/list` and `thread/read`
methods. It never enables `experimentalApi`.

`thread/list` is paginated and requests only non-archived CLI threads, sorted
by recency. App Server thread summaries are normalized into the existing
`Session` model. `thread/read` supplies lazy previews from user and agent
message items. Selecting a session continues to execute the stable
`codex resume <session-id>` command.

The existing `SessionRepository` and `PreviewService` remain as a secondary
local-storage adapter. A hybrid repository and preview service try App Server
first and fall back only when the server cannot start, times out, returns an
error, or produces an incompatible response. An empty successful App Server
listing is authoritative and does not trigger fallback.

## Components

- `app_server.py`: subprocess lifecycle, sequential JSON-RPC requests,
  pagination, response validation, and conversion to `Session`/`Preview`.
- `compatibility.py`: primary/fallback orchestration and user-facing degraded
  mode diagnostics.
- `repository.py` and `preview.py`: unchanged local SQLite/JSONL fallback
  responsibilities.
- `cli.py`: constructs the hybrid services when `codex` exists, closes the
  App Server before process handoff, and keeps browse-only behavior when Codex
  is absent.
- `tui.py`: displays a repository compatibility warning without treating it as
  a fatal error.

## Failure Handling

App Server startup and every request have finite timeouts. Malformed JSON,
unexpected response shapes, process exit, broken pipes, and JSON-RPC errors are
reported as one `AppServerError` family. The hybrid layer catches only expected
compatibility/transport errors, switches to local parsing, and records a
localized warning. Unexpected programming errors are not hidden.

If local fallback returns sessions, the TUI reports that compatibility mode is
active. If App Server fails and local storage contains no readable sessions,
the TUI tells the user to upgrade `codex-session-manager` instead of silently
presenting an unexplained empty list.

Closing the client is idempotent. It closes stdin, terminates the subprocess,
waits briefly, and kills it only if graceful shutdown does not complete.

## Portability and Privacy

The implementation uses only the Python standard library and preserves Python
3.10+, Linux, and macOS support. `CODEX_HOME` is passed explicitly to the App
Server subprocess so `--codex-home` continues to work. No database or rollout
file is modified, and no conversation content is logged.

## Testing

Unit tests use a small fake App Server process speaking the real JSONL protocol
to cover handshake, pagination, filtering parameters, previews, errors,
timeouts, shutdown, and custom `CODEX_HOME`. Pure response parsers cover
malformed and forward-compatible fields. Hybrid tests cover primary success,
authoritative empty results, local fallback, warning text, and preview fallback.

The complete existing suite, distribution build checks, installed-wheel smoke
tests, and a read-only live App Server smoke test must pass before merge and
push.

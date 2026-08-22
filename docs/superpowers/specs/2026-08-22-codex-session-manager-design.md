# Codex Session Manager Design

## Goal

Build a polished, zero-dependency terminal UI for browsing and resuming Codex CLI sessions. The tool lists every resumable, non-archived CLI session, previews the selected conversation, and replaces itself with `codex resume <session-id>` when the user presses Enter.

The project lives at `/tmp/codex-session-manager`, uses Python 3 and the standard library, and exposes the `codex-session` command.

## Scope

The first version will:

- list non-archived interactive Codex CLI sessions across all working directories;
- show an eight-character session ID prefix, first user question, creation time, most recent activity time, and working-directory basename;
- sort sessions by most recent activity, newest first;
- update a conversation preview as the user moves with `j` and `k`;
- resume the selected session with Enter;
- support colors and responsive split/stacked layouts;
- remain read-only with respect to Codex's files.

Archived sessions, subagent sessions, VS Code sessions, deletion, renaming, pinning, filtering, and search are outside the first version.

## Architecture

The package has five focused modules:

- `models.py` defines the normalized `Session` and `Preview` data classes.
- `repository.py` discovers Codex storage and returns normalized sessions. It reads SQLite first and falls back to JSONL.
- `preview.py` lazily reads the selected rollout and extracts user/assistant content, with an in-memory cache.
- `tui.py` owns curses layout, rendering, keyboard input, and view state. It depends on the normalized model interfaces rather than storage details.
- `cli.py` validates the environment, starts the TUI, and executes Codex after a selection.

The console entry point calls `codex_session_manager.cli:main`.

## Session Discovery

`CODEX_HOME` is honored when set; otherwise the tool uses `~/.codex`.

The primary repository selects the newest usable `state_*.sqlite`, opens it through a read-only SQLite URI, checks for the `threads` table and available columns, and builds its query dynamically. It includes rows where:

- `archived` is absent or false;
- `source` is exactly `cli` when that column exists;
- `first_user_message` is non-empty, or the rollout contains a user message when the field is unavailable.

An exact `source = cli` check excludes structured subagent sources and VS Code sessions. The rollout path is retained for lazy preview loading.

If no compatible database can be read, the fallback repository scans `sessions/**/*.jsonl`. It reads enough of each file to extract `session_meta`, the first genuine user message, and the last relevant timestamp. Developer, system, tool, and environment-context messages are not treated as user questions. A malformed file is skipped without aborting the full listing.

## Time Semantics

Creation time uses the first available value in this order:

1. `created_at_ms`
2. `created_at`
3. the session metadata timestamp
4. the rollout filename timestamp

The displayed "last opened" value represents Codex recency and uses:

1. `recency_at_ms`
2. `recency_at`
3. `updated_at_ms`
4. `updated_at`
5. rollout modification time in JSONL fallback mode

Epoch seconds and milliseconds are normalized, converted to the host's local timezone, and formatted as a compact absolute time with a human-friendly relative label where space permits.

## Preview Data Flow

Initial loading reads metadata only. Whenever selection changes, the preview service reads only that session's rollout and caches the result by path and modification time.

It extracts:

- the complete first genuine user question;
- the most recent genuine user message;
- the most recent assistant message;
- full UUID and working directory.

Input from developer/system roles, tool calls, reasoning, approvals, and injected environment context is ignored. Text wraps to the preview pane width. Preview scrolling is independent from list selection and resets when the selection changes.

## TUI Layout and Interaction

The preferred wide-terminal layout is a left session table and right preview pane. On narrower terminals the panes stack vertically. If the terminal cannot fit the minimum safe dimensions, the UI renders a size requirement instead of attempting to draw clipped windows.

The palette uses cyan for the title and focus accents, a blue-cyan selected row, yellow for time metadata, gray for secondary text, and the terminal's default background. When curses reports no color support, rendering remains fully usable without colors.

Keys:

- `j` or Down: next session
- `k` or Up: previous session
- `Ctrl-d` or Page Down: scroll preview down
- `Ctrl-u` or Page Up: scroll preview up
- `g`: first session
- `G`: last session
- Enter: select and resume
- `r`: reload sessions
- `q` or Escape: quit

The footer always shows the relevant shortcuts and transient status/error messages. Chinese and other wide characters are measured by a small standard-library display-width helper so columns remain aligned and truncation never splits combining sequences.

## Resuming a Session

The TUI returns the complete selected UUID to the CLI layer. After curses restores the terminal, the CLI checks that `codex` is available and calls:

```python
os.execvp("codex", ["codex", "resume", session_id])
```

This preserves normal signal handling and gives the resumed Codex process the original terminal. If validation fails before the transition, the TUI displays the error and remains usable. A rare `execvp` failure is reported to stderr with a nonzero exit code after terminal restoration.

## Error Handling

- A missing Codex storage directory or zero matching sessions produces an actionable Chinese empty-state message.
- An incompatible or locked SQLite database triggers the JSONL fallback.
- A corrupt rollout affects only its own preview.
- Missing curses color support selects a monochrome palette.
- Terminal resize events recompute layout without losing selection.
- A missing `codex` executable prevents resume and explains how to fix `PATH`.
- The tool never writes to Codex databases, indexes, rollouts, or configuration.

## Testing

Tests use `unittest`, temporary directories, generated SQLite databases, and generated JSONL fixtures. Coverage includes:

- SQLite discovery, dynamic columns, filters, ordering, and timestamp normalization;
- exclusion of archived, VS Code, and structured subagent sessions;
- JSONL fallback on missing, incompatible, and corrupt databases;
- correct filtering of developer/tool content from the first question and preview;
- lazy preview caching and invalidation by modification time;
- wide-character width, wrapping, clipping, and responsive layout calculations;
- navigation, preview scrolling, reload, quit, and selection state transitions;
- construction of the exact `codex resume <UUID>` process arguments.

A final smoke test runs the installed command's help and real read-only session listing path. It does not actually resume a session.

## Acceptance Criteria

The implementation is complete when it starts without third-party Python packages, lists the user's non-archived Codex CLI sessions in recency order, previews them smoothly with `j`/`k`, renders correctly in wide and narrow terminals with or without color, resumes the exact selected UUID on Enter, handles incompatible local storage without crashing, and passes the full automated test suite.

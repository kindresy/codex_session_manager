# Codex Session Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished, zero-dependency Python TUI that lists, previews, and resumes non-archived Codex CLI sessions.

**Architecture:** A read-only repository normalizes SQLite or JSONL session metadata, a lazy preview service parses only selected rollouts, and a curses view renders responsive split/stacked layouts. The CLI restores the terminal and replaces itself with `codex resume <UUID>` after selection.

**Tech Stack:** Python 3.10+, standard-library `sqlite3`, `json`, `curses`, `dataclasses`, `unittest`, and setuptools build metadata.

## Global Constraints

- Use no third-party runtime or test dependencies.
- Honor `$CODEX_HOME`, defaulting to `~/.codex`.
- Never modify Codex databases, rollouts, indexes, or configuration.
- Include only non-archived interactive CLI sessions; exclude archived, VS Code, and subagent sessions.
- Use the `codex-session` console command and `codex resume <full UUID>` for resume.
- Render colors when supported and remain usable in monochrome terminals.
- Keep Chinese and other wide characters aligned.

---

### Task 1: Package, Models, Time, and Display-Width Utilities

**Files:**
- Create: `pyproject.toml`
- Create: `src/codex_session_manager/__init__.py`
- Create: `src/codex_session_manager/models.py`
- Create: `src/codex_session_manager/text.py`
- Test: `tests/test_models_and_text.py`

**Interfaces:**
- Produces: `Session`, `Preview`, `normalize_epoch(value)`, `display_width(text)`, `clip_display(text, width)`, and `wrap_display(text, width)`.
- Consumes: no earlier project interfaces.

- [ ] **Step 1: Write failing model and text tests**

```python
import unittest
from datetime import datetime, timezone

from codex_session_manager.models import Session, normalize_epoch
from codex_session_manager.text import clip_display, display_width, wrap_display


class ModelAndTextTests(unittest.TestCase):
    def test_normalize_epoch_accepts_seconds_and_milliseconds(self):
        expected = datetime.fromtimestamp(1_700_000_000, timezone.utc)
        self.assertEqual(normalize_epoch(1_700_000_000), expected)
        self.assertEqual(normalize_epoch(1_700_000_000_000), expected)

    def test_session_short_id_and_directory(self):
        session = Session("12345678-abcd", "问题", "/tmp/work", 1.0, 2.0, "/tmp/a.jsonl")
        self.assertEqual(session.short_id, "12345678")
        self.assertEqual(session.directory_name, "work")

    def test_display_helpers_keep_chinese_aligned(self):
        self.assertEqual(display_width("ab中文"), 6)
        self.assertEqual(clip_display("ab中文cd", 7), "ab中文…")
        self.assertEqual(wrap_display("甲乙丙", 4), ["甲乙", "丙"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused tests and verify import failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_models_and_text -v`

Expected: FAIL because `codex_session_manager.models` does not exist.

- [ ] **Step 3: Add packaging, models, and width-aware text helpers**

Create `pyproject.toml` with setuptools package discovery under `src`, Python `>=3.10`, project name `codex-session-manager`, and console script `codex-session = codex_session_manager.cli:main`.

Implement immutable slotted data classes:

```python
@dataclass(frozen=True, slots=True)
class Session:
    id: str
    first_question: str
    cwd: str
    created_at: float
    last_opened_at: float
    rollout_path: str

    @property
    def short_id(self) -> str:
        return self.id[:8]

    @property
    def directory_name(self) -> str:
        return Path(self.cwd).name or self.cwd


@dataclass(frozen=True, slots=True)
class Preview:
    first_question: str
    latest_user: str
    latest_assistant: str
    error: str = ""
```

`normalize_epoch` returns a UTC `datetime`, dividing values greater than `10_000_000_000` by 1000. `text.py` uses `unicodedata.combining` and `unicodedata.east_asian_width` to count combining characters as zero and `W`/`F` characters as two. `clip_display` reserves one cell for `…`; `wrap_display` wraps without splitting combining sequences.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_models_and_text -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit the foundational types**

```bash
git add pyproject.toml src/codex_session_manager tests/test_models_and_text.py
git commit -m "feat: add session models and display helpers"
```

### Task 2: Read-Only SQLite Repository with JSONL Fallback

**Files:**
- Create: `src/codex_session_manager/repository.py`
- Test: `tests/test_repository.py`

**Interfaces:**
- Consumes: `Session` from `models.py`.
- Produces: `SessionRepository(codex_home: Path)`, `SessionRepository.list_sessions() -> list[Session]`, and `RepositoryError`.

- [ ] **Step 1: Write failing repository tests**

Build temporary SQLite fixtures with a `threads` table containing `id`, `rollout_path`, `created_at`, `updated_at`, `source`, `cwd`, `archived`, `first_user_message`, and `recency_at`. Assert that:

```python
sessions = SessionRepository(home).list_sessions()
self.assertEqual([item.id for item in sessions], ["cli-new", "cli-old"])
self.assertEqual(sessions[0].first_question, "最新问题")
```

Insert and verify exclusion of an archived CLI row, a `vscode` row, and a structured subagent `source`. Add a database missing the `threads` table plus two rollout fixtures and assert JSONL fallback still returns the valid CLI rollout while skipping a malformed file.

- [ ] **Step 2: Run repository tests and verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_repository -v`

Expected: FAIL because `codex_session_manager.repository` does not exist.

- [ ] **Step 3: Implement dynamic SQLite discovery and filtering**

Implement these private boundaries:

```python
class RepositoryError(RuntimeError):
    pass


class SessionRepository:
    def __init__(self, codex_home: Path):
        self.codex_home = codex_home

    def list_sessions(self) -> list[Session]:
        for database in self._database_candidates():
            try:
                sessions = self._read_database(database)
                if sessions:
                    return sessions
            except (sqlite3.Error, RepositoryError):
                continue
        return self._scan_rollouts()
```

Sort `state_*.sqlite` by modification time newest first. Connect with `sqlite3.connect(f"file:{quoted_path}?mode=ro", uri=True)`, inspect columns with `PRAGMA table_info(threads)`, select only available fields, and perform exact `source = 'cli'` and `COALESCE(archived, 0) = 0` filters when those columns exist. Reject empty first questions after normalization. Choose creation and recency fields in the order specified by the design, then sort normalized sessions by `(last_opened_at, created_at)` descending.

- [ ] **Step 4: Implement the JSONL fallback parser**

Scan `sessions/**/*.jsonl`. Parse each line independently, extracting `session_meta.payload.id/cwd/source` and `response_item.payload` messages. Accept only `source == "cli"`; ignore role values other than `user`; strip known injected blocks such as `<environment_context>...</environment_context>` and leading `# AGENTS.md instructions ...` content; retain the first non-empty genuine user text. Use the first record timestamp for creation and `stat().st_mtime` for fallback recency. Skip malformed sessions without failing the full scan.

- [ ] **Step 5: Run repository tests and the combined suite**

Run: `PYTHONPATH=src python3 -m unittest tests.test_repository -v`

Expected: all repository tests PASS.

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit repository support**

```bash
git add src/codex_session_manager/repository.py tests/test_repository.py
git commit -m "feat: discover codex sessions"
```

### Task 3: Lazy Conversation Preview Service

**Files:**
- Create: `src/codex_session_manager/preview.py`
- Test: `tests/test_preview.py`

**Interfaces:**
- Consumes: `Session` and `Preview` from `models.py`, plus the repository's genuine-user-text normalization helper.
- Produces: `PreviewService.get(session: Session) -> Preview`.

- [ ] **Step 1: Write failing preview extraction and cache tests**

Create a rollout containing developer content, tool output, two real user messages, and two assistant messages. Assert:

```python
preview = PreviewService().get(session)
self.assertEqual(preview.first_question, "第一条真实问题")
self.assertEqual(preview.latest_user, "最后一个问题")
self.assertEqual(preview.latest_assistant, "最后一个回答")
```

Patch the parser, call `get` twice without changing mtime, and assert one parse. Change mtime and assert a second parse. For malformed JSONL, assert `preview.error == "预览不可用"` and no exception escapes.

- [ ] **Step 2: Run preview tests and verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_preview -v`

Expected: FAIL because `codex_session_manager.preview` does not exist.

- [ ] **Step 3: Implement lazy parsing and mtime cache**

```python
class PreviewService:
    def __init__(self):
        self._cache: dict[str, tuple[int, Preview]] = {}

    def get(self, session: Session) -> Preview:
        path = Path(session.rollout_path)
        try:
            stamp = path.stat().st_mtime_ns
            cached = self._cache.get(str(path))
            if cached and cached[0] == stamp:
                return cached[1]
            preview = self._parse(path, session.first_question)
            self._cache[str(path)] = (stamp, preview)
            return preview
        except (OSError, ValueError, json.JSONDecodeError):
            return Preview(session.first_question, "", "", "预览不可用")
```

Parse only `response_item` message records. Gather clean `input_text` from genuine `user` messages and `output_text` from `assistant` messages. Use the final entry of each role for recent content and the session's normalized first question as the canonical first question.

- [ ] **Step 4: Run preview and full tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_preview -v`

Expected: all preview tests PASS.

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit preview support**

```bash
git add src/codex_session_manager/preview.py tests/test_preview.py
git commit -m "feat: add lazy session previews"
```

### Task 4: Responsive Curses TUI and Navigation

**Files:**
- Create: `src/codex_session_manager/tui.py`
- Test: `tests/test_tui.py`

**Interfaces:**
- Consumes: `SessionRepository.list_sessions()`, `PreviewService.get(Session)`, display helpers, `Session`, and `Preview`.
- Produces: `run_tui(repository, preview_service) -> str | None`, `ViewState.handle_key(key, count)`, and `calculate_layout(rows, cols) -> Layout`.

- [ ] **Step 1: Write failing pure-state and layout tests**

Assert `j`/Down and `k`/Up clamp selection, `g` and `G` jump, changing selection resets preview scroll, Ctrl-d/Ctrl-u and page keys clamp scroll, `q` returns a quit action, Enter returns a select action, and `r` returns reload. Assert `calculate_layout(40, 140)` is split, `calculate_layout(40, 80)` is stacked, and very small dimensions are marked too small.

- [ ] **Step 2: Run TUI tests and verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_tui -v`

Expected: FAIL because `codex_session_manager.tui` does not exist.

- [ ] **Step 3: Implement layout and view-state logic**

Use immutable `Layout` dimensions and a mutable `ViewState`:

```python
@dataclass(frozen=True, slots=True)
class Layout:
    mode: str
    list_rect: tuple[int, int, int, int]
    preview_rect: tuple[int, int, int, int]


@dataclass(slots=True)
class ViewState:
    selected: int = 0
    list_offset: int = 0
    preview_offset: int = 0

    def move(self, delta: int, count: int) -> None:
        before = self.selected
        self.selected = max(0, min(max(count - 1, 0), self.selected + delta))
        if self.selected != before:
            self.preview_offset = 0
```

Keep input-to-action mapping independently testable. Split mode starts at 110 columns; stacked mode requires at least 60 columns and 20 rows; smaller screens return `mode="small"`.

- [ ] **Step 4: Implement curses rendering and event loop**

Initialize `curs_set(0)`, `use_default_colors()`, and guarded color pairs. Render a title bar, bordered panes, a left header/rows, wrapped preview sections, and footer key hints. Use only bounds-checked `addnstr` calls so resize races do not crash. On `KEY_RESIZE`, redraw. On `r`, call the repository again while preserving the selected UUID when it still exists. On Enter, return the full selected ID. On q/Escape, return `None`.

- [ ] **Step 5: Run TUI and full tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_tui -v`

Expected: all TUI tests PASS.

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 6: Commit the TUI**

```bash
git add src/codex_session_manager/tui.py tests/test_tui.py
git commit -m "feat: add responsive session browser"
```

### Task 5: CLI Resume Integration, Documentation, and End-to-End Verification

**Files:**
- Create: `src/codex_session_manager/cli.py`
- Create: `src/codex_session_manager/__main__.py`
- Create: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `SessionRepository`, `PreviewService`, and `run_tui`.
- Produces: `main(argv: Sequence[str] | None = None) -> int` and `resume_command(session_id) -> NoReturn`.

- [ ] **Step 1: Write failing CLI tests**

Patch `curses.wrapper`, `shutil.which`, and `os.execvp`. Assert `--help` exits successfully, `--codex-home PATH` overrides the environment, a missing `codex` binary still opens the browser with a resume error, quitting returns zero, and selection calls exactly:

```python
mock_execvp.assert_called_once_with(
    "codex", ["codex", "resume", "12345678-abcd"]
)
```

- [ ] **Step 2: Run CLI tests and verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_cli -v`

Expected: FAIL because `codex_session_manager.cli` does not exist.

- [ ] **Step 3: Implement argument parsing and process handoff**

Use `argparse` with `--codex-home` and `--no-color`. Resolve the home in the order explicit flag, `CODEX_HOME`, then `~/.codex`. Check `shutil.which("codex")` before entering curses and pass a transient resume error when unavailable, while retaining browse/preview support. Construct the repository and preview service, call `curses.wrapper`, and use `os.execvp("codex", ["codex", "resume", selected_id])` only when an ID is returned. Catch initialization failures, print a concise Chinese error to stderr, and return a nonzero status.

Add `__main__.py`:

```python
from .cli import main

raise SystemExit(main())
```

- [ ] **Step 4: Document installation and key bindings**

Document Python 3.10+, editable installation with `python3 -m pip install -e .`, direct source execution with `PYTHONPATH=src python3 -m codex_session_manager`, data-source behavior, all keys, `CODEX_HOME`, read-only guarantees, and the SQLite-to-JSONL fallback.

- [ ] **Step 5: Run unit, packaging, and real-data smoke tests**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`

Expected: all tests PASS.

Run: `python3 -m pip install --no-deps --target /tmp/codex-session-manager-install-test .`

Expected: wheel builds and installs successfully without downloading runtime dependencies.

Run: `PYTHONPATH=src python3 -m codex_session_manager --help`

Expected: help includes `--codex-home` and `--no-color`.

Run a read-only repository smoke command against the real `~/.codex` and assert at least one CLI session is returned; print only the count and first eight ID characters. Do not start or resume Codex.

- [ ] **Step 6: Commit CLI and documentation**

```bash
git add src/codex_session_manager/cli.py src/codex_session_manager/__main__.py tests/test_cli.py README.md
git commit -m "feat: ship codex session manager"
```

- [ ] **Step 7: Final repository checks**

Run: `git diff --check`

Expected: no output.

Run: `git status --short --branch`

Expected: clean branch after committing the completed implementation plan and implementation commits.

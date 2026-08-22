# Session Metadata Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/` metadata search with wrapped `n/N` navigation to the curses session browser.

**Architecture:** Add a pure matcher and a small `SearchState` beside `ViewState`, then route Unicode keys through an event-loop search-input mode. Keep the loaded session list unchanged and update only the selected index, preview offset, footer, and search state.

**Tech Stack:** Python 3.10–3.13 standard library, curses, dataclasses, unittest.

## Global Constraints

- Search only first question, full session ID, and working directory already present in `Session`.
- Matching uses case-insensitive Unicode substring comparison through `str.casefold()`.
- No rollout transcript reads, fuzzy matching, filtering, or new runtime dependency.
- Preserve existing Linux, macOS, WSL, and SSH Linux support and native Windows limitation.
- Preserve all existing navigation, preview, reload, resume, and quit behavior outside search-input mode.

---

### Task 1: Search Model and Navigation

**Files:**
- Modify: `src/codex_session_manager/tui.py`
- Test: `tests/test_tui.py`

**Interfaces:**
- Consumes: `Session.id`, `Session.first_question`, and `Session.cwd`.
- Produces: `find_session_matches(sessions: list[Session], query: str) -> tuple[int, ...]` and `SearchState` with `activate`, `next`, and `clear` behavior.

- [ ] **Step 1: Write failing pure search tests**

Add tests that construct sessions with mixed-case IDs, Chinese questions, and paths, then require:

```python
self.assertEqual(find_session_matches(sessions, "修复"), (1, 3))
self.assertEqual(find_session_matches(sessions, "ABCDEF"), (0,))
self.assertEqual(find_session_matches(sessions, "project-x"), (2,))
self.assertEqual(find_session_matches(sessions, ""), ())
```

Add `SearchState` tests requiring activation to choose the first match strictly after the current selection with wrapping, `next(..., 1)`/`next(..., -1)` to wrap in both directions, no-match activation to preserve the selection, and `clear()` to reset query and matches.

- [ ] **Step 2: Run focused tests and observe failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_tui.SearchTests -v
```

Expected: import failure because `SearchState` and `find_session_matches` do not exist.

- [ ] **Step 3: Implement the pure matcher and state**

Implement the following public behavior in `tui.py`:

```python
def find_session_matches(sessions: list[Session], query: str) -> tuple[int, ...]:
    needle = query.casefold()
    if not needle:
        return ()
    return tuple(
        index
        for index, session in enumerate(sessions)
        if needle in "\n".join((session.id, session.first_question, session.cwd)).casefold()
    )

@dataclass(slots=True)
class SearchState:
    query: str = ""
    matches: tuple[int, ...] = ()

    def activate(self, query: str, sessions: list[Session], selected: int) -> int | None:
        self.query = query
        self.matches = find_session_matches(sessions, query)
        if not self.matches:
            return None
        return next((index for index in self.matches if index > selected), self.matches[0])

    def next(self, selected: int, direction: int) -> int | None:
        if not self.matches:
            return None
        if direction >= 0:
            return next((index for index in self.matches if index > selected), self.matches[0])
        return next(
            (index for index in reversed(self.matches) if index < selected),
            self.matches[-1],
        )

    def clear(self) -> None:
        self.query = ""
        self.matches = ()
```

`activate` stores the non-empty query and match tuple, returns the first index greater than `selected` or wraps to the first match, and returns `None` when empty or unmatched. `next` returns the next/previous match relative to the current index with circular wrapping even when the current selection is not itself a match.

- [ ] **Step 4: Run focused and full tests**

Run the focused command from Step 2, then:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the search model**

```bash
git add src/codex_session_manager/tui.py tests/test_tui.py
git commit -m "feat: add session metadata matching"
```

---

### Task 2: Curses Search Input and Documentation

**Files:**
- Modify: `src/codex_session_manager/tui.py`
- Modify: `tests/test_tui.py`
- Modify: `README.md`
- Modify: `tests/test_release_assets.py`

**Interfaces:**
- Consumes: `SearchState`, `find_session_matches`, `ViewState.move`, and the existing event loop.
- Produces: `/` input mode, Enter/Esc/Backspace handling, `n/N` actions, search status footer, and documented controls.

- [ ] **Step 1: Write failing key-routing and event-loop tests**

Extend `ViewState.handle_key` tests to require:

```python
self.assertEqual(state.handle_key("/", 3, 0), "search")
self.assertEqual(state.handle_key("n", 3, 0), "next_match")
self.assertEqual(state.handle_key("N", 3, 0), "previous_match")
```

Add fake-screen event-loop tests using `get_wch()` sequences for:

```python
("/", "问", "题", "\n", "\n")       # search then resume matched session
("/", "x", "\n", "q")              # no match leaves selection unchanged
("/", "a", "b", "\x7f", "c", "\n", "q")  # Backspace edits query
("/", "x", "\x1b", "q")           # Esc cancels input
("/", "x", "\n", "r", "n", "q") # reload clears matches
```

Patch drawing functions and assert selected IDs, status messages, and query/match clearing rather than asserting terminal pixels.

- [ ] **Step 2: Run focused tests and observe failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_tui.ViewStateTests tests.test_tui.SearchEventLoopTests -v
```

Expected: failures because string key routing and search-input mode are absent.

- [ ] **Step 3: Implement Unicode input mode and wrapped navigation**

Change the event loop to use `stdscr.get_wch()` so printable Unicode characters arrive as strings. Update `ViewState.handle_key` to accept `int | str` and return `search`, `next_match`, or `previous_match` for `/`, `n`, and `N`.

Maintain:

```python
search = SearchState()
search_input: str | None = None
```

While `search_input is not None`, route Enter, Esc, Backspace variants (`curses.KEY_BACKSPACE`, `127`, `8`, `"\x7f"`, `"\b"`), and printable characters before ordinary navigation. Confirming a non-empty query activates search and uses `ViewState.move(target - state.selected, len(sessions))`; no matches show `未找到：query`. Outside input mode, `n/N` call `search.next`, `/` starts with an empty buffer, and reload calls `search.clear()`.

Update footer help to include `/ 搜索  n/N 匹配`, render `/{search_input}` during input, and use a normal title/time color rather than the error color for the prompt.

- [ ] **Step 4: Document the controls and lock the README contract**

Add the following rows to the README key table:

```markdown
| `/` | 输入关键词，搜索首问、完整 session ID 和工作目录 |
| `n` / `N` | 跳到下一个 / 上一个搜索结果 |
```

State that matching is case-insensitive substring matching and does not scan full conversation content. Extend `test_readme_public_usage` to require `/`, `n` / `N`, and the three search fields.

- [ ] **Step 5: Run feature and regression tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_tui tests.test_release_assets -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

Expected: all commands exit zero.

- [ ] **Step 6: Commit the TUI and documentation**

```bash
git add src/codex_session_manager/tui.py tests/test_tui.py README.md tests/test_release_assets.py
git commit -m "feat: add interactive session search"
```

---

### Task 3: Release and Real-Data Verification

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: completed source tree and existing distribution verifier.
- Produces: release evidence for source, sdist, installed wheel, and real local Codex sessions.

- [ ] **Step 1: Run distribution verification**

```bash
python3 -m build
python3 tests/verify_distribution.py dist/*.whl dist/*.tar.gz
```

Expected: wheel and sdist are both reported as verified.

- [ ] **Step 2: Test the extracted sdist and installed wheel**

Run:

```bash
python3 -m tarfile -e dist/codex_session_manager-0.1.0.tar.gz /tmp/codex-session-search-sdist-20260822
cd /tmp/codex-session-search-sdist-20260822/codex_session_manager-0.1.0
PYTHONPATH=src python3 -m unittest discover -s tests -v
cd /tmp/codex-session-manager
python3 -m pip install --no-deps --target /tmp/codex-session-search-wheel-20260822 dist/codex_session_manager-0.1.0-py3-none-any.whl
PYTHONPATH=/tmp/codex-session-search-wheel-20260822 /tmp/codex-session-search-wheel-20260822/bin/codex-session --help
PYTHONPATH=/tmp/codex-session-search-wheel-20260822 /tmp/codex-session-search-wheel-20260822/bin/codex-session --version
```

Expected: all commands exit zero and report version `0.1.0`.

- [ ] **Step 3: Run read-only real-session search smoke test**

Load sessions through `SessionRepository(Path.home() / ".codex")`, search a substring taken from an existing session's first question through `find_session_matches`, and assert at least one match without printing conversation text.

Expected: a positive match count and no Codex data writes.

- [ ] **Step 4: Review and repository checks**

Request an independent read-only review of the design-to-HEAD diff. Fix all Critical and Important findings, then run:

```bash
git diff --check
git status --short --branch
git remote -v
```

Expected: clean `master`, canonical `origin`, and no unpushed source changes.

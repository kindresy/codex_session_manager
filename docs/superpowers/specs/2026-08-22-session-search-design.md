# Session Metadata Search Design

## Goal

Add Vim-style metadata search to the Codex session browser so users can quickly locate a session without changing the existing list, preview, or resume workflows.

## Scope

Search only data already loaded in each `Session`:

- first question;
- full session ID;
- working directory.

Do not read complete rollout transcripts during search. Matching is a case-insensitive Unicode substring comparison. Fuzzy matching and result filtering are out of scope.

## Interaction

- `/` enters search-input mode and displays `/query` in the footer.
- Printable characters append to the query; Backspace removes one character.
- Enter confirms a non-empty query and jumps to the first matching session after the current selection, wrapping at the end.
- Esc cancels input and leaves the selection unchanged.
- `n` jumps to the next match and `N` to the previous match, both wrapping across the list boundary.
- An empty query confirmed with Enter performs no search.
- A query with no matches leaves the selection unchanged and displays `未找到：query`.
- Starting a new search replaces the previous query and match set.
- Reloading with `r` clears the active query and match set because list indices may have changed.

Existing `j/k`, arrow, preview scrolling, `g/G`, Enter-to-resume, and quit controls keep their current behavior outside search-input mode.

## Architecture

Keep search state separate from curses drawing:

- `SearchState` owns the active query and matching session indices.
- A pure metadata-matching helper returns match indices for a query.
- `ViewState` continues to own selection and scrolling; search navigation updates it through a selection method that resets preview scrolling.
- The event loop owns the temporary input buffer and routes keys differently while search-input mode is active.
- The footer renders the input prompt, match status, or ordinary shortcut help.

Search navigation is index-based because the session list is stable between reloads. Reload explicitly clears search state before accepting further `n/N` navigation.

## Error and Edge Cases

- Search with no sessions is accepted but reports no match without crashing.
- A deleted or refreshed list cannot leave stale match indices because reload clears search state.
- Unicode questions and paths are matched with `str.casefold()`.
- Backspace recognizes terminal Backspace variants.
- Terminal resize and small-terminal mode do not alter search semantics; the footer remains the input surface.

## Testing

Add unit tests for:

- metadata matching across question, full ID, and directory;
- case-insensitive Unicode matching;
- forward and reverse wrapped navigation;
- no-match and empty-query behavior;
- input editing, confirmation, and cancellation in the event loop;
- reload clearing search state;
- footer/help and README key documentation.

Run the complete unittest suite, compile checks, distribution build and validation, installed-wheel CLI smoke tests, and a read-only real-session discovery smoke test.

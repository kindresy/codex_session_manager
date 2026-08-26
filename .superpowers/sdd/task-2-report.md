# Task 2: Cloud configuration and HTTP API client

## TDD record

- **RED:** Added `tests/test_cloud_client.py`, then ran
  `PYTHONPATH=src python3 -m unittest tests.test_cloud_client -v`.
  It failed with `ModuleNotFoundError: No module named 'codex_session_manager.cloud_client'`.
- **GREEN:** Added `cloud_client.py` with configuration round trips, atomic UTF-8 writes, normalized Worker URLs, UTF-8 JSON requests, encoded session IDs, Bearer authorization, schema-version checks, and user-facing `CloudError` failures. The focused suite passed: 9 tests.

## Verification

- Focused: `PYTHONPATH=src python3 -m unittest tests.test_cloud_client -v` — 9 passed.
- Full Python suite: `PYTHONPATH=src python3 -m unittest discover -s tests -v` — 145 passed.
- Self-review: inspected the new module and tests; `python3 -m compileall -q src tests` completed successfully.

## Scope and concerns

- Only Task 2 files were added: `src/codex_session_manager/cloud_client.py` and `tests/test_cloud_client.py`.
- No known concerns.

## Review fixes (2026-08-26)

### TDD record

- **RED:** Added focused regression tests, then ran
  `PYTHONPATH=src python3 -m unittest tests.test_cloud_client -v`.
  Result: 15 tests ran; 4 failures and 3 errors. The failures showed that a
  302 redirect was followed, `delete_session` accepted schema version 2, and
  Worker URLs with a query or fragment were accepted. The errors showed raw
  `UnicodeDecodeError` and `OSError` escaping configuration I/O, including a
  cleanup error masking an `os.replace` error.
- **GREEN:** Used a `urllib` redirect handler that declines every redirect,
  made all configuration read/write filesystem paths raise `CloudError`,
  preserved the original write error if temporary cleanup fails, validated
  delete responses through the existing schema checker, and rejected Worker
  URLs containing a query or fragment. The focused suite passed: 15 tests.

### Verification

- Focused: `PYTHONPATH=src python3 -m unittest tests.test_cloud_client -v` —
  15 passed.
- Full Python suite: `PYTHONPATH=src python3 -m unittest discover -s tests -v`
  — 151 passed.

### Scope and concerns

- Changed only `src/codex_session_manager/cloud_client.py` and
  `tests/test_cloud_client.py`, plus this requested review record.
- The redirect regression uses a distinct local host endpoint and asserts it
  receives no request, so its Bearer token cannot be forwarded.
- No known concerns.

### Review follow-up TDD record

- **RED:** A pre-commit review found two untested edge cases. Added a focused
  test for bare `?` and `#` URL separators and a test for an invalid Unicode
  surrogate during configuration writing, then ran
  `PYTHONPATH=src python3 -m unittest tests.test_cloud_client -v`. Result: 16
  tests ran; 2 failures (bare URL separators accepted) and 1 error (raw
  `UnicodeEncodeError` escaped).
- **GREEN:** Rejected URLs containing either separator and included
  `UnicodeError` in the existing save/cleanup error boundary. The focused
  command passed: 16 tests.
- **Full suite:** `PYTHONPATH=src python3 -m unittest discover -s tests -v` —
  152 passed.

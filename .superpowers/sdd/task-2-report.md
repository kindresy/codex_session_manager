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

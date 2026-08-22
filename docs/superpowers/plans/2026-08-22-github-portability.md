# GitHub Portability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Codex Session Manager publicly cloneable and installable from `kindresy/codex_session_manager` on Linux, macOS, and WSL without source changes.

**Architecture:** Preserve the standard-library runtime and POSIX curses implementation. Add complete distribution metadata, synthetic cross-version storage fixtures, an eight-job GitHub Actions matrix, and user-facing installation/troubleshooting documentation.

**Tech Stack:** Python 3.10–3.13, setuptools, unittest, GitHub Actions, POSIX curses, SQLite, JSONL.

## Global Constraints

- Official platforms: Linux, macOS, WSL, and SSH Linux; native Windows is unsupported.
- Runtime dependencies remain empty.
- License: MIT, copyright 2026 kindresy.
- Canonical repository: `https://github.com/kindresy/codex_session_manager`.
- Tests use synthetic data only and never require a Codex account.
- No real session, authentication, or machine-specific private data may be committed.
- Configure `origin` but do not push.

---

### Task 1: License, Distribution Metadata, and Version CLI

**Files:**
- Create: `LICENSE`
- Modify: `pyproject.toml`
- Modify: `src/codex_session_manager/cli.py`
- Test: `tests/test_cli.py`
- Create: `tests/test_release_assets.py`

**Interfaces:**
- Consumes: `codex_session_manager.__version__`.
- Produces: `codex-session --version`, complete PEP 621 project metadata, and MIT licensing.

- [ ] **Step 1: Add failing version and metadata tests**

Add a CLI test that captures stdout from `main(["--version"])`, expects `SystemExit(0)`, and asserts output equals `codex-session 0.1.0`. Add release-asset tests that read `pyproject.toml` and assert it contains `readme = "README.md"`, `license = { file = "LICENSE" }`, author `kindresy`, no dependencies, the canonical repository and issue URLs, POSIX classifiers, and Python 3.10–3.13 classifiers. Assert `LICENSE` includes `MIT License`, `Copyright (c) 2026 kindresy`, and the standard permission and warranty paragraphs.

- [ ] **Step 2: Run focused tests and observe failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_cli.CliTests.test_version_exits_successfully tests.test_release_assets.ReleaseAssetTests.test_project_metadata tests.test_release_assets.ReleaseAssetTests.test_mit_license -v`

Expected: FAIL because `--version`, metadata, and LICENSE are absent.

- [ ] **Step 3: Implement license, metadata, and version flag**

Add the standard MIT License text. Extend `[project]` with:

```toml
readme = "README.md"
license = { file = "LICENSE" }
authors = [{ name = "kindresy" }]
keywords = ["codex", "openai", "session", "tui", "cli"]
classifiers = [
  "Development Status :: 3 - Alpha",
  "Environment :: Console :: Curses",
  "License :: OSI Approved :: MIT License",
  "Operating System :: MacOS",
  "Operating System :: POSIX :: Linux",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Utilities",
]

[project.urls]
Homepage = "https://github.com/kindresy/codex_session_manager"
Repository = "https://github.com/kindresy/codex_session_manager"
Issues = "https://github.com/kindresy/codex_session_manager/issues"

[tool.setuptools]
include-package-data = false
```

Import `__version__` in `cli.py` and add `parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")`.

- [ ] **Step 4: Run focused and full tests**

Run the focused command from Step 2, then `PYTHONPATH=src python3 -m unittest discover -s tests -v`.

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add LICENSE pyproject.toml src/codex_session_manager/cli.py tests/test_cli.py tests/test_release_assets.py
git commit -m "chore: add public release metadata"
```

### Task 2: Synthetic Codex Compatibility Fixtures

**Files:**
- Create: `tests/fixtures/current_schema.sql`
- Create: `tests/fixtures/minimal_schema.sql`
- Create: `tests/fixtures/fallback/rollout-2026-08-22T20-05-43-fixture.jsonl`
- Create: `tests/fixtures/mixed-context.jsonl`
- Create: `tests/fixture_loader.py`
- Create: `tests/test_compatibility_fixtures.py`

**Interfaces:**
- Consumes: `SessionRepository.list_sessions()`, `clean_user_text()`, and `PreviewService.get()`.
- Produces: reusable `load_sql_fixture(home, name)` and `copy_rollout_fixture(home, relative_path)` helpers.

- [ ] **Step 1: Write failing fixture-driven compatibility tests**

Tests must load committed files and assert:

```python
current = load_sql_fixture(home, "current_schema.sql")
self.assertEqual([item.id for item in current], ["cli-current"])

minimal = load_sql_fixture(home, "minimal_schema.sql")
self.assertEqual(minimal[0].first_question, "minimal question")

fallback = load_fallback_fixture(home)
self.assertEqual(fallback[0].id, "fixture-fallback")
self.assertEqual(fallback[0].first_question, "fixture real prompt")
```

The current fixture includes one valid CLI row and excluded archived, VS Code, and structured subagent rows. The minimal fixture omits millisecond and recency columns. The fallback fixture includes an incompatible database, filename timestamp fallback, and mixed injected context. The preview fixture includes deterministic latest user and assistant messages.

- [ ] **Step 2: Run fixture tests and observe missing-file failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_compatibility_fixtures -v`

Expected: FAIL because fixture assets and loader do not exist.

- [ ] **Step 3: Add synthetic fixture assets and loader**

SQL fixtures create and populate `threads` with public synthetic UUIDs and `/tmp/fixture` paths. JSONL fixture records use `session_meta` plus `response_item` user/assistant messages and contain no user data. `fixture_loader.py` copies JSONL into a `TemporaryDirectory`, executes SQL with `sqlite3.Connection.executescript`, and always returns sessions through the public repository API.

- [ ] **Step 4: Run fixture and full test suites**

Run: `PYTHONPATH=src python3 -m unittest tests.test_compatibility_fixtures -v`

Expected: all fixture tests PASS.

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add tests/fixtures tests/fixture_loader.py tests/test_compatibility_fixtures.py
git commit -m "test: add codex storage compatibility fixtures"
```

### Task 3: GitHub Actions Portability Matrix

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `.gitignore`
- Modify: `tests/test_release_assets.py`

**Interfaces:**
- Consumes: package build and unittest commands.
- Produces: push/PR CI across Ubuntu/macOS and Python 3.10–3.13.

- [ ] **Step 1: Add failing workflow and hygiene tests**

Read `.github/workflows/ci.yml` as text and assert it declares `ubuntu-latest`, `macos-latest`, quoted versions `3.10`, `3.11`, `3.12`, `3.13`, `fail-fast: false`, unittest discovery, compileall, `python -m build`, wheel installation, `codex-session --help`, and `codex-session --version`. Assert `.gitignore` covers `.venv/`, `venv/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `htmlcov/`, `build/`, `dist/`, `*.egg-info/`, and `__pycache__/`.

- [ ] **Step 2: Run workflow tests and observe failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_release_assets.ReleaseAssetTests.test_ci_matrix tests.test_release_assets.ReleaseAssetTests.test_gitignore_release_artifacts -v`

Expected: FAIL because workflow and ignore entries are missing.

- [ ] **Step 3: Implement the workflow and ignore rules**

Create a workflow triggered by `push` and `pull_request` with:

```yaml
strategy:
  fail-fast: false
  matrix:
    os: [ubuntu-latest, macos-latest]
    python-version: ["3.10", "3.11", "3.12", "3.13"]
```

Use `actions/checkout@v4`, `actions/setup-python@v5`, upgrade pip, install `build`, run tests and compileall, build wheel/sdist, install the wheel into the job environment, then run help and version. Add the exact cache/build patterns to `.gitignore`.

- [ ] **Step 4: Run focused and full tests**

Run the focused command from Step 2, then the complete unittest suite.

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add .github/workflows/ci.yml .gitignore tests/test_release_assets.py
git commit -m "ci: test supported python platforms"
```

### Task 4: Public README, Build, and Repository Verification

**Files:**
- Modify: `README.md`
- Modify: `tests/test_release_assets.py`

**Interfaces:**
- Consumes: supported-platform, installation, CLI, and troubleshooting behavior.
- Produces: clone/install instructions requiring no source edits and release verification evidence.

- [ ] **Step 1: Add failing README contract tests**

Assert README contains canonical GitHub install URL, clone + virtualenv + `pip install .`, direct source execution, development editable install, Linux/macOS/WSL support, native Windows unsupported/WSL guidance, Python 3.10+, UTF-8/curses requirements, `$CODEX_HOME`, read-only guarantee, internal-format warning, troubleshooting for missing Codex and empty sessions, issue-report version information, and all key bindings.

- [ ] **Step 2: Run README tests and observe failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_release_assets.ReleaseAssetTests.test_readme_public_usage -v`

Expected: FAIL because public installation, platform, and troubleshooting sections are incomplete.

- [ ] **Step 3: Rewrite README for public users**

Organize README as Overview, Features, Supported Platforms, Requirements, Install from GitHub, Install from Clone, Run from Source, Usage/Keys, Configuration, Data Compatibility and Privacy, Troubleshooting, Development, and Issue Reporting. Commands must be directly copyable and use `https://github.com/kindresy/codex_session_manager.git`.

- [ ] **Step 4: Configure the canonical remote without pushing**

Run: `git remote add origin https://github.com/kindresy/codex_session_manager.git`

If `origin` exists, verify it exactly matches; update only when it differs. Do not run `git push`.

- [ ] **Step 5: Run final local release verification**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
python3 -m build
python3 -m pip install --no-deps --target /tmp/codex-session-manager-release-test dist/*.whl
PYTHONPATH=/tmp/codex-session-manager-release-test /tmp/codex-session-manager-release-test/bin/codex-session --help
PYTHONPATH=/tmp/codex-session-manager-release-test /tmp/codex-session-manager-release-test/bin/codex-session --version
```

Inspect the wheel and sdist archives. Assert that the wheel contains LICENSE, all package modules, and the README as its Markdown long description in `METADATA`; assert that the sdist contains README, LICENSE, all package modules, and every file required to run its included tests. Run the tests from the extracted sdist and the real read-only local session discovery smoke test. Expected: every command exits 0.

- [ ] **Step 6: Commit documentation and verify repository state**

```bash
git add README.md tests/test_release_assets.py
git commit -m "docs: prepare github release"
git diff --check
git status --short --branch
git remote -v
```

Expected: clean branch and `origin` pointing to `https://github.com/kindresy/codex_session_manager.git`; no push performed.

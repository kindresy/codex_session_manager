# GitHub Portability Design

## Goal

Prepare Codex Session Manager for public use from `https://github.com/kindresy/codex_session_manager`. A new user on a supported platform must be able to clone or install the project and run it without changing source code.

## Supported Platforms

Version 0.1.0 officially supports:

- Linux
- macOS
- Windows Subsystem for Linux
- Linux hosts reached through SSH

Native Windows is explicitly unsupported because Python does not bundle `curses` there. The first public release retains zero third-party runtime dependencies rather than adding `windows-curses` or replacing the TUI framework.

Python 3.10 through 3.13 are supported. The terminal must support UTF-8. Color is optional because the TUI already has a monochrome mode.

## Licensing and Repository Identity

The project uses the MIT License with copyright holder `kindresy` and year 2026.

Project metadata uses these canonical links:

- Homepage and repository: `https://github.com/kindresy/codex_session_manager`
- Issues: `https://github.com/kindresy/codex_session_manager/issues`

The local repository will receive an `origin` remote pointing to the canonical repository. Implementation will not push without separate authorization.

## Packaging

`pyproject.toml` remains setuptools-based with a `src` layout, Python `>=3.10`, and no runtime dependencies. It gains:

- README and license metadata;
- author, keywords, classifiers, and project URLs;
- explicit package-data policy;
- a `codex-session` console entry point;
- metadata sufficient for a correctly named wheel and source distribution.

The CLI gains `--version`, sourced from the package's single `__version__` value.

End-user installation documentation prefers an isolated virtual environment and `pip install .`. Development documentation uses `pip install -e .`. Direct source execution remains available with `PYTHONPATH=src python3 -m codex_session_manager`.

## README and User Experience

The README will document:

- supported and unsupported platforms;
- installation from GitHub, from a clone, and direct source execution;
- normal use, all key bindings, and color behavior;
- `$CODEX_HOME` and `--codex-home` overrides;
- the read-only SQLite-first and JSONL-fallback design;
- the fact that Codex storage is internal and may evolve;
- troubleshooting for missing `codex`, `curses`, UTF-8 terminals, and empty session lists;
- issue-report information: operating system, Python version, `codex --version`, and the tool version;
- development test and build commands.

Native Windows users will be directed to WSL.

## Compatibility Fixtures

Repository tests will use committed, synthetic fixtures rather than real user sessions. Fixtures contain no credentials or personal conversation content and cover:

- a representative current SQLite `threads` schema;
- an older/minimal SQLite schema without optional timestamp fields;
- an incompatible SQLite database that triggers JSONL fallback;
- JSONL with session-meta timestamps;
- JSONL requiring rollout-filename creation-time fallback;
- injected AGENTS/environment context mixed with a genuine prompt;
- CLI, archived, VS Code, and structured subagent records.

Fixture loaders copy database templates into temporary directories before opening them so tests remain isolated and read-only with respect to tracked files.

## Continuous Integration

GitHub Actions runs on pushes and pull requests. The test matrix contains:

- Ubuntu with Python 3.10, 3.11, 3.12, and 3.13;
- macOS with Python 3.10, 3.11, 3.12, and 3.13.

Every matrix job runs:

1. unit-test discovery;
2. bytecode compilation;
3. standards-based wheel build;
4. installation into an isolated target;
5. installed `codex-session --help` and `--version` smoke tests.

The workflow does not require a Codex account, network access beyond normal Python build tooling, or access to `~/.codex`.

## Repository Hygiene

`.gitignore` will cover Python caches, virtual environments, coverage data, build directories, distributions, and egg metadata. Generated artifacts currently present in the working directory remain ignored and are not committed.

The repository will include only source, tests, synthetic fixtures, documentation, workflows, and license files. No real session data, authentication material, or machine-specific absolute path is allowed in tracked release assets, except paths used illustratively in documentation or tests.

## Error Handling

Platform constraints are reported through documentation and packaging classifiers. Unsupported native Windows is not silently advertised as supported.

The existing runtime behavior remains:

- missing Codex storage produces an empty-state UI;
- missing `codex` still permits browsing and shows an in-TUI resume error;
- incompatible SQLite falls back to JSONL;
- malformed session files do not abort the full session list;
- no Codex file is modified.

## Testing and Acceptance Criteria

The release-readiness work is complete when:

- all existing and new unit tests pass locally;
- synthetic compatibility fixtures exercise both SQLite and JSONL paths;
- wheel and source distributions contain the package, README, and LICENSE;
- an installed console script prints help and version;
- the CI workflow defines all eight OS/Python combinations;
- README commands work without source modifications;
- real local Codex discovery still succeeds through a read-only smoke test;
- `git diff --check` passes and the working tree is clean;
- `origin` points to `https://github.com/kindresy/codex_session_manager.git`;
- no push occurs during implementation.

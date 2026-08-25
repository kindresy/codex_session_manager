# Linux Standalone Distribution Design

## Goal

Allow users on Linux and WSL x86_64 to install and run Codex Session Manager without installing or upgrading Python, pip, virtual environments, setuptools, or other Python build tooling.

The initial compatibility baseline is Ubuntu 20.04 and glibc 2.31. The same release artifact must also run on Ubuntu 22.04 and Ubuntu 24.04. Native Windows, macOS, Linux ARM64, and Linux distributions using musl libc are outside this change.

The existing Python package, Git-based pip installation, and editable development installation remain supported. The standalone distribution becomes the recommended installation method for non-developers.

## Distribution Format

Each tagged GitHub release publishes these assets with stable names:

- `codex-session-manager-linux-x86_64.tar.gz`
- `codex-session-manager-linux-x86_64.tar.gz.sha256`
- `install.sh`

The archive is a PyInstaller directory-mode distribution containing the Python interpreter, standard library, application modules, and executable entry point. Directory mode is preferred over one-file mode because it avoids extracting the application to a temporary executable directory on every launch and remains usable when `/tmp` is mounted with `noexec`.

Manual download and extraction must remain a supported execution path. The installer improves convenience but is not required to launch the archive contents.

## Installation Layout

The default installation uses only the current user's home directory:

```text
~/.local/lib/codex-session-manager/
├── versions/
│   └── 0.1.0/
└── current -> versions/0.1.0

~/.local/bin/
└── codex-session -> ../lib/codex-session-manager/current/codex-session
```

The installer accepts `--prefix PATH` to replace `~/.local` and `--version vX.Y.Z` to select a release. Without `--version`, it installs the latest stable GitHub release.

Installation never requires `sudo` and never modifies the system Python installation. If the selected prefix's `bin` directory is absent from `PATH`, the installer prints an exact shell configuration hint but does not edit shell startup files.

## Installer Flow

The installer performs these operations in order:

1. Require Linux and accept the `x86_64` or `amd64` architecture spelling.
2. Check for the required download, archive, and checksum utilities.
3. Resolve the requested release and its stable asset URLs.
4. Create a private temporary directory with `mktemp` and register cleanup on exit.
5. Download the archive and checksum file over HTTPS.
6. Verify the archive with SHA-256 before extraction.
7. Extract into a staging directory under the target prefix.
8. Verify the staged executable reports the expected version.
9. Move the completed version directory into `versions/`.
10. Atomically replace the `current` symbolic link.
11. Create or update the command link in the prefix's `bin` directory.
12. Retain the newly installed version and the immediately previous version, then remove older managed versions.

Repeating installation of the same version is idempotent. Download, checksum, extraction, or smoke-test failures leave the current installation untouched.

The installer refuses to overwrite a regular file or symbolic link at `bin/codex-session` unless it can establish that the path belongs to this installation. A path collision produces an actionable error rather than silently replacing user data.

Users upgrade by running the installer again. The retained previous directory provides a manual rollback target by repointing `current`. Uninstallation is documented as removing the managed command link and application directory; no privileged or system-wide cleanup is necessary.

## Build Environment

PyInstaller does not bundle glibc, and Linux glibc compatibility is forward rather than backward. The standalone application must therefore be built against a glibc version no newer than the oldest supported target.

GitHub's hosted Ubuntu 20.04 runner is retired, so the workflow runs on a current GitHub-hosted Linux runner and executes the build in a pinned x86_64 container. The container uses a Python 3.10 Debian Bullseye base with glibc 2.31, pinned by immutable image digest. The PyInstaller version and all standalone-build dependencies are also pinned.

The repository provides one build script used by both developers and CI. It:

1. runs the Python test suite;
2. invokes the checked-in PyInstaller specification in directory mode;
3. checks the executable's help and version output;
4. creates the release archive with stable ownership and path names;
5. emits the SHA-256 checksum; and
6. rejects archives containing caches, test sessions, credentials, or build-host absolute paths.

No runtime behavior changes are required. The existing `codex-session` entry point remains the standalone executable's entry point.

## Release Workflow

A dedicated GitHub Actions workflow handles standalone releases:

- Pull requests and ordinary branch pushes build and test the standalone artifact without publishing it.
- A `vX.Y.Z` tag runs the complete build and compatibility matrix, then creates or updates the corresponding GitHub Release only after every required job succeeds.
- The tag version must exactly match the package's `__version__` value.
- Release assets use the stable filenames defined above so the latest-release installer URL remains stable.
- The publishing job receives only the required `contents: write` permission. All other jobs use read-only repository permissions.
- A failed build or compatibility test cannot create a partial release.

The workflow uploads intermediate artifacts between build and compatibility jobs. The exact archive built once in the baseline container is tested and published; target jobs must not rebuild it.

## Compatibility Verification

The release candidate is tested in clean x86_64 containers for:

- Ubuntu 20.04;
- Ubuntu 22.04; and
- Ubuntu 24.04.

Each target uses the same archive and verifies:

- `codex-session --help`;
- `codex-session --version`;
- SQLite session discovery using synthetic data;
- JSONL fallback discovery using synthetic data;
- TUI startup and clean exit in a pseudo-terminal; and
- browsing behavior when the `codex` executable is absent.

WSL uses the same Linux x86_64 executable and does not need a separate build. A manual WSL smoke test remains part of the release checklist because GitHub-hosted Linux containers do not reproduce the entire WSL host integration.

Existing unit tests and wheel/source-distribution checks continue to run. The pip-installable package must not regress as a consequence of standalone packaging.

## Installer Tests

Installer integration tests use a temporary prefix and a local fixture release server or injected asset source so they do not modify the developer's home directory and do not depend on a live GitHub release.

They cover:

- first installation;
- repeated installation of the same version;
- upgrade with atomic `current` switching;
- retention of only the current and previous versions;
- explicit version selection;
- custom prefix installation;
- checksum mismatch;
- interrupted or unavailable download;
- malformed archive;
- staged executable version mismatch;
- unsupported operating system or architecture; and
- refusal to overwrite an unrelated command path.

Failure-path tests assert that an already working version and command link remain unchanged.

## Error Handling and Security

All downloads use HTTPS and fail on HTTP errors. The checksum detects corruption or disagreement between downloaded release assets. It is not presented as protection against compromise of the GitHub release account because the archive and checksum share the same trust boundary.

Temporary files are private and removed on every handled exit. Archive extraction must reject absolute paths and parent-directory traversal before placing files under the installation prefix.

The installer prints failures to standard error, uses a nonzero exit status, and identifies the failed phase. It never logs credentials or reads Codex session data. The release archive contains no real session fixtures, authentication material, caches, or machine-specific private paths.

The standalone program preserves current runtime behavior: without `codex` in `PATH`, users may browse and preview sessions but cannot resume one.

## Repository Changes

Implementation is limited to standalone distribution support:

```text
packaging/codex-session.spec
scripts/build-standalone.sh
scripts/install.sh
.github/workflows/release-linux-x86_64.yml
tests/test_install_script.py
README.md
```

Additional focused test helpers or fixture files may be added when required, but application features and unrelated refactoring are out of scope.

## Acceptance Criteria

The change is complete when:

- a fresh Ubuntu or WSL 20.04 x86_64 user can install without Python or sudo;
- installation through `--version` succeeds using only user-owned paths;
- the same archive passes Ubuntu 20.04, 22.04, and 24.04 compatibility tests;
- installation failure cannot damage a previously installed version;
- repeated installation is idempotent;
- upgrade retains one usable previous version;
- path collisions, unsupported targets, download errors, and checksum failures produce clear diagnostics;
- the GitHub Release contains the archive, matching checksum, and installer;
- release tags and application versions cannot disagree;
- existing pip installation and tests continue to pass; and
- README documents standalone installation first, pip installation for developers, rollback, uninstallation, PATH configuration, supported platforms, and the continuing Codex CLI requirement.

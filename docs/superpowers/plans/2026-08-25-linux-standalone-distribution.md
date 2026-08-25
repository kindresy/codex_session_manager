# Linux Standalone Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish one self-contained Codex Session Manager archive for Linux/WSL x86_64 that installs without Python or sudo and runs on Ubuntu 20.04 through 24.04.

**Architecture:** Build a PyInstaller directory bundle inside a digest-pinned Python 3.10 Debian Bullseye container so the executable targets glibc 2.31. A POSIX shell installer downloads a tagged archive and checksum into private staging, validates it, installs into versioned user directories, and atomically switches managed links. GitHub Actions builds the archive once, tests that exact file in three clean Ubuntu containers, and publishes it only after all gates pass.

**Tech Stack:** Python 3.10, unittest, PyInstaller 6.21.0, POSIX shell, GNU tar/coreutils, Docker, GitHub Actions, GitHub CLI.

## Global Constraints

- Supported targets are Linux and WSL x86_64 with Ubuntu 20.04/glibc 2.31 or newer.
- Native Windows, macOS, Linux ARM64, and musl-based Linux are out of scope.
- End users must not need Python, pip, a virtual environment, setuptools, or sudo.
- The standalone bundle uses PyInstaller directory mode, never one-file mode.
- Default installation prefix is `~/.local`; `--prefix PATH` and `--version vX.Y.Z` are supported.
- Installation failure must leave the currently selected version and command link unchanged.
- Keep the newly installed version and one previous version after a successful upgrade.
- Existing wheel, source distribution, Git installation, editable installation, and runtime behavior remain supported.
- Release assets are exactly `codex-session-manager-linux-x86_64.tar.gz`, `codex-session-manager-linux-x86_64.tar.gz.sha256`, and `install.sh`.
- The build image is `python@sha256:b3061b93c8df9809c3783a4f17bbf2520425ec6b40bd3e5e7538870e21ba7209`, the linux/amd64 manifest for Python 3.10.18 on Debian Bullseye.
- Standalone build dependencies are pinned to PyInstaller 6.21.0, altgraph 0.17.5, packaging 26.3, pyinstaller-hooks-contrib 2026.7, and setuptools 65.5.1.
- No real Codex sessions, credentials, caches, or build-machine private paths may enter release artifacts.

---

## File Structure

- `scripts/install.sh`: end-user platform checks, release resolution, download, validation, staged installation, atomic switching, retention, and diagnostics.
- `tests/test_install_script.py`: hermetic installer integration tests using synthetic local release assets and temporary prefixes.
- `packaging/codex-session.spec`: PyInstaller directory-bundle graph and bundled README/LICENSE data.
- `packaging/requirements-standalone.txt`: exact standalone build-tool versions.
- `scripts/build-standalone.sh`: single local/CI build entry point that tests, freezes, archives, checksums, and verifies.
- `scripts/test-standalone.sh`: target-container smoke checks for CLI, SQLite, JSONL, and curses startup.
- `tests/verify_standalone.py`: archive structure, path-safety, content, and build-path verifier.
- `.github/workflows/release-linux-x86_64.yml`: build-once, compatibility-matrix, and tag release pipeline.
- `tests/test_release_assets.py`: repository-level contracts for packaging, workflow, installer, and public documentation.
- `tests/verify_distribution.py`: source-distribution inclusion contract for the new release tooling.
- `MANIFEST.in`: source-distribution inclusion rules.
- `README.md`: standalone-first installation, upgrade, rollback, uninstall, PATH, compatibility, and developer fallback guidance.

---

### Task 1: Versioned User Installer Happy Path

**Files:**
- Create: `scripts/install.sh`
- Create: `tests/test_install_script.py`

**Interfaces:**
- Consumes: release tag `vX.Y.Z`; stable archive and checksum filenames; executable output `codex-session X.Y.Z`.
- Produces: `scripts/install.sh [--prefix PATH] [--version vX.Y.Z]`; version directory `<prefix>/lib/codex-session-manager/versions/X.Y.Z`; atomic `current` and `<prefix>/bin/codex-session` links.

- [ ] **Step 1: Write fixture helpers and failing happy-path tests**

Create `tests/test_install_script.py` with helpers that build a synthetic directory-mode archive. The fake executable must implement `--version` and `--help`, and the local fixture layout must match GitHub's `/releases/download/<tag>/` URL shape:

```python
import hashlib
import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install.sh"
ASSET = "codex-session-manager-linux-x86_64.tar.gz"


def create_release(root: Path, tag: str) -> Path:
    version = tag.removeprefix("v")
    release = root / "releases" / "download" / tag
    bundle = root / f"bundle-{version}" / "codex-session-manager"
    bundle.mkdir(parents=True)
    executable = bundle / "codex-session"
    executable.write_text(
        "#!/bin/sh\n"
        f"test \"$1\" = --version && echo 'codex-session {version}' && exit 0\n"
        "test \"$1\" = --help && echo 'synthetic help' && exit 0\n"
        "exit 0\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    (bundle / "README.md").write_text("synthetic release\n", encoding="utf-8")
    release.mkdir(parents=True)
    archive = release / ASSET
    with tarfile.open(archive, "w:gz") as output:
        output.add(bundle, arcname="codex-session-manager")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (release / f"{ASSET}.sha256").write_text(
        f"{digest}  {ASSET}\n", encoding="utf-8"
    )
    return release


class InstallScriptTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.assets = self.root / "assets"
        self.prefix = self.root / "prefix"

    def tearDown(self):
        self.tempdir.cleanup()

    def install(self, *arguments: str, assets: Path | None = None):
        base = (assets or self.assets).resolve().as_uri()
        environment = os.environ.copy()
        environment.update(
            {
                "CODEX_SESSION_RELEASE_BASE_URL": base + "/releases/download",
                "CODEX_SESSION_INSTALLER_TESTING": "1",
            }
        )
        return subprocess.run(
            ["bash", str(INSTALLER), "--prefix", str(self.prefix), *arguments],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    def current_version(self) -> str:
        executable = self.prefix / "bin" / "codex-session"
        return subprocess.check_output(
            [str(executable), "--version"], text=True
        ).strip()

    def test_installs_explicit_version_without_python_or_sudo(self):
        create_release(self.assets, "v0.1.0")

        result = self.install("--version", "v0.1.0")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current_version(), "codex-session 0.1.0")
        current = self.prefix / "lib" / "codex-session-manager" / "current"
        self.assertEqual(os.readlink(current), "versions/0.1.0")
        self.assertEqual(
            os.readlink(self.prefix / "bin" / "codex-session"),
            "../lib/codex-session-manager/current/codex-session",
        )

    def test_reinstalling_same_version_is_idempotent(self):
        create_release(self.assets, "v0.1.0")
        first = self.install("--version", "v0.1.0")

        second = self.install("--version", "v0.1.0")

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        versions = self.prefix / "lib" / "codex-session-manager" / "versions"
        self.assertEqual([item.name for item in versions.iterdir()], ["0.1.0"])

    def test_upgrade_switches_current_and_retains_previous(self):
        for tag in ("v0.1.0", "v0.2.0", "v0.3.0"):
            create_release(self.assets, tag)
        self.assertEqual(self.install("--version", "v0.1.0").returncode, 0)
        self.assertEqual(self.install("--version", "v0.2.0").returncode, 0)

        result = self.install("--version", "v0.3.0")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current_version(), "codex-session 0.3.0")
        versions = self.prefix / "lib" / "codex-session-manager" / "versions"
        self.assertEqual(
            sorted(item.name for item in versions.iterdir()), ["0.2.0", "0.3.0"]
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the installer tests and verify they fail**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_install_script -v
```

Expected: FAIL because `scripts/install.sh` does not exist.

- [ ] **Step 3: Implement the minimal safe installer**

Create executable `scripts/install.sh`. Keep all mutation after archive checksum, archive-path, staged-version, and command-collision validation. Use a temporary link plus GNU `mv -T` for both atomic switches. The complete script at this task must implement argument parsing, latest-tag resolution, validation, idempotence, upgrade, and two-version retention:

```bash
#!/bin/sh
set -eu

PROGRAM=codex-session-manager
ASSET=codex-session-manager-linux-x86_64.tar.gz
REPOSITORY=https://github.com/kindresy/codex_session_manager
PREFIX=${HOME:?HOME is not set}/.local
REQUESTED_TAG=

fail() {
    printf 'codex-session installer: %s\n' "$*" >&2
    exit 1
}

usage() {
    printf 'Usage: install.sh [--prefix PATH] [--version vX.Y.Z]\n'
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix)
            [ "$#" -ge 2 ] || fail "--prefix requires a path"
            PREFIX=$2
            shift 2
            ;;
        --version)
            [ "$#" -ge 2 ] || fail "--version requires a tag such as v0.1.0"
            REQUESTED_TAG=$2
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *) fail "unknown argument: $1" ;;
    esac
done

[ "$(uname -s)" = Linux ] || fail "only Linux is supported"
case "$(uname -m)" in
    x86_64|amd64) ;;
    *) fail "only Linux x86_64 is supported" ;;
esac
for command in curl tar sha256sum mktemp awk grep mkdir mv rm rmdir ln readlink; do
    command -v "$command" >/dev/null 2>&1 || fail "required command not found: $command"
done

RELEASE_BASE_URL=${CODEX_SESSION_RELEASE_BASE_URL:-$REPOSITORY/releases/download}
LATEST_URL=${CODEX_SESSION_LATEST_URL:-$REPOSITORY/releases/latest}
case "$RELEASE_BASE_URL" in
    https://*) ;;
    file://*) [ "${CODEX_SESSION_INSTALLER_TESTING:-}" = 1 ] || fail "release URL must use HTTPS" ;;
    *) fail "release URL must use HTTPS" ;;
esac

TAG=$REQUESTED_TAG
if [ -z "$TAG" ]; then
    effective_url=$(curl -fsSL -o /dev/null -w '%{url_effective}' "$LATEST_URL") \
        || fail "could not resolve the latest release"
    TAG=${effective_url##*/}
fi
printf '%s\n' "$TAG" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$' \
    || fail "invalid release tag: $TAG"
VERSION=${TAG#v}

DOWNLOAD_DIR=$(mktemp -d) || fail "could not create a temporary directory"
cleanup() { rm -rf "$DOWNLOAD_DIR"; }
trap cleanup EXIT HUP INT TERM
ARCHIVE=$DOWNLOAD_DIR/$ASSET
CHECKSUM=$ARCHIVE.sha256
URL=$RELEASE_BASE_URL/$TAG
curl -fsSL "$URL/$ASSET" -o "$ARCHIVE" || fail "archive download failed"
curl -fsSL "$URL/$ASSET.sha256" -o "$CHECKSUM" || fail "checksum download failed"
(cd "$DOWNLOAD_DIR" && sha256sum -c "$ASSET.sha256") >/dev/null 2>&1 \
    || fail "archive checksum verification failed"

tar -tzf "$ARCHIVE" >"$DOWNLOAD_DIR/members" || fail "release archive is invalid"
if awk -F/ '
    BEGIN { bad = 0 }
    /^\// { bad = 1 }
    { for (i = 1; i <= NF; i++) if ($i == "..") bad = 1 }
    END { exit bad ? 0 : 1 }
' "$DOWNLOAD_DIR/members"; then
    fail "release archive contains an unsafe path"
fi
awk -F/ '$1 != "codex-session-manager" { exit 1 }' "$DOWNLOAD_DIR/members" \
    || fail "release archive has an unexpected root directory"

APP_ROOT=$PREFIX/lib/$PROGRAM
VERSIONS=$APP_ROOT/versions
TARGET=$VERSIONS/$VERSION
CURRENT=$APP_ROOT/current
COMMAND=$PREFIX/bin/codex-session
MANAGED_COMMAND=../lib/$PROGRAM/current/codex-session
mkdir -p "$VERSIONS" "$PREFIX/bin"

if [ -e "$COMMAND" ] || [ -L "$COMMAND" ]; then
    [ -L "$COMMAND" ] && [ "$(readlink "$COMMAND")" = "$MANAGED_COMMAND" ] \
        || fail "$COMMAND already exists and is not managed by this installer"
fi
if [ -e "$CURRENT" ] && [ ! -L "$CURRENT" ]; then
    fail "$CURRENT exists and is not a symbolic link"
fi

PREVIOUS=
if [ -L "$CURRENT" ]; then
    PREVIOUS=$(readlink "$CURRENT")
    PREVIOUS=${PREVIOUS##*/}
fi

if [ ! -d "$TARGET" ]; then
    STAGE=$(mktemp -d "$APP_ROOT/.stage.XXXXXX") \
        || fail "could not create installation staging directory"
    tar -xzf "$ARCHIVE" -C "$STAGE" || fail "release archive extraction failed"
    STAGED=$STAGE/codex-session-manager
    [ -x "$STAGED/codex-session" ] || fail "release executable is missing"
    reported=$("$STAGED/codex-session" --version 2>/dev/null) \
        || fail "staged executable did not start"
    [ "$reported" = "codex-session $VERSION" ] \
        || fail "staged executable version does not match $TAG"
    mv "$STAGED" "$TARGET"
    rmdir "$STAGE"
else
    reported=$("$TARGET/codex-session" --version 2>/dev/null) \
        || fail "installed version $VERSION is damaged"
    [ "$reported" = "codex-session $VERSION" ] \
        || fail "installed version $VERSION does not match its directory"
fi

CURRENT_TMP=$APP_ROOT/.current.$$
COMMAND_TMP=$PREFIX/bin/.codex-session.$$
rm -f "$CURRENT_TMP" "$COMMAND_TMP"
ln -s "versions/$VERSION" "$CURRENT_TMP"
ln -s "$MANAGED_COMMAND" "$COMMAND_TMP"
mv -Tf "$CURRENT_TMP" "$CURRENT"
mv -Tf "$COMMAND_TMP" "$COMMAND"

for directory in "$VERSIONS"/*; do
    [ -d "$directory" ] || continue
    name=${directory##*/}
    [ "$name" = "$VERSION" ] && continue
    [ -n "$PREVIOUS" ] && [ "$name" = "$PREVIOUS" ] && continue
    rm -rf "$directory"
done

"$COMMAND" --version >/dev/null || fail "installed command smoke test failed"
printf 'Installed codex-session %s at %s\n' "$VERSION" "$COMMAND"
case :$PATH: in
    *:$PREFIX/bin:*) ;;
    *) printf 'Add %s/bin to PATH to run codex-session directly.\n' "$PREFIX" ;;
esac
```

- [ ] **Step 4: Mark the installer executable and run the focused tests**

Run:

```bash
chmod +x scripts/install.sh
PYTHONPATH=src python3 -m unittest tests.test_install_script -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit the installer happy path**

```bash
git add scripts/install.sh tests/test_install_script.py
git commit -m "feat: add standalone user installer"
```

---

### Task 2: Installer Failure Atomicity and Input Hardening

**Files:**
- Modify: `tests/test_install_script.py`
- Modify: `scripts/install.sh`

**Interfaces:**
- Consumes: `InstallScriptTests.install()`, `create_release()`, the managed layout from Task 1.
- Produces: stable nonzero failures for corrupt downloads, wrong versions, unsafe archives, unsupported platforms, and unmanaged command collisions without changing `current`.

- [ ] **Step 1: Add helpers and failing failure-path tests**

Replace `create_release` with the version below, which adds an optional reported version, and add an archive writer for unsafe names:

```python
def create_release(root: Path, tag: str, reported_version: str | None = None) -> Path:
    version = tag.removeprefix("v")
    shown = reported_version or version
    release = root / "releases" / "download" / tag
    bundle = root / f"bundle-{version}" / "codex-session-manager"
    bundle.mkdir(parents=True)
    executable = bundle / "codex-session"
    executable.write_text(
        "#!/bin/sh\n"
        f"test \"$1\" = --version && echo 'codex-session {shown}' && exit 0\n"
        "test \"$1\" = --help && echo 'synthetic help' && exit 0\n"
        "exit 0\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    (bundle / "README.md").write_text("synthetic release\n", encoding="utf-8")
    release.mkdir(parents=True)
    archive = release / ASSET
    with tarfile.open(archive, "w:gz") as output:
        output.add(bundle, arcname="codex-session-manager")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (release / f"{ASSET}.sha256").write_text(
        f"{digest}  {ASSET}\n", encoding="utf-8"
    )
    return release


def replace_with_unsafe_archive(release: Path) -> None:
    archive = release / ASSET
    with tarfile.open(archive, "w:gz") as output:
        payload = b"unsafe\n"
        member = tarfile.TarInfo("../outside")
        member.size = len(payload)
        output.addfile(member, io.BytesIO(payload))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (release / f"{ASSET}.sha256").write_text(
        f"{digest}  {ASSET}\n", encoding="utf-8"
    )
```

Add these methods to `InstallScriptTests`:

```python
def assert_current_survives(self, failed: subprocess.CompletedProcess[str]):
    self.assertNotEqual(failed.returncode, 0)
    self.assertEqual(self.current_version(), "codex-session 0.1.0")

def test_checksum_failure_preserves_current_installation(self):
    create_release(self.assets, "v0.1.0")
    release = create_release(self.assets, "v0.2.0")
    self.assertEqual(self.install("--version", "v0.1.0").returncode, 0)
    (release / f"{ASSET}.sha256").write_text("0" * 64 + f"  {ASSET}\n")

    result = self.install("--version", "v0.2.0")

    self.assertIn("checksum", result.stderr)
    self.assert_current_survives(result)

def test_download_failure_preserves_current_installation(self):
    create_release(self.assets, "v0.1.0")
    self.assertEqual(self.install("--version", "v0.1.0").returncode, 0)

    result = self.install("--version", "v9.9.9")

    self.assertIn("download failed", result.stderr)
    self.assert_current_survives(result)

def test_version_mismatch_preserves_current_installation(self):
    create_release(self.assets, "v0.1.0")
    create_release(self.assets, "v0.2.0", reported_version="9.9.9")
    self.assertEqual(self.install("--version", "v0.1.0").returncode, 0)

    result = self.install("--version", "v0.2.0")

    self.assertIn("does not match", result.stderr)
    self.assert_current_survives(result)
    app_root = self.prefix / "lib" / "codex-session-manager"
    self.assertEqual(list(app_root.glob(".stage.*")), [])

def test_unsafe_archive_is_rejected_before_extraction(self):
    release = create_release(self.assets, "v0.1.0")
    replace_with_unsafe_archive(release)

    result = self.install("--version", "v0.1.0")

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("unsafe path", result.stderr)
    self.assertFalse((self.root / "outside").exists())

def test_unmanaged_command_is_never_overwritten(self):
    create_release(self.assets, "v0.1.0")
    command = self.prefix / "bin" / "codex-session"
    command.parent.mkdir(parents=True)
    command.write_text("user-owned\n", encoding="utf-8")

    result = self.install("--version", "v0.1.0")

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("not managed", result.stderr)
    self.assertEqual(command.read_text(encoding="utf-8"), "user-owned\n")

def test_invalid_tag_is_rejected(self):
    result = self.install("--version", "main")

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("invalid release tag", result.stderr)

def test_latest_release_is_resolved_from_redirect_target(self):
    create_release(self.assets, "v0.1.0")
    latest = self.assets / "releases" / "tag" / "v0.1.0"
    latest.parent.mkdir(parents=True)
    latest.write_text("latest\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "CODEX_SESSION_RELEASE_BASE_URL":
                self.assets.resolve().as_uri() + "/releases/download",
            "CODEX_SESSION_LATEST_URL": latest.resolve().as_uri(),
            "CODEX_SESSION_INSTALLER_TESTING": "1",
        }
    )

    result = subprocess.run(
        ["bash", str(INSTALLER), "--prefix", str(self.prefix)],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.current_version(), "codex-session 0.1.0")

def test_non_https_latest_url_requires_explicit_test_mode(self):
    latest = self.assets / "releases" / "tag" / "v0.1.0"
    latest.parent.mkdir(parents=True)
    latest.write_text("latest\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["CODEX_SESSION_LATEST_URL"] = latest.resolve().as_uri()

    result = subprocess.run(
        ["bash", str(INSTALLER), "--prefix", str(self.prefix)],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("latest release URL must use HTTPS", result.stderr)

def test_unsupported_operating_system_is_rejected(self):
    create_release(self.assets, "v0.1.0")
    fake_bin = self.root / "fake-bin"
    fake_bin.mkdir()
    uname = fake_bin / "uname"
    uname.write_text(
        "#!/bin/sh\n"
        "test \"$1\" = -s && echo Darwin || echo x86_64\n",
        encoding="utf-8",
    )
    uname.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]

    result = subprocess.run(
        ["bash", str(INSTALLER), "--prefix", str(self.prefix),
         "--version", "v0.1.0"],
        text=True, capture_output=True, env=environment, check=False,
    )

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("only Linux", result.stderr)

def test_unsupported_architecture_is_rejected(self):
    create_release(self.assets, "v0.1.0")
    fake_bin = self.root / "fake-bin"
    fake_bin.mkdir()
    uname = fake_bin / "uname"
    uname.write_text(
        "#!/bin/sh\n"
        "test \"$1\" = -s && echo Linux || echo aarch64\n",
        encoding="utf-8",
    )
    uname.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]

    result = subprocess.run(
        ["bash", str(INSTALLER), "--prefix", str(self.prefix),
         "--version", "v0.1.0"],
        text=True, capture_output=True, env=environment, check=False,
    )

    self.assertNotEqual(result.returncode, 0)
    self.assertIn("x86_64", result.stderr)
```

- [ ] **Step 2: Run the expanded tests and observe the first failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_install_script -v
```

Expected: FAIL because a staged version mismatch leaves `.stage.*` behind and a `file://` latest URL is not yet rejected outside explicit installer test mode.

- [ ] **Step 3: Fix staging cleanup and latest-URL test allowance**

Update the installer cleanup trap so a failed extraction cannot leave `.stage.*` directories, and permit `file://` for both test URLs only when `CODEX_SESSION_INSTALLER_TESTING=1`:

```bash
STAGE=
cleanup() {
    [ -z "$STAGE" ] || rm -rf "$STAGE"
    rm -rf "$DOWNLOAD_DIR"
}
trap cleanup EXIT HUP INT TERM

case "$LATEST_URL" in
    https://*) ;;
    file://*) [ "${CODEX_SESSION_INSTALLER_TESTING:-}" = 1 ] \
        || fail "latest release URL must use HTTPS" ;;
    *) fail "latest release URL must use HTTPS" ;;
esac
```

After moving a staged bundle successfully, set `STAGE=` instead of relying on `rmdir` after the variable remains registered:

```bash
mv "$STAGED" "$TARGET"
rmdir "$STAGE"
STAGE=
```

The checksum, path validation, staged-version verification, command-collision check, and pre-switch validation from Task 1 satisfy the other tests in this task. Do not add another download or extraction path.

- [ ] **Step 4: Run installer and full unit suites**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_install_script -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Expected: all tests PASS and no files exist below the test temporary directories after cleanup.

- [ ] **Step 5: Commit installer hardening**

```bash
git add scripts/install.sh tests/test_install_script.py
git commit -m "test: harden standalone installation failures"
```

---

### Task 3: Reproducible PyInstaller Directory Bundle

**Files:**
- Create: `packaging/requirements-standalone.txt`
- Create: `packaging/codex-session.spec`
- Create: `scripts/build-standalone.sh`
- Create: `scripts/test-standalone.sh`
- Create: `tests/verify_standalone.py`
- Modify: `tests/test_release_assets.py`

**Interfaces:**
- Consumes: `src/codex_session_manager/__main__.py`, `scripts/install.sh`, synthetic fixtures, pinned build container and requirements.
- Produces: `dist/release/codex-session-manager-linux-x86_64.tar.gz`, its `.sha256`, and copied `dist/release/install.sh`; `scripts/test-standalone.sh ARCHIVE`.

- [ ] **Step 1: Add failing repository contracts for standalone build inputs**

Add this test to `ReleaseAssetTests` in `tests/test_release_assets.py`:

```python
def test_standalone_build_assets(self):
    requirements = (ROOT / "packaging/requirements-standalone.txt").read_text(
        encoding="utf-8"
    )
    for pin in (
        "PyInstaller==6.21.0",
        "altgraph==0.17.5",
        "packaging==26.3",
        "pyinstaller-hooks-contrib==2026.7",
        "setuptools==65.5.1",
    ):
        self.assertIn(pin, requirements)
    spec = (ROOT / "packaging/codex-session.spec").read_text(encoding="utf-8")
    self.assertIn("src/codex_session_manager/__main__.py", spec)
    self.assertIn("name=\"codex-session\"", spec)
    self.assertIn("name=\"codex-session-manager\"", spec)
    build = (ROOT / "scripts/build-standalone.sh").read_text(encoding="utf-8")
    self.assertIn("python -m unittest discover -s tests -v", build)
    self.assertIn("python -m PyInstaller", build)
    self.assertIn("tests/verify_standalone.py", build)
    self.assertIn("sha256sum", build)
```

- [ ] **Step 2: Run the contract and verify it fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_release_assets.ReleaseAssetTests.test_standalone_build_assets -v
```

Expected: ERROR because `packaging/requirements-standalone.txt` is absent.

- [ ] **Step 3: Add pinned requirements and PyInstaller specification**

Create `packaging/requirements-standalone.txt`:

```text
PyInstaller==6.21.0
altgraph==0.17.5
packaging==26.3
pyinstaller-hooks-contrib==2026.7
setuptools==65.5.1
```

Create `packaging/codex-session.spec`:

```python
from pathlib import Path


ROOT = Path(SPECPATH).parent
ENTRY = ROOT / "src/codex_session_manager/__main__.py"

analysis = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "README.md"), "."),
        (str(ROOT / "LICENSE"), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="codex-session",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="codex-session-manager",
)
```

- [ ] **Step 4: Add standalone archive verification**

Create `tests/verify_standalone.py` with `verify_archive(path: Path, forbidden_root: Path)`. It must reject unsafe members, require one `codex-session-manager` root plus executable, README, and LICENSE, and scan regular payload files for the UTF-8 bytes of the build root:

```python
from __future__ import annotations

import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


REQUIRED = {
    "codex-session-manager/codex-session",
    "codex-session-manager/README.md",
    "codex-session-manager/LICENSE",
}


def verify_archive(path: Path, forbidden_root: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        missing = REQUIRED - names
        assert not missing, f"standalone archive missing: {sorted(missing)}"
        for member in members:
            parsed = PurePosixPath(member.name)
            assert not parsed.is_absolute(), f"absolute archive path: {member.name}"
            assert ".." not in parsed.parts, f"parent traversal: {member.name}"
            assert parsed.parts[0] == "codex-session-manager", member.name
        with tempfile.TemporaryDirectory() as directory:
            archive.extractall(directory)
            root_bytes = str(forbidden_root.resolve()).encode()
            for candidate in Path(directory).rglob("*"):
                if candidate.is_file() and root_bytes in candidate.read_bytes():
                    raise AssertionError(f"build path leaked into {candidate.name}")


def main(arguments: list[str]) -> int:
    if len(arguments) != 2:
        raise SystemExit("usage: verify_standalone.py ARCHIVE FORBIDDEN_ROOT")
    verify_archive(Path(arguments[0]), Path(arguments[1]))
    print(f"verified {arguments[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 5: Add the reproducible build entry point**

Create executable `scripts/build-standalone.sh`:

```bash
#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
cd "$ROOT"
ARCHIVE=codex-session-manager-linux-x86_64.tar.gz

PYTHONPATH=src python -m unittest discover -s tests -v
rm -rf build/standalone dist/standalone dist/release
mkdir -p build/standalone dist/standalone dist/release
python -m PyInstaller --clean --noconfirm \
    --workpath build/standalone \
    --distpath dist/standalone \
    packaging/codex-session.spec

dist/standalone/codex-session-manager/codex-session --help >/dev/null
dist/standalone/codex-session-manager/codex-session --version
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-0}
export SOURCE_DATE_EPOCH
tar --sort=name --owner=0 --group=0 --numeric-owner \
    --mtime="@$SOURCE_DATE_EPOCH" \
    -C dist/standalone -czf "dist/release/$ARCHIVE" codex-session-manager
(cd dist/release && sha256sum "$ARCHIVE" >"$ARCHIVE.sha256")
cp scripts/install.sh dist/release/install.sh
python tests/verify_standalone.py "dist/release/$ARCHIVE" "$ROOT"
```

- [ ] **Step 6: Add target-container smoke testing**

Create executable `scripts/test-standalone.sh`:

```bash
#!/bin/sh
set -eu

[ "$#" -eq 1 ] || { echo "usage: test-standalone.sh ARCHIVE" >&2; exit 2; }
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT HUP INT TERM
tar -xzf "$1" -C "$WORK"
APP=$WORK/codex-session-manager/codex-session
"$APP" --help >/dev/null
"$APP" --version

JSON_HOME=$WORK/json-home
mkdir -p "$JSON_HOME/sessions/2026/08/22"
cp "$ROOT/tests/fixtures/fallback/rollout-2026-08-22T20-05-43-fixture.jsonl" \
    "$JSON_HOME/sessions/2026/08/22/"
printf 'q' | TERM=xterm timeout 10 script -qefc \
    "$APP --codex-home $JSON_HOME --no-color" /dev/null >/dev/null

SQL_HOME=$WORK/sql-home
mkdir -p "$SQL_HOME"
sqlite3 "$SQL_HOME/state_5.sqlite" <"$ROOT/tests/fixtures/current_schema.sql"
printf 'q' | TERM=xterm timeout 10 script -qefc \
    "$APP --codex-home $SQL_HOME --no-color" /dev/null >/dev/null
```

- [ ] **Step 7: Run the fast contracts**

Run:

```bash
chmod +x scripts/build-standalone.sh scripts/test-standalone.sh
PYTHONPATH=src python3 -m unittest \
  tests.test_release_assets.ReleaseAssetTests.test_standalone_build_assets -v
python3 -m compileall -q tests/verify_standalone.py
```

Expected: PASS.

- [ ] **Step 8: Build in the pinned glibc 2.31 container**

Run:

```bash
docker run --rm --platform linux/amd64 \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -v "$PWD:/work" -w /work \
  python@sha256:b3061b93c8df9809c3783a4f17bbf2520425ec6b40bd3e5e7538870e21ba7209 \
  sh -euxc '
    apt-get update
    apt-get install -y --no-install-recommends bash binutils curl
    python -m pip install --no-cache-dir -r packaging/requirements-standalone.txt
    scripts/build-standalone.sh
    chown -R "$HOST_UID:$HOST_GID" build dist
  '
```

Expected: `dist/release/` contains exactly the archive, checksum, and installer; verifier prints `verified ...`; the frozen command prints `codex-session 0.1.0`.

- [ ] **Step 9: Smoke-test the exact archive on the local host**

Run:

```bash
scripts/test-standalone.sh dist/release/codex-session-manager-linux-x86_64.tar.gz
```

Expected: exit 0 after both pseudo-terminal launches.

- [ ] **Step 10: Commit standalone packaging**

```bash
git add packaging scripts/build-standalone.sh scripts/test-standalone.sh \
  tests/verify_standalone.py tests/test_release_assets.py
git commit -m "build: add reproducible linux standalone bundle"
```

---

### Task 4: Build-Once Compatibility and Release Workflow

**Files:**
- Create: `.github/workflows/release-linux-x86_64.yml`
- Modify: `tests/test_release_assets.py`

**Interfaces:**
- Consumes: pinned build image; `scripts/build-standalone.sh`; `scripts/test-standalone.sh`; the three files in `dist/release/`.
- Produces: CI artifact `linux-x86_64-release`; compatibility jobs for Ubuntu 20.04/22.04/24.04; draft-then-publish GitHub Release on matching `vX.Y.Z` tags.

- [ ] **Step 1: Add a failing workflow contract**

Add to `ReleaseAssetTests`:

```python
def test_linux_standalone_release_workflow(self):
    workflow = (
        ROOT / ".github/workflows/release-linux-x86_64.yml"
    ).read_text(encoding="utf-8")
    required = (
        "pull_request:",
        "workflow_dispatch:",
        "linux-x86_64-release",
        "b3061b93c8df9809c3783a4f17bbf2520425ec6b40bd3e5e7538870e21ba7209",
        'ubuntu: ["20.04", "22.04", "24.04"]',
        "scripts/build-standalone.sh",
        "scripts/test-standalone.sh",
        "actions/upload-artifact@v4",
        "actions/download-artifact@v4",
        "contents: write",
        "gh release create",
        "--draft",
        "gh release edit",
    )
    for value in required:
        with self.subTest(value=value):
            self.assertIn(value, workflow)
```

- [ ] **Step 2: Run the workflow contract and verify it fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_release_assets.ReleaseAssetTests.test_linux_standalone_release_workflow -v
```

Expected: ERROR because the workflow file is absent.

- [ ] **Step 3: Create the build-once and compatibility workflow**

Create `.github/workflows/release-linux-x86_64.yml` with this structure and exact job dependencies:

```yaml
name: Linux standalone release

on:
  push:
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v5
      - name: Build in glibc 2.31 container
        run: |
          docker run --rm --platform linux/amd64 \
            -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
            -v "$PWD:/work" -w /work \
            python@sha256:b3061b93c8df9809c3783a4f17bbf2520425ec6b40bd3e5e7538870e21ba7209 \
            sh -euxc '
              apt-get update
              apt-get install -y --no-install-recommends bash binutils curl
              python -m pip install --no-cache-dir -r packaging/requirements-standalone.txt
              scripts/build-standalone.sh
              chown -R "$HOST_UID:$HOST_GID" build dist
            '
      - uses: actions/upload-artifact@v4
        with:
          name: linux-x86_64-release
          path: dist/release/
          if-no-files-found: error

  compatibility:
    needs: build
    runs-on: ubuntu-24.04
    strategy:
      fail-fast: false
      matrix:
        ubuntu: ["20.04", "22.04", "24.04"]
    steps:
      - uses: actions/checkout@v5
      - uses: actions/download-artifact@v4
        with:
          name: linux-x86_64-release
          path: dist/release
      - name: Test exact archive on Ubuntu ${{ matrix.ubuntu }}
        run: |
          docker run --rm --platform linux/amd64 \
            -v "$PWD:/work:ro" -w /work \
            "ubuntu:${{ matrix.ubuntu }}" \
            bash -euxc '
              apt-get update
              apt-get install -y --no-install-recommends sqlite3 util-linux
              scripts/test-standalone.sh \
                dist/release/codex-session-manager-linux-x86_64.tar.gz
            '

  release:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: [build, compatibility]
    runs-on: ubuntu-24.04
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v5
      - uses: actions/download-artifact@v4
        with:
          name: linux-x86_64-release
          path: dist/release
      - name: Verify tag matches package version
        run: |
          package_version=$(PYTHONPATH=src python3 -c \
            'from codex_session_manager import __version__; print(__version__)')
          test "$GITHUB_REF_NAME" = "v$package_version"
      - name: Publish complete release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set -eu
          tag=$GITHUB_REF_NAME
          created=0
          cleanup() {
            status=$?
            if [ "$status" -ne 0 ] && [ "$created" -eq 1 ]; then
              gh release delete "$tag" --yes || true
            fi
            exit "$status"
          }
          trap cleanup EXIT
          gh release view "$tag" >/dev/null 2>&1 && {
            echo "release $tag already exists" >&2
            exit 1
          }
          created=1
          gh release create "$tag" dist/release/* \
            --verify-tag --draft --generate-notes --title "$tag"
          gh release edit "$tag" --draft=false
          created=0
```

- [ ] **Step 4: Run workflow and full repository contracts**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_release_assets -v
git diff --check
```

Expected: all release-asset tests PASS and diff check has no output.

- [ ] **Step 5: Commit the workflow**

```bash
git add .github/workflows/release-linux-x86_64.yml tests/test_release_assets.py
git commit -m "ci: publish tested linux standalone releases"
```

---

### Task 5: Source Distribution and Standalone-First Documentation

**Files:**
- Modify: `README.md`
- Modify: `MANIFEST.in`
- Modify: `tests/verify_distribution.py`
- Modify: `tests/test_release_assets.py`

**Interfaces:**
- Consumes: public installer flags and layout from Tasks 1-2; release asset names and support matrix from Tasks 3-4.
- Produces: copyable end-user installation, upgrade, rollback, uninstall, and PATH instructions; complete source archive containing standalone build and release files.

- [ ] **Step 1: Add failing README and sdist contracts**

Extend `test_readme_public_usage`'s `required` tuple in `tests/test_release_assets.py` with:

```python
"codex-session-manager-linux-x86_64.tar.gz",
"releases/latest/download/install.sh",
"bash install.sh",
"--prefix",
"--version",
"~/.local/bin",
"无需安装或升级 Python",
"升级",
"回退",
"卸载",
"glibc 2.31",
```

Extend `SDIST_FILES` in `tests/verify_distribution.py` with:

```python
".github/workflows/release-linux-x86_64.yml",
"packaging/codex-session.spec",
"packaging/requirements-standalone.txt",
"scripts/build-standalone.sh",
"scripts/install.sh",
"scripts/test-standalone.sh",
"tests/test_install_script.py",
"tests/verify_standalone.py",
```

Add assertions to `test_sdist_manifest_and_distribution_checks` for these exact manifest directives:

```python
self.assertIn("include .github/workflows/release-linux-x86_64.yml", manifest)
self.assertIn("recursive-include packaging *.spec *.txt", manifest)
self.assertIn("recursive-include scripts *.sh", manifest)
```

- [ ] **Step 2: Run focused contracts and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_release_assets.ReleaseAssetTests.test_readme_public_usage \
  tests.test_release_assets.ReleaseAssetTests.test_sdist_manifest_and_distribution_checks -v
```

Expected: FAIL because README and MANIFEST do not contain the standalone release guidance/files.

- [ ] **Step 3: Include standalone tooling in source distributions**

Append these exact lines to `MANIFEST.in`:

```text
include .github/workflows/release-linux-x86_64.yml
recursive-include packaging *.spec *.txt
recursive-include scripts *.sh
```

- [ ] **Step 4: Make standalone installation the README default**

Insert this section before the existing GitHub pip installation section, and rename that existing heading to `## 使用 Python/pip 安装`:

```markdown
## 推荐安装：Linux/WSL 独立程序

Linux 或 WSL x86_64 用户可以直接安装自包含版本，无需安装或升级 Python、pip、venv 或 setuptools，也不需要 `sudo`。支持 Ubuntu 20.04 或其他 glibc 2.31 及以上的发行版。

```bash
curl -fsSLO \
  https://github.com/kindresy/codex_session_manager/releases/latest/download/install.sh
less install.sh
bash install.sh
codex-session --version
```

默认安装到 `~/.local`。如果 `~/.local/bin` 不在 `PATH` 中，安装器会打印需要添加的配置。安装到其他用户目录或指定版本：

```bash
bash install.sh --prefix /path/to/prefix
bash install.sh --version v0.1.0
```

也可以从 GitHub Release 手动下载 `codex-session-manager-linux-x86_64.tar.gz` 和对应 `.sha256` 文件，校验并解压后直接运行其中的 `codex-session`。

### 升级、回退和卸载

重新运行 `bash install.sh` 即可升级。安装器保留当前版本和上一个版本；需要回退时，将 `current` 链接指向保留的旧版本：

```bash
ln -sfn ~/.local/lib/codex-session-manager/versions/0.1.0 \
  ~/.local/lib/codex-session-manager/current
```

卸载只删除本工具管理的用户目录和命令链接：

```bash
rm ~/.local/bin/codex-session
rm -r ~/.local/lib/codex-session-manager
```
```

Keep the existing virtual-environment GitHub command under `使用 Python/pip 安装`, followed by clone installation and direct source execution. Add one sentence that pip installation remains intended for Python users and developers and still requires Python 3.10+.

Append this release check to the development section so the WSL-only manual gate is explicit:

```markdown
发布标签前，还需要在 WSL Ubuntu 20.04 x86_64 中手动下载候选压缩包，运行 `codex-session --version`，并打开一次 TUI 后按 `q` 正常退出。GitHub Actions 中的 Linux 容器测试不能替代这项 WSL 集成检查。
```

- [ ] **Step 5: Run distribution and documentation verification**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
python3 -m build
python3 tests/verify_distribution.py dist/*.whl dist/*.tar.gz
git diff --check
```

Expected: all tests PASS, compilation exits 0, wheel and sdist verification both print `verified`, and diff check has no output.

- [ ] **Step 6: Commit public documentation and sdist coverage**

```bash
git add README.md MANIFEST.in tests/verify_distribution.py tests/test_release_assets.py
git commit -m "docs: recommend standalone linux installation"
```

---

### Task 6: Final Cross-Version Release Verification

**Files:**
- Modify only if a verification command exposes a defect in a file owned by Tasks 1-5.

**Interfaces:**
- Consumes: final standalone archive, installer, three Ubuntu target images, wheel, and sdist.
- Produces: local evidence that the release candidate satisfies the approved design before any tag or push.

- [ ] **Step 1: Run the complete unit and distribution suite from a clean generated-output state**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
python3 -m build
python3 tests/verify_distribution.py dist/*.whl dist/*.tar.gz
```

Expected: every command exits 0.

- [ ] **Step 2: Rebuild the standalone artifact in the pinned container**

Run the exact Docker command from Task 3 Step 8.

Expected: archive, checksum, and installer are regenerated under `dist/release/`, and archive verification succeeds.

- [ ] **Step 3: Test the exact archive on all target Ubuntu versions**

Run:

```bash
for version in 20.04 22.04 24.04; do
  docker run --rm --platform linux/amd64 \
    -v "$PWD:/work:ro" -w /work "ubuntu:$version" bash -euxc '
      apt-get update
      apt-get install -y --no-install-recommends sqlite3 util-linux
      scripts/test-standalone.sh \
        dist/release/codex-session-manager-linux-x86_64.tar.gz
    '
done
```

Expected: all three containers print `codex-session 0.1.0` and exit 0 after both TUI smoke tests.

- [ ] **Step 4: Exercise the real installer against local synthetic releases**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_install_script -v
```

Expected: all happy-path and atomic-failure tests PASS.

- [ ] **Step 5: Inspect final repository state**

Run:

```bash
git diff --check
git status --short --branch
git log -6 --oneline
```

Expected: diff check has no output; generated `build/` and `dist/` remain ignored; only intentional commits are ahead of `origin/master`. Do not create a release tag and do not push without a separate user request.

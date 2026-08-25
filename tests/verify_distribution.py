"""Validate the contents of built wheel and source distributions."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path


PACKAGE_MODULES = {
    "codex_session_manager/__init__.py",
    "codex_session_manager/__main__.py",
    "codex_session_manager/app_server.py",
    "codex_session_manager/cli.py",
    "codex_session_manager/compatibility.py",
    "codex_session_manager/models.py",
    "codex_session_manager/preview.py",
    "codex_session_manager/repository.py",
    "codex_session_manager/text.py",
    "codex_session_manager/tui.py",
}

SDIST_FILES = {
    ".github/workflows/ci.yml",
    ".github/workflows/release-linux-x86_64.yml",
    ".gitignore",
    "LICENSE",
    "packaging/codex-session.spec",
    "packaging/requirements-standalone.txt",
    "README.md",
    "pyproject.toml",
    "scripts/build-standalone.sh",
    "scripts/install.sh",
    "scripts/test-standalone.sh",
    "tests/__init__.py",
    "tests/fixture_loader.py",
    "tests/fixtures/current_schema.sql",
    "tests/fixtures/minimal_schema.sql",
    "tests/fixtures/fallback/rollout-2026-08-22T20-05-43-fixture.jsonl",
    "tests/fixtures/mixed-context.jsonl",
    "tests/test_install_script.py",
    "tests/verify_standalone.py",
}


def verify_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        missing = PACKAGE_MODULES - names
        assert not missing, f"wheel missing package modules: {sorted(missing)}"

        metadata_name = next(
            (name for name in names if name.endswith(".dist-info/METADATA")), None
        )
        assert metadata_name is not None, "wheel missing METADATA"
        metadata = archive.read(metadata_name).decode("utf-8")
        assert "Description-Content-Type: text/markdown" in metadata
        assert "# Codex Session Manager" in metadata
        assert any(name.endswith(".dist-info/licenses/LICENSE") for name in names)


def verify_sdist(path: Path) -> None:
    with tarfile.open(path) as archive:
        names = archive.getnames()
    roots = {name.split("/", 1)[0] for name in names if "/" in name}
    assert len(roots) == 1, f"unexpected sdist roots: {sorted(roots)}"
    root = roots.pop()
    relative_names = {
        name.removeprefix(f"{root}/") for name in names if name.startswith(f"{root}/")
    }
    required = SDIST_FILES | {f"src/{name}" for name in PACKAGE_MODULES}
    missing = required - relative_names
    assert not missing, f"sdist missing files: {sorted(missing)}"


def main(arguments: list[str]) -> int:
    if not arguments:
        raise SystemExit("usage: verify_distribution.py DIST [DIST ...]")
    for argument in arguments:
        path = Path(argument)
        if path.suffix == ".whl":
            verify_wheel(path)
        elif path.name.endswith(".tar.gz"):
            verify_sdist(path)
        else:
            raise AssertionError(f"unsupported distribution: {path}")
        print(f"verified {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

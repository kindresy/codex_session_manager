"""Validate a standalone Linux release archive."""

from __future__ import annotations

import sys
import tarfile
from pathlib import Path, PurePosixPath


REQUIRED = {
    "codex-session-manager/codex-session",
    "codex-session-manager/README.md",
    "codex-session-manager/LICENSE",
}
FORBIDDEN_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "sessions",
}
FORBIDDEN_FILES = {
    "auth.json",
    "credentials",
    "credentials.json",
    ".netrc",
    "id_rsa",
    "id_ed25519",
}


def member_contains(archive: tarfile.TarFile, member: tarfile.TarInfo, needle: bytes) -> bool:
    if not needle:
        return False
    source = archive.extractfile(member)
    assert source is not None, f"could not read archive member: {member.name}"
    overlap = b""
    while chunk := source.read(1024 * 1024):
        combined = overlap + chunk
        if needle in combined:
            return True
        overlap_size = max(len(needle) - 1, 0)
        overlap = combined[-overlap_size:] if overlap_size else b""
    return False


def verify_archive(path: Path, forbidden_root: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        missing = REQUIRED - names
        assert not missing, f"standalone archive missing: {sorted(missing)}"
        by_name = {member.name: member for member in members}
        executable = by_name["codex-session-manager/codex-session"]
        assert executable.isfile(), "standalone executable must be a regular file"
        assert executable.mode & 0o111, "standalone executable is not executable"
        root_bytes = str(forbidden_root.resolve()).encode()
        for member in members:
            parsed = PurePosixPath(member.name)
            assert not parsed.is_absolute(), f"absolute archive path: {member.name}"
            assert ".." not in parsed.parts, f"parent traversal: {member.name}"
            assert parsed.parts[0] == "codex-session-manager", member.name
            assert member.isdir() or member.isfile(), (
                f"archive members must be directories or regular files: {member.name}"
            )
            lowered = tuple(part.casefold() for part in parsed.parts)
            assert not FORBIDDEN_PARTS.intersection(lowered), (
                f"forbidden cache or session path: {member.name}"
            )
            assert parsed.name.casefold() not in FORBIDDEN_FILES, (
                f"forbidden credential-like file: {member.name}"
            )
            if member.isfile() and member_contains(archive, member, root_bytes):
                raise AssertionError(f"build path leaked into {member.name}")


def main(arguments: list[str]) -> int:
    if len(arguments) != 2:
        raise SystemExit("usage: verify_standalone.py ARCHIVE FORBIDDEN_ROOT")
    verify_archive(Path(arguments[0]), Path(arguments[1]))
    print(f"verified {arguments[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

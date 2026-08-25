"""Validate a standalone Linux release archive."""

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

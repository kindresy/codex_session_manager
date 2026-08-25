import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from verify_standalone import verify_archive


class StandaloneVerifierTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.archive = self.root / "release.tar.gz"

    def tearDown(self):
        self.tempdir.cleanup()

    def write_archive(self, extras=(), executable_mode=0o755):
        with tarfile.open(self.archive, "w:gz") as output:
            for name, data, mode in (
                ("codex-session-manager/codex-session", b"binary", executable_mode),
                ("codex-session-manager/README.md", b"readme", 0o644),
                ("codex-session-manager/LICENSE", b"license", 0o644),
            ):
                member = tarfile.TarInfo(name)
                member.size = len(data)
                member.mode = mode
                output.addfile(member, io.BytesIO(data))
            for member, data in extras:
                output.addfile(member, io.BytesIO(data) if data is not None else None)

    def test_accepts_regular_standalone_archive(self):
        self.write_archive()
        verify_archive(self.archive, self.root / "build-root")

    def test_rejects_non_executable_entrypoint(self):
        self.write_archive(executable_mode=0o644)
        with self.assertRaisesRegex(AssertionError, "executable"):
            verify_archive(self.archive, self.root / "build-root")

    def test_accepts_safe_internal_symbolic_link(self):
        link = tarfile.TarInfo("codex-session-manager/lib/alias.so")
        link.type = tarfile.SYMTYPE
        link.linkname = "../real.so"
        self.write_archive(extras=((link, None),))
        verify_archive(self.archive, self.root / "build-root")

    def test_rejects_escaping_symbolic_link(self):
        link = tarfile.TarInfo("codex-session-manager/lib/escape")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../../outside"
        self.write_archive(extras=((link, None),))
        with self.assertRaisesRegex(AssertionError, "unsafe symbolic link"):
            verify_archive(self.archive, self.root / "build-root")

    def test_rejects_special_members(self):
        fifo = tarfile.TarInfo("codex-session-manager/pipe")
        fifo.type = tarfile.FIFOTYPE
        self.write_archive(extras=((fifo, None),))
        with self.assertRaisesRegex(AssertionError, "regular files"):
            verify_archive(self.archive, self.root / "build-root")

    def test_rejects_caches_sessions_and_credentials(self):
        for forbidden in (
            "codex-session-manager/__pycache__/module.pyc",
            "codex-session-manager/sessions/rollout.jsonl",
            "codex-session-manager/auth.json",
        ):
            with self.subTest(forbidden=forbidden):
                member = tarfile.TarInfo(forbidden)
                member.size = 1
                self.write_archive(extras=((member, b"x"),))
                with self.assertRaisesRegex(AssertionError, "forbidden"):
                    verify_archive(self.archive, self.root / "build-root")

    def test_rejects_build_path_in_member_content(self):
        forbidden_root = self.root / "private-build"
        member = tarfile.TarInfo("codex-session-manager/data.bin")
        payload = b"prefix" + os.fsencode(forbidden_root.resolve()) + b"suffix"
        member.size = len(payload)
        self.write_archive(extras=((member, payload),))
        with self.assertRaisesRegex(AssertionError, "build path"):
            verify_archive(self.archive, forbidden_root)


if __name__ == "__main__":
    unittest.main()

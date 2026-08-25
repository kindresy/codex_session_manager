import hashlib
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

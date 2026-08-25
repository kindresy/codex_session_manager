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


def create_release(
    root: Path, tag: str, reported_version: str | None = None
) -> Path:
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


def replace_with_malformed_archive(release: Path) -> None:
    archive = release / ASSET
    archive.write_bytes(b"not a tar archive\n")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (release / f"{ASSET}.sha256").write_text(
        f"{digest}  {ASSET}\n", encoding="utf-8"
    )


class InstallScriptTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.assets = self.root / "assets"
        self.prefix = self.root / "prefix"

    def tearDown(self):
        self.tempdir.cleanup()

    def install(
        self,
        *arguments: str,
        assets: Path | None = None,
        extra_environment: dict[str, str] | None = None,
    ):
        base = (assets or self.assets).resolve().as_uri()
        environment = os.environ.copy()
        environment.update(
            {
                "CODEX_SESSION_RELEASE_BASE_URL": base + "/releases/download",
                "CODEX_SESSION_INSTALLER_TESTING": "1",
            }
        )
        environment.update(extra_environment or {})
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

    def assert_current_survives(
        self, failed: subprocess.CompletedProcess[str]
    ) -> None:
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.current_version(), "codex-session 0.1.0")

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

    def test_failure_after_current_switch_rolls_back_everything(self):
        create_release(self.assets, "v0.1.0")
        create_release(self.assets, "v0.2.0")
        self.assertEqual(self.install("--version", "v0.1.0").returncode, 0)
        current = self.prefix / "lib" / "codex-session-manager" / "current"
        command = self.prefix / "bin" / "codex-session"
        old_current = os.readlink(current)
        old_command = os.readlink(command)

        result = self.install(
            "--version",
            "v0.2.0",
            extra_environment={
                "CODEX_SESSION_INSTALLER_TEST_FAIL_PHASE": "after-current"
            },
        )

        self.assert_current_survives(result)
        self.assertEqual(os.readlink(current), old_current)
        self.assertEqual(os.readlink(command), old_command)
        versions = self.prefix / "lib" / "codex-session-manager" / "versions"
        self.assertEqual([item.name for item in versions.iterdir()], ["0.1.0"])

    def test_failed_current_restoration_keeps_new_target_usable(self):
        create_release(self.assets, "v0.1.0")
        create_release(self.assets, "v0.2.0")
        self.assertEqual(self.install("--version", "v0.1.0").returncode, 0)

        result = self.install(
            "--version",
            "v0.2.0",
            extra_environment={
                "CODEX_SESSION_INSTALLER_TEST_FAIL_PHASE": "after-current",
                "CODEX_SESSION_INSTALLER_TEST_FAIL_ROLLBACK": "1",
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.current_version(), "codex-session 0.2.0")
        target = (
            self.prefix
            / "lib"
            / "codex-session-manager"
            / "versions"
            / "0.2.0"
        )
        self.assertTrue(target.is_dir())

    def test_missing_prefix_bin_in_path_prints_exact_export(self):
        create_release(self.assets, "v0.1.0")

        result = self.install("--version", "v0.1.0")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f'export PATH="{self.prefix}/bin:$PATH"', result.stdout
        )

    def test_checksum_failure_preserves_current_installation(self):
        create_release(self.assets, "v0.1.0")
        release = create_release(self.assets, "v0.2.0")
        self.assertEqual(self.install("--version", "v0.1.0").returncode, 0)
        (release / f"{ASSET}.sha256").write_text(
            "0" * 64 + f"  {ASSET}\n", encoding="utf-8"
        )

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

    def test_malformed_archive_with_valid_checksum_is_rejected(self):
        release = create_release(self.assets, "v0.1.0")
        replace_with_malformed_archive(release)

        result = self.install("--version", "v0.1.0")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("archive is invalid", result.stderr)
        self.assertFalse(
            (self.prefix / "lib" / "codex-session-manager" / "current").exists()
        )

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
            [
                "bash",
                str(INSTALLER),
                "--prefix",
                str(self.prefix),
                "--version",
                "v0.1.0",
            ],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only Linux", result.stderr)

    def test_unsupported_architecture_is_rejected(self):
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
            [
                "bash",
                str(INSTALLER),
                "--prefix",
                str(self.prefix),
                "--version",
                "v0.1.0",
            ],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("x86_64", result.stderr)


if __name__ == "__main__":
    unittest.main()

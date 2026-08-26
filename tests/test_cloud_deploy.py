import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "cloud" / "deploy.sh"
PACKAGE = ROOT / "cloud" / "package.json"
LOCKFILE = ROOT / "cloud" / "package-lock.json"
BUCKET = "codex-session-history"
EMPTY_DOMAINS = (
    f"Listing custom domains connected to bucket '{BUCKET}'...\n"
    "There are no custom domains connected to this bucket."
)


class CloudDeployTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls.log"
        self.make_command("npm", "exit 0")
        self.make_command(
            "npx",
            f"""
printf '%s\\n' \"$*\" >> \"$CALL_LOG\"
case \"$*\" in
  '--no-install wrangler login')
    exit \"${{LOGIN_STATUS:-0}}\"
    ;;
  '--no-install wrangler r2 bucket create {BUCKET}')
    printf '%s' \"${{BUCKET_OUTPUT:-created}}\"
    exit \"${{BUCKET_STATUS:-0}}\"
    ;;
  '--no-install wrangler r2 bucket dev-url disable {BUCKET} --force')
    exit \"${{DEV_URL_STATUS:-0}}\"
    ;;
  '--no-install wrangler r2 bucket domain list {BUCKET}')
    printf '%s' \"${{DOMAINS_OUTPUT:-{EMPTY_DOMAINS}}}\"
    exit \"${{DOMAINS_STATUS:-0}}\"
    ;;
  '--no-install wrangler secret put SYNC_TOKEN')
    IFS= read -r secret
    printf 'secret-length=%s\\n' \"${{#secret}}\" >> \"$CALL_LOG\"
    exit \"${{SECRET_STATUS:-0}}\"
    ;;
  '--no-install wrangler deploy')
    printf 'https://example.workers.dev\\n'
    exit \"${{DEPLOY_STATUS:-0}}\"
    ;;
esac
""",
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def make_command(self, name: str, body: str) -> None:
        command = self.bin / name
        command.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        command.chmod(0o755)

    def run_deploy(self, token: str = "secret-token", **environment: str):
        command_environment = os.environ.copy()
        command_environment.update(
            {
                "PATH": str(self.bin),
                "CALL_LOG": str(self.log),
                **environment,
            }
        )
        return subprocess.run(
            ["/bin/sh", "-x", str(DEPLOY)],
            cwd=self.root,
            input=f"{token}\n",
            text=True,
            capture_output=True,
            env=command_environment,
            check=False,
        )

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()

    def expected_calls(self, *tail: str) -> list[str]:
        return [
            "--no-install wrangler login",
            f"--no-install wrangler r2 bucket create {BUCKET}",
            f"--no-install wrangler r2 bucket dev-url disable {BUCKET} --force",
            f"--no-install wrangler r2 bucket domain list {BUCKET}",
            *tail,
        ]

    def test_script_is_posix_and_hides_terminal_input(self):
        source = DEPLOY.read_text(encoding="utf-8")

        self.assertTrue(source.startswith("#!/bin/sh\n"))
        for forbidden in ("pipefail", "BASH_SOURCE", "[[", "((", "read -r -s"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn("stty -echo", source)
        self.assertIn("trap", source)
        self.assertIn("set +x", source)

    def test_pins_local_wrangler_in_the_lockfile(self):
        package = json.loads(PACKAGE.read_text(encoding="utf-8"))
        lockfile = json.loads(LOCKFILE.read_text(encoding="utf-8"))

        self.assertEqual(package["devDependencies"]["wrangler"], "4.125.0")
        self.assertEqual(
            lockfile["packages"]["node_modules/wrangler"]["version"], "4.125.0"
        )

    def test_deploys_from_another_directory_without_exposing_token_under_xtrace(self):
        token = "not-for-output"

        result = self.run_deploy(token)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.calls(),
            self.expected_calls(
                "--no-install wrangler secret put SYNC_TOKEN",
                f"secret-length={len(token)}",
                "--no-install wrangler deploy",
            ),
        )
        output = result.stdout + result.stderr + self.log.read_text(encoding="utf-8")
        self.assertNotIn(token, output)
        self.assertIn("https://example.workers.dev", result.stdout)
        self.assertIn("codex-session sync setup", result.stdout)

    def test_exact_existing_bucket_message_continues_with_private_access(self):
        result = self.run_deploy(
            BUCKET_STATUS="1",
            BUCKET_OUTPUT=f"Bucket {BUCKET} already exists.",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[-1], "--no-install wrangler deploy")
        self.assertIn(
            f"--no-install wrangler r2 bucket dev-url disable {BUCKET} --force",
            self.calls(),
        )

    def test_mixed_existing_bucket_error_stops_before_access_changes(self):
        result = self.run_deploy(
            BUCKET_STATUS="1",
            BUCKET_OUTPUT=f"Bucket {BUCKET} already exists.\nauthentication failed",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("authentication failed", result.stderr)
        self.assertEqual(self.calls(), self.expected_calls()[:2])

    def test_custom_domains_stop_before_secret_or_deploy(self):
        result = self.run_deploy(DOMAINS_OUTPUT="history.example.com")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("custom domains", result.stderr)
        self.assertEqual(self.calls(), self.expected_calls())

    def test_missing_npm_stops_before_wrangler(self):
        (self.bin / "npm").unlink()

        result = self.run_deploy()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("npm", result.stderr)
        self.assertFalse(self.log.exists())

    def test_missing_npx_stops_before_wrangler(self):
        (self.bin / "npx").unlink()

        result = self.run_deploy()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("npx", result.stderr)
        self.assertFalse(self.log.exists())

    def test_login_failure_stops_before_bucket_creation(self):
        result = self.run_deploy(LOGIN_STATUS="1")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), ["--no-install wrangler login"])

    def test_secret_failure_stops_before_deploy(self):
        result = self.run_deploy(SECRET_STATUS="1")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            self.calls(),
            self.expected_calls(
                "--no-install wrangler secret put SYNC_TOKEN",
                "secret-length=12",
            ),
        )

    def test_deploy_failure_returns_an_error(self):
        result = self.run_deploy(DEPLOY_STATUS="1")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls()[-1], "--no-install wrangler deploy")


if __name__ == "__main__":
    unittest.main()

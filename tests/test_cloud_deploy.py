import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "cloud" / "deploy.sh"


class CloudDeployTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "bash").symlink_to("/bin/bash")
        self.log = self.root / "calls.log"
        self.make_command("npm", "exit 0")
        self.make_command(
            "npx",
            """
printf '%s\\n' \"$*\" >> \"$CALL_LOG\"
case \"$*\" in
  'wrangler r2 bucket create codex-session-history')
    printf '%s' \"${BUCKET_OUTPUT:-created}\"
    exit \"${BUCKET_STATUS:-0}\"
    ;;
  'wrangler secret put SYNC_TOKEN')
    IFS= read -r secret
    printf 'secret-length=%s\\n' \"${#secret}\" >> \"$CALL_LOG\"
    exit \"${SECRET_STATUS:-0}\"
    ;;
  'wrangler deploy')
    printf 'https://example.workers.dev\\n'
    exit \"${DEPLOY_STATUS:-0}\"
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
            [str(DEPLOY)],
            cwd=self.root,
            input=f"{token}\n",
            text=True,
            capture_output=True,
            env=command_environment,
            check=False,
        )

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()

    def test_script_is_bash_and_reads_a_hidden_token(self):
        source = DEPLOY.read_text(encoding="utf-8")

        self.assertTrue(source.startswith("#!/usr/bin/env bash\n"))
        self.assertIn("command -v npm", source)
        self.assertIn("command -v npx", source)
        self.assertIn("read -r -s", source)
        self.assertIn("wrangler r2 bucket create codex-session-history", source)
        self.assertNotIn("echo \"$sync_token\"", source)

    def test_deploys_from_another_directory_without_exposing_token(self):
        token = "not-for-output"

        result = self.run_deploy(token)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.calls(),
            [
                "wrangler login",
                "wrangler r2 bucket create codex-session-history",
                "wrangler secret put SYNC_TOKEN",
                f"secret-length={len(token)}",
                "wrangler deploy",
            ],
        )
        output = result.stdout + result.stderr + self.log.read_text(encoding="utf-8")
        self.assertNotIn(token, output)
        self.assertIn("https://example.workers.dev", result.stdout)
        self.assertIn("codex-session sync setup", result.stdout)

    def test_existing_bucket_continues_to_secret_and_deploy(self):
        result = self.run_deploy(
            BUCKET_STATUS="1", BUCKET_OUTPUT="bucket already exists"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("wrangler secret put SYNC_TOKEN", self.calls())
        self.assertEqual(self.calls()[-1], "wrangler deploy")

    def test_other_bucket_error_stops_before_secret_or_deploy(self):
        result = self.run_deploy(
            BUCKET_STATUS="1", BUCKET_OUTPUT="authentication failed"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("authentication failed", result.stderr)
        self.assertEqual(
            self.calls(),
            [
                "wrangler login",
                "wrangler r2 bucket create codex-session-history",
            ],
        )

    def test_missing_npm_stops_before_wrangler(self):
        (self.bin / "npm").unlink()

        result = self.run_deploy()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("npm", result.stderr)
        self.assertFalse(self.log.exists())

    def test_empty_token_stops_before_secret_or_deploy(self):
        result = self.run_deploy("")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SYNC_TOKEN cannot be empty", result.stderr)
        self.assertEqual(
            self.calls(),
            [
                "wrangler login",
                "wrangler r2 bucket create codex-session-history",
            ],
        )


if __name__ == "__main__":
    unittest.main()

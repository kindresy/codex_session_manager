import contextlib
import io
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_session_manager.cli import main, resume_command


class CliTests(unittest.TestCase):
    def test_version_exits_successfully(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), "codex-session 0.1.0")

    def test_help_exits_successfully(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--codex-home", output.getvalue())
        self.assertIn("--no-color", output.getvalue())

    @patch("codex_session_manager.cli.run_tui", return_value=None)
    @patch("codex_session_manager.cli.shutil.which", return_value="/usr/bin/codex")
    @patch("codex_session_manager.cli.PreviewService")
    @patch("codex_session_manager.cli.SessionRepository")
    def test_explicit_home_overrides_environment(
        self, repository_type, preview_type, _which, run_tui
    ):
        with patch.dict(os.environ, {"CODEX_HOME": "/tmp/from-env"}):
            result = main(["--codex-home", "/tmp/from-flag", "--no-color"])

        self.assertEqual(result, 0)
        repository_type.assert_called_once_with(Path("/tmp/from-flag"))
        run_tui.assert_called_once_with(
            repository_type.return_value,
            preview_type.return_value,
            use_color=False,
        )

    @patch("codex_session_manager.cli.run_tui")
    @patch("codex_session_manager.cli.shutil.which", return_value=None)
    def test_missing_codex_still_allows_browsing(self, _which, run_tui):
        run_tui.return_value = None
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            result = main([])
        self.assertEqual(result, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertIn("找不到 codex", run_tui.call_args.kwargs["resume_error"])

    @patch("codex_session_manager.cli.run_tui", return_value=None)
    @patch("codex_session_manager.cli.shutil.which", return_value="/usr/bin/codex")
    def test_quitting_tui_returns_success(self, _which, _run_tui):
        self.assertEqual(main([]), 0)

    @patch("codex_session_manager.cli.os.execvp")
    def test_resume_command_executes_exact_uuid(self, execvp):
        resume_command("12345678-abcd")
        execvp.assert_called_once_with(
            "codex", ["codex", "resume", "12345678-abcd"]
        )

    @patch("codex_session_manager.cli.os.execvp")
    @patch("codex_session_manager.cli.run_tui", return_value="12345678-abcd")
    @patch("codex_session_manager.cli.shutil.which", return_value="/usr/bin/codex")
    def test_selected_session_is_resumed(self, _which, _run_tui, execvp):
        self.assertEqual(main([]), 0)
        execvp.assert_called_once_with(
            "codex", ["codex", "resume", "12345678-abcd"]
        )


if __name__ == "__main__":
    unittest.main()

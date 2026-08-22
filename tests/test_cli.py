import contextlib
import curses
import io
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from codex_session_manager import __version__
from codex_session_manager.cli import main, resume_command


class CliTests(unittest.TestCase):
    def test_version_exits_successfully(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), "codex-session 0.2.0")

    def test_help_exits_successfully(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--codex-home", output.getvalue())
        self.assertIn("--no-color", output.getvalue())

    def test_codex_present_builds_shared_app_server_compatibility_services(self):
        with (
            patch.dict(os.environ, {"CODEX_HOME": "/tmp/from-env"}),
            patch(
                "codex_session_manager.cli.shutil.which",
                return_value="/opt/codex/bin/codex",
            ),
            patch("codex_session_manager.cli.AppServerClient") as client_type,
            patch("codex_session_manager.cli.SessionRepository") as repository_type,
            patch("codex_session_manager.cli.PreviewService") as preview_type,
            patch(
                "codex_session_manager.cli.CompatibleSessionRepository"
            ) as compatible_repository_type,
            patch(
                "codex_session_manager.cli.CompatiblePreviewService"
            ) as compatible_preview_type,
            patch("codex_session_manager.cli.run_tui", return_value=None) as run_tui,
        ):
            result = main(["--codex-home", "/tmp/from-flag", "--no-color"])

        self.assertEqual(result, 0)
        home = Path("/tmp/from-flag")
        repository_type.assert_called_once_with(home)
        preview_type.assert_called_once_with()
        client_type.assert_called_once_with("/opt/codex/bin/codex", home, __version__)
        compatible_repository_type.assert_called_once_with(
            client_type.return_value, repository_type.return_value
        )
        compatible_preview_type.assert_called_once_with(
            client_type.return_value, preview_type.return_value
        )
        run_tui.assert_called_once_with(
            compatible_repository_type.return_value,
            compatible_preview_type.return_value,
            use_color=False,
        )
        client_type.return_value.close.assert_called_once_with()

    def test_missing_codex_still_allows_local_browsing_without_app_server(self):
        with (
            patch("codex_session_manager.cli.shutil.which", return_value=None),
            patch("codex_session_manager.cli.AppServerClient") as client_type,
            patch("codex_session_manager.cli.SessionRepository") as repository_type,
            patch("codex_session_manager.cli.PreviewService") as preview_type,
            patch(
                "codex_session_manager.cli.CompatibleSessionRepository"
            ) as compatible_repository_type,
            patch(
                "codex_session_manager.cli.CompatiblePreviewService"
            ) as compatible_preview_type,
            patch("codex_session_manager.cli.run_tui", return_value=None) as run_tui,
        ):
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                result = main([])
        self.assertEqual(result, 0)
        self.assertEqual(errors.getvalue(), "")
        client_type.assert_not_called()
        compatible_repository_type.assert_not_called()
        compatible_preview_type.assert_not_called()
        self.assertEqual(
            run_tui.call_args.args,
            (repository_type.return_value, preview_type.return_value),
        )
        self.assertTrue(run_tui.call_args.kwargs["use_color"])
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

    def test_app_server_closes_before_resume_handoff(self):
        lifecycle = Mock()
        with (
            patch("codex_session_manager.cli.shutil.which", return_value="/usr/bin/codex"),
            patch("codex_session_manager.cli.AppServerClient") as client_type,
            patch("codex_session_manager.cli.run_tui", return_value="12345678-abcd"),
            patch("codex_session_manager.cli.resume_command") as resume,
        ):
            lifecycle.attach_mock(client_type.return_value.close, "close")
            lifecycle.attach_mock(resume, "resume")
            result = main([])

        self.assertEqual(result, 0)
        self.assertEqual(
            lifecycle.mock_calls,
            [call.close(), call.resume("12345678-abcd")],
        )

    def test_app_server_closes_when_tui_raises(self):
        with (
            patch("codex_session_manager.cli.shutil.which", return_value="/usr/bin/codex"),
            patch("codex_session_manager.cli.AppServerClient") as client_type,
            patch("codex_session_manager.cli.run_tui", side_effect=curses.error("broken")),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            result = main([])

        self.assertEqual(result, 2)
        client_type.return_value.close.assert_called_once_with()

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

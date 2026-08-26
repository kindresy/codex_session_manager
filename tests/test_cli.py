import contextlib
import curses
import io
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from codex_session_manager import __version__
from codex_session_manager.app_server import AppServerError
from codex_session_manager.cli import main, resume_command
from codex_session_manager.cloud_client import CloudError, SyncConfig
from codex_session_manager.sync import SyncResult


class CliTests(unittest.TestCase):
    def test_version_exits_successfully(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), "codex-session 0.3.0")

    def test_help_exits_successfully(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--codex-home", output.getvalue())
        self.assertIn("--no-color", output.getvalue())
        self.assertIn("sync", output.getvalue())
        self.assertIn("cloud", output.getvalue())

    def test_sync_help_lists_setup_status_and_all(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["sync", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("setup", output.getvalue())
        self.assertIn("status", output.getvalue())
        self.assertIn("--all", output.getvalue())

    def test_sync_setup_prompts_for_url_and_hidden_token_then_saves_config(self):
        config_path = Path("/tmp/codex-session-sync.json")
        output = io.StringIO()
        with (
            patch.dict(os.environ, {"CODEX_HOME": "/tmp/original"}, clear=True),
            patch("builtins.input", return_value="https://worker.example") as prompt,
            patch(
                "codex_session_manager.cli.getpass.getpass",
                return_value="secret-token",
            ) as token_prompt,
            patch(
                "codex_session_manager.cli.default_config_path",
                return_value=config_path,
            ),
            patch("codex_session_manager.cli.save_config") as save_config,
            patch("codex_session_manager.cli.shutil.which") as which,
            contextlib.redirect_stdout(output),
        ):
            result = main(["sync", "setup"])
            self.assertEqual(os.environ["CODEX_HOME"], "/tmp/original")

        self.assertEqual(result, 0)
        prompt.assert_called_once_with("Worker URL: ")
        token_prompt.assert_called_once_with("Access token: ")
        save_config.assert_called_once_with(
            config_path,
            SyncConfig("https://worker.example", "secret-token"),
        )
        which.assert_not_called()
        self.assertIn(str(config_path), output.getvalue())
        self.assertNotIn("secret-token", output.getvalue())

    def test_sync_missing_configuration_is_user_facing(self):
        with (
            patch(
                "codex_session_manager.cli.load_config",
                side_effect=CloudError("run codex-session sync setup"),
            ),
            patch("codex_session_manager.cli.AppServerClient") as client_type,
            contextlib.redirect_stderr(io.StringIO()) as errors,
        ):
            result = main(["sync"])

        self.assertEqual(result, 2)
        self.assertIn("run codex-session sync setup", errors.getvalue())
        client_type.assert_not_called()

    def test_sync_requires_codex_after_loading_configuration(self):
        config = SyncConfig("https://worker.example", "token")
        with (
            patch("codex_session_manager.cli.load_config", return_value=config),
            patch("codex_session_manager.cli.shutil.which", return_value=None),
            patch("codex_session_manager.cli.AppServerClient") as client_type,
            patch("codex_session_manager.cli.CloudClient") as cloud_type,
            contextlib.redirect_stderr(io.StringIO()) as errors,
        ):
            result = main(["sync"])

        self.assertEqual(result, 2)
        self.assertIn("找不到 codex", errors.getvalue())
        client_type.assert_not_called()
        cloud_type.assert_not_called()

    def test_sync_all_prints_success_summary_and_closes_app_server(self):
        config = SyncConfig("https://worker.example", "token")
        result = SyncResult(uploaded=2, skipped=3, failed=())
        output = io.StringIO()
        with (
            patch("codex_session_manager.cli.load_config", return_value=config),
            patch(
                "codex_session_manager.cli.shutil.which",
                return_value="/opt/codex/bin/codex",
            ),
            patch("codex_session_manager.cli.AppServerClient") as client_type,
            patch("codex_session_manager.cli.CloudClient") as cloud_type,
            patch("codex_session_manager.cli.sync_sessions", return_value=result) as sync,
            patch("codex_session_manager.cli.run_tui") as run_tui,
            contextlib.redirect_stdout(output),
        ):
            exit_code = main(
                ["--codex-home", "/tmp/sync-home", "--no-color", "sync", "--all"]
            )

        self.assertEqual(exit_code, 0)
        client_type.assert_called_once_with(
            "/opt/codex/bin/codex", Path("/tmp/sync-home"), __version__
        )
        cloud_type.assert_called_once_with(config)
        sync.assert_called_once_with(
            client_type.return_value,
            cloud_type.return_value,
            force_all=True,
        )
        client_type.return_value.close.assert_called_once_with()
        run_tui.assert_not_called()
        self.assertIn("uploaded: 2", output.getvalue())
        self.assertIn("skipped: 3", output.getvalue())
        self.assertIn("failed: 0", output.getvalue())

    def test_sync_partial_failure_prints_details_and_returns_one(self):
        result = SyncResult(
            uploaded=1,
            skipped=2,
            failed=(("session-bad", "thread unavailable"),),
        )
        output = io.StringIO()
        with (
            patch(
                "codex_session_manager.cli.load_config",
                return_value=SyncConfig("https://worker.example", "token"),
            ),
            patch("codex_session_manager.cli.shutil.which", return_value="/usr/bin/codex"),
            patch("codex_session_manager.cli.AppServerClient") as client_type,
            patch("codex_session_manager.cli.CloudClient") as cloud_type,
            patch(
                "codex_session_manager.cli.sync_sessions", return_value=result
            ) as sync,
            contextlib.redirect_stdout(output),
        ):
            exit_code = main(["sync"])

        self.assertEqual(exit_code, 1)
        self.assertIn("uploaded: 1", output.getvalue())
        self.assertIn("skipped: 2", output.getvalue())
        self.assertIn("failed: 1", output.getvalue())
        self.assertIn("session-bad: thread unavailable", output.getvalue())
        sync.assert_called_once_with(
            client_type.return_value,
            cloud_type.return_value,
            force_all=False,
        )
        client_type.return_value.close.assert_called_once_with()

    def test_sync_status_checks_cloud_without_codex(self):
        config = SyncConfig("https://worker.example", "token")
        output = io.StringIO()
        with (
            patch("codex_session_manager.cli.load_config", return_value=config),
            patch("codex_session_manager.cli.CloudClient") as cloud_type,
            patch("codex_session_manager.cli.shutil.which") as which,
            patch("codex_session_manager.cli.AppServerClient") as app_server_type,
            contextlib.redirect_stdout(output),
        ):
            cloud_type.return_value.get_index.return_value = {
                "schema_version": 1,
                "generated_at": 123.5,
                "sessions": [{"id": "one"}, {"id": "two"}],
            }
            exit_code = main(["sync", "status"])

        self.assertEqual(exit_code, 0)
        cloud_type.assert_called_once_with(config)
        cloud_type.return_value.health.assert_called_once_with()
        cloud_type.return_value.get_index.assert_called_once_with()
        which.assert_not_called()
        app_server_type.assert_not_called()
        self.assertIn("count: 2", output.getvalue())
        self.assertIn("generated_at: 123.5", output.getvalue())

    def test_sync_cloud_error_is_user_facing_and_closes_app_server(self):
        with (
            patch(
                "codex_session_manager.cli.load_config",
                return_value=SyncConfig("https://worker.example", "token"),
            ),
            patch("codex_session_manager.cli.shutil.which", return_value="/usr/bin/codex"),
            patch("codex_session_manager.cli.AppServerClient") as client_type,
            patch("codex_session_manager.cli.CloudClient"),
            patch(
                "codex_session_manager.cli.sync_sessions",
                side_effect=CloudError("service unavailable"),
            ),
            contextlib.redirect_stderr(io.StringIO()) as errors,
        ):
            result = main(["sync"])

        self.assertEqual(result, 2)
        self.assertIn("service unavailable", errors.getvalue())
        client_type.return_value.close.assert_called_once_with()

    def test_sync_app_server_error_is_user_facing_and_closes_app_server(self):
        with (
            patch(
                "codex_session_manager.cli.load_config",
                return_value=SyncConfig("https://worker.example", "token"),
            ),
            patch("codex_session_manager.cli.shutil.which", return_value="/usr/bin/codex"),
            patch("codex_session_manager.cli.AppServerClient") as client_type,
            patch("codex_session_manager.cli.CloudClient"),
            patch(
                "codex_session_manager.cli.sync_sessions",
                side_effect=AppServerError("protocol failed"),
            ),
            contextlib.redirect_stderr(io.StringIO()) as errors,
        ):
            result = main(["sync"])

        self.assertEqual(result, 2)
        self.assertIn("protocol failed", errors.getvalue())
        client_type.return_value.close.assert_called_once_with()

    def test_cloud_browsing_uses_configured_client_in_read_only_mode_without_codex(self):
        config = SyncConfig("https://worker.example", "token")
        with (
            patch("codex_session_manager.cli.load_config", return_value=config),
            patch("codex_session_manager.cli.CloudClient") as cloud_type,
            patch("codex_session_manager.cli.CloudSessionRepository") as repository_type,
            patch("codex_session_manager.cli.CloudPreviewService") as preview_type,
            patch("codex_session_manager.cli.run_tui", return_value=None) as run_tui,
            patch("codex_session_manager.cli.shutil.which") as which,
        ):
            result = main(["--no-color", "cloud"])

        self.assertEqual(result, 0)
        cloud_type.assert_called_once_with(config)
        repository_type.assert_called_once_with(cloud_type.return_value)
        preview_type.assert_called_once_with(cloud_type.return_value)
        run_tui.assert_called_once_with(
            repository_type.return_value,
            preview_type.return_value,
            use_color=False,
            allow_select=False,
            empty_message="云端没有会话，按 r 刷新",
        )
        which.assert_not_called()

    def test_cloud_quit_is_success_and_cloud_error_is_user_facing(self):
        with (
            patch(
                "codex_session_manager.cli.load_config",
                side_effect=CloudError("service unavailable"),
            ),
            contextlib.redirect_stderr(io.StringIO()) as errors,
        ):
            result = main(["cloud"])

        self.assertEqual(result, 2)
        self.assertIn("service unavailable", errors.getvalue())

    def test_cloud_repository_error_from_tui_is_user_facing(self):
        with (
            patch(
                "codex_session_manager.cli.load_config",
                return_value=SyncConfig("https://worker.example", "token"),
            ),
            patch(
                "codex_session_manager.cli.run_tui",
                side_effect=CloudError("Cloud session data is invalid."),
            ),
            contextlib.redirect_stderr(io.StringIO()) as errors,
        ):
            result = main(["cloud"])

        self.assertEqual(result, 2)
        self.assertIn("Cloud session data is invalid.", errors.getvalue())

    def test_codex_present_builds_shared_app_server_compatibility_services(self):
        with (
            patch.dict(os.environ, {"CODEX_HOME": "/tmp/from-env"}),
            patch(
                "codex_session_manager.cli.shutil.which",
                return_value="/opt/codex/bin/codex",
            ),
            patch("codex_session_manager.cli.AppServerClient") as client_type,
            patch("codex_session_manager.cli.CompatibilityState") as state_type,
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
            client_type.return_value,
            repository_type.return_value,
            state_type.return_value,
        )
        compatible_preview_type.assert_called_once_with(
            client_type.return_value,
            repository_type.return_value,
            preview_type.return_value,
            state_type.return_value,
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

    @patch("codex_session_manager.cli.os.execvpe")
    def test_resume_command_uses_resolved_executable_home_and_exact_full_id(
        self, execvpe
    ):
        session_id = "会话-12345678-abcd-ef00-0123456789ab"
        codex_path = "/opt/codex/bin/codex"
        codex_home = Path("/tmp/自定义-codex")

        with patch.dict(
            os.environ,
            {"CODEX_HOME": "/tmp/from-env", "KEEP": "preserved"},
            clear=True,
        ):
            resume_command(session_id, codex_path, codex_home)
            self.assertEqual(os.environ["CODEX_HOME"], "/tmp/from-env")

        execvpe.assert_called_once_with(
            codex_path,
            ["codex", "resume", session_id],
            {"CODEX_HOME": str(codex_home), "KEEP": "preserved"},
        )

    def test_app_server_closes_before_resume_handoff(self):
        lifecycle = Mock()
        session_id = "会话-12345678-abcd-ef00-0123456789ab"
        with (
            patch("codex_session_manager.cli.shutil.which", return_value="/usr/bin/codex"),
            patch("codex_session_manager.cli.AppServerClient") as client_type,
            patch("codex_session_manager.cli.run_tui", return_value=session_id),
            patch("codex_session_manager.cli.resume_command") as resume,
        ):
            lifecycle.attach_mock(client_type.return_value.close, "close")
            lifecycle.attach_mock(resume, "resume")
            result = main(["--codex-home", "/tmp/from-flag"])

        self.assertEqual(result, 0)
        self.assertEqual(
            lifecycle.mock_calls,
            [
                call.close(),
                call.resume(
                    session_id,
                    "/usr/bin/codex",
                    Path("/tmp/from-flag"),
                ),
            ],
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

    @patch("codex_session_manager.cli.os.execvpe")
    @patch(
        "codex_session_manager.cli.run_tui",
        return_value="会话-12345678-abcd-ef00-0123456789ab",
    )
    @patch("codex_session_manager.cli.shutil.which", return_value="/usr/bin/codex")
    def test_selected_session_is_resumed_with_effective_environment(
        self, _which, _run_tui, execvpe
    ):
        with patch.dict(
            os.environ,
            {"CODEX_HOME": "/tmp/original", "KEEP": "preserved"},
            clear=True,
        ):
            self.assertEqual(
                main(["--codex-home", "/tmp/from-flag"]),
                0,
            )

        execvpe.assert_called_once_with(
            "/usr/bin/codex",
            ["codex", "resume", "会话-12345678-abcd-ef00-0123456789ab"],
            {"CODEX_HOME": "/tmp/from-flag", "KEEP": "preserved"},
        )


if __name__ == "__main__":
    unittest.main()

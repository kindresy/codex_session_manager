import tempfile
import unittest
from pathlib import Path

from codex_session_manager.app_server import AppServerError
from codex_session_manager.models import Preview, Session
from codex_session_manager.compatibility import (
    CompatibilityState,
    CompatiblePreviewService,
    CompatibleSessionRepository,
)
from codex_session_manager.preview import PreviewService
from codex_session_manager.repository import SessionRepository
from tests.fixture_loader import copy_rollout_fixture


SESSION = Session(
    "thread-123",
    "来自 App Server 的问题",
    "/tmp/project",
    1.0,
    2.0,
    "",
)
FALLBACK_SESSION = Session(
    "local-456",
    "来自本地存储的问题",
    "/tmp/project",
    1.0,
    2.0,
    "/tmp/rollout.jsonl",
)


class ListingService:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def list_sessions(self):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class AppServerPreviewingService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def get_preview(self, session):
        self.calls.append(session)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class LocalPreviewingService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def get(self, session):
        self.calls.append(session)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class CompatibleSessionRepositoryTests(unittest.TestCase):
    def test_primary_sessions_win_without_using_fallback(self):
        primary = ListingService([SESSION])
        fallback = ListingService([FALLBACK_SESSION])
        state = CompatibilityState()

        repository = CompatibleSessionRepository(primary, fallback, state)

        self.assertEqual(repository.list_sessions(), [SESSION])
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 0)
        self.assertEqual(repository.warning, "")

    def test_successful_empty_primary_result_is_authoritative(self):
        primary = ListingService([])
        fallback = ListingService([FALLBACK_SESSION])
        state = CompatibilityState()

        repository = CompatibleSessionRepository(primary, fallback, state)

        self.assertEqual(repository.list_sessions(), [])
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 0)
        self.assertEqual(repository.warning, "")

    def test_app_server_error_uses_local_sessions_with_degraded_warning(self):
        primary = ListingService(AppServerError("server unavailable"))
        fallback = ListingService([FALLBACK_SESSION])
        state = CompatibilityState()

        repository = CompatibleSessionRepository(primary, fallback, state)

        self.assertEqual(repository.list_sessions(), [FALLBACK_SESSION])
        self.assertEqual(fallback.calls, 1)
        self.assertEqual(repository.warning, "Codex App Server 不可用，已切换到本地兼容模式。")

    def test_empty_local_fallback_prompts_for_an_upgrade(self):
        primary = ListingService(AppServerError("server unavailable"))
        fallback = ListingService([])
        state = CompatibilityState()

        repository = CompatibleSessionRepository(primary, fallback, state)

        self.assertEqual(repository.list_sessions(), [])
        self.assertEqual(fallback.calls, 1)
        self.assertEqual(
            repository.warning,
            "Codex App Server 不可用，且本地会话不可读；请升级 codex-session-manager。",
        )

    def test_unexpected_primary_errors_are_not_hidden(self):
        primary = ListingService(RuntimeError("programming error"))
        fallback = ListingService([FALLBACK_SESSION])
        repository = CompatibleSessionRepository(
            primary, fallback, CompatibilityState()
        )

        with self.assertRaisesRegex(RuntimeError, "programming error"):
            repository.list_sessions()

        self.assertEqual(fallback.calls, 0)


class CompatiblePreviewServiceTests(unittest.TestCase):
    def test_primary_preview_wins_without_using_fallback(self):
        app_server_preview = Preview("第一条问题", "最后一个问题", "App Server 回答")
        local_preview = Preview("第一条问题", "本地问题", "本地回答")
        primary = AppServerPreviewingService(app_server_preview)
        local_repository = ListingService([FALLBACK_SESSION])
        fallback = LocalPreviewingService(local_preview)
        state = CompatibilityState()

        service = CompatiblePreviewService(
            primary, local_repository, fallback, state
        )

        self.assertEqual(service.get(SESSION), app_server_preview)
        self.assertEqual(service.get(SESSION), app_server_preview)
        self.assertEqual(primary.calls, [SESSION])
        self.assertEqual(local_repository.calls, 0)
        self.assertEqual(fallback.calls, [])

    def test_app_server_error_resolves_exact_local_id_before_preview(self):
        session_without_rollout = Session(
            "thread-without-path",
            "App Server 会话",
            "/tmp/project",
            1.0,
            2.0,
            "",
        )
        local_session = Session(
            session_without_rollout.id,
            "本地摘要",
            "/tmp/local-project",
            3.0,
            4.0,
            "/tmp/exact-rollout.jsonl",
        )
        local_preview = Preview("App Server 会话", "本地问题", "本地回答")
        primary = AppServerPreviewingService(AppServerError("thread/read failed"))
        local_repository = ListingService(
            [
                FALLBACK_SESSION,
                local_session,
                Session(
                    "thread-without-path-suffix",
                    "不能短 ID 匹配",
                    "",
                    0.0,
                    0.0,
                    "/tmp/wrong.jsonl",
                ),
            ]
        )
        fallback = LocalPreviewingService(local_preview)
        state = CompatibilityState()

        service = CompatiblePreviewService(
            primary, local_repository, fallback, state
        )

        self.assertEqual(service.get(session_without_rollout), local_preview)
        self.assertEqual(primary.calls, [session_without_rollout])
        self.assertEqual(local_repository.calls, 1)
        self.assertEqual(len(fallback.calls), 1)
        resolved = fallback.calls[0]
        self.assertEqual(resolved.id, session_without_rollout.id)
        self.assertEqual(resolved.first_question, session_without_rollout.first_question)
        self.assertEqual(resolved.rollout_path, local_session.rollout_path)
        self.assertEqual(
            state.warning,
            "Codex App Server 预览不可用，已切换到本地兼容模式。",
        )

    def test_unexpected_preview_errors_are_not_hidden(self):
        primary = AppServerPreviewingService(RuntimeError("programming error"))
        fallback = LocalPreviewingService(Preview("", "", ""))
        service = CompatiblePreviewService(
            primary,
            ListingService([FALLBACK_SESSION]),
            fallback,
            CompatibilityState(),
        )

        with self.assertRaisesRegex(RuntimeError, "programming error"):
            service.get(SESSION)

        self.assertEqual(fallback.calls, [])

    def test_listing_degradation_bypasses_app_server_preview(self):
        state = CompatibilityState()
        primary_repository = ListingService(AppServerError("list failed"))
        local_repository = ListingService([FALLBACK_SESSION])
        repository = CompatibleSessionRepository(
            primary_repository, local_repository, state
        )
        primary_preview = AppServerPreviewingService(
            Preview("", "", "should not be used")
        )
        local_preview = Preview("本地问题", "本地问题", "本地回答")
        fallback_preview = LocalPreviewingService(local_preview)
        previews = CompatiblePreviewService(
            primary_preview, local_repository, fallback_preview, state
        )

        sessions = repository.list_sessions()

        self.assertEqual(previews.get(sessions[0]), local_preview)
        self.assertEqual(primary_preview.calls, [])
        self.assertEqual(fallback_preview.calls, [FALLBACK_SESSION])
        self.assertEqual(
            repository.warning,
            "Codex App Server 不可用，已切换到本地兼容模式。",
        )

    def test_repository_refresh_invalidates_successful_preview_cache(self):
        state = CompatibilityState()
        primary_repository = ListingService([SESSION])
        local_repository = ListingService([FALLBACK_SESSION])
        repository = CompatibleSessionRepository(
            primary_repository, local_repository, state
        )
        app_server_preview = Preview("问题", "最近问题", "最近回答")
        primary_preview = AppServerPreviewingService(app_server_preview)
        previews = CompatiblePreviewService(
            primary_preview,
            local_repository,
            LocalPreviewingService(Preview("", "", "")),
            state,
        )

        first_session = repository.list_sessions()[0]
        equal_session = Session(
            first_session.id,
            first_session.first_question,
            first_session.cwd,
            first_session.created_at,
            first_session.last_opened_at,
            first_session.rollout_path,
        )
        self.assertEqual(previews.get(first_session), app_server_preview)
        self.assertEqual(previews.get(equal_session), app_server_preview)
        self.assertEqual(primary_preview.calls, [first_session])

        refreshed_session = repository.list_sessions()[0]

        self.assertEqual(previews.get(refreshed_session), app_server_preview)
        self.assertEqual(primary_preview.calls, [first_session, refreshed_session])

    def test_preview_degradation_bypasses_repeated_reads_until_refresh(self):
        state = CompatibilityState()
        primary_repository = ListingService([SESSION])
        local_repository = ListingService([FALLBACK_SESSION])
        repository = CompatibleSessionRepository(
            primary_repository, local_repository, state
        )
        primary_preview = AppServerPreviewingService(
            AppServerError("thread/read timed out")
        )
        fallback_preview = LocalPreviewingService(
            Preview("问题", "本地问题", "本地回答")
        )
        previews = CompatiblePreviewService(
            primary_preview, local_repository, fallback_preview, state
        )
        session = repository.list_sessions()[0]

        previews.get(session)
        previews.get(session)

        self.assertEqual(primary_preview.calls, [session])
        self.assertEqual(fallback_preview.calls, [session, session])

        refreshed_session = repository.list_sessions()[0]
        previews.get(refreshed_session)

        self.assertEqual(primary_preview.calls, [session, refreshed_session])

    def test_pathless_session_uses_real_local_repository_and_preview_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            copy_rollout_fixture(
                home,
                "fallback/rollout-2026-08-22T20-05-43-fixture.jsonl",
            )
            local_repository = SessionRepository(home)
            state = CompatibilityState()
            server_session = Session(
                "fixture-fallback",
                "来自 App Server 的问题",
                "/tmp/server-project",
                1.0,
                2.0,
                "",
            )
            previews = CompatiblePreviewService(
                AppServerPreviewingService(AppServerError("thread/read failed")),
                local_repository,
                PreviewService(),
                state,
            )

            preview = previews.get(server_session)

        self.assertEqual(preview.first_question, "来自 App Server 的问题")
        self.assertEqual(preview.latest_user, "fixture real prompt")
        self.assertEqual(preview.latest_assistant, "fixture answer")
        self.assertEqual(preview.error, "")
        self.assertEqual(
            state.warning,
            "Codex App Server 预览不可用，已切换到本地兼容模式。",
        )


if __name__ == "__main__":
    unittest.main()

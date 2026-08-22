import unittest

from codex_session_manager.app_server import AppServerError
from codex_session_manager.models import Preview, Session
from codex_session_manager.compatibility import (
    CompatiblePreviewService,
    CompatibleSessionRepository,
)


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

        repository = CompatibleSessionRepository(primary, fallback)

        self.assertEqual(repository.list_sessions(), [SESSION])
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 0)
        self.assertEqual(repository.warning, "")

    def test_successful_empty_primary_result_is_authoritative(self):
        primary = ListingService([])
        fallback = ListingService([FALLBACK_SESSION])

        repository = CompatibleSessionRepository(primary, fallback)

        self.assertEqual(repository.list_sessions(), [])
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 0)
        self.assertEqual(repository.warning, "")

    def test_app_server_error_uses_local_sessions_with_degraded_warning(self):
        primary = ListingService(AppServerError("server unavailable"))
        fallback = ListingService([FALLBACK_SESSION])

        repository = CompatibleSessionRepository(primary, fallback)

        self.assertEqual(repository.list_sessions(), [FALLBACK_SESSION])
        self.assertEqual(fallback.calls, 1)
        self.assertEqual(repository.warning, "Codex App Server 不可用，已切换到本地兼容模式。")

    def test_empty_local_fallback_prompts_for_an_upgrade(self):
        primary = ListingService(AppServerError("server unavailable"))
        fallback = ListingService([])

        repository = CompatibleSessionRepository(primary, fallback)

        self.assertEqual(repository.list_sessions(), [])
        self.assertEqual(fallback.calls, 1)
        self.assertEqual(
            repository.warning,
            "Codex App Server 不可用，且本地会话不可读；请升级 codex-session-manager。",
        )

    def test_unexpected_primary_errors_are_not_hidden(self):
        primary = ListingService(RuntimeError("programming error"))
        fallback = ListingService([FALLBACK_SESSION])
        repository = CompatibleSessionRepository(primary, fallback)

        with self.assertRaisesRegex(RuntimeError, "programming error"):
            repository.list_sessions()

        self.assertEqual(fallback.calls, 0)


class CompatiblePreviewServiceTests(unittest.TestCase):
    def test_primary_preview_wins_without_using_fallback(self):
        app_server_preview = Preview("第一条问题", "最后一个问题", "App Server 回答")
        local_preview = Preview("第一条问题", "本地问题", "本地回答")
        primary = AppServerPreviewingService(app_server_preview)
        fallback = LocalPreviewingService(local_preview)

        service = CompatiblePreviewService(primary, fallback)

        self.assertEqual(service.get(SESSION), app_server_preview)
        self.assertEqual(primary.calls, [SESSION])
        self.assertEqual(fallback.calls, [])

    def test_app_server_error_uses_local_preview_without_rollout_path(self):
        session_without_rollout = Session(
            "thread-without-path",
            "App Server 会话",
            "/tmp/project",
            1.0,
            2.0,
            "",
        )
        local_preview = Preview("App Server 会话", "本地问题", "本地回答")
        primary = AppServerPreviewingService(AppServerError("thread/read failed"))
        fallback = LocalPreviewingService(local_preview)

        service = CompatiblePreviewService(primary, fallback)

        self.assertEqual(service.get(session_without_rollout), local_preview)
        self.assertEqual(primary.calls, [session_without_rollout])
        self.assertEqual(fallback.calls, [session_without_rollout])

    def test_unexpected_preview_errors_are_not_hidden(self):
        primary = AppServerPreviewingService(RuntimeError("programming error"))
        fallback = LocalPreviewingService(Preview("", "", ""))
        service = CompatiblePreviewService(primary, fallback)

        with self.assertRaisesRegex(RuntimeError, "programming error"):
            service.get(SESSION)

        self.assertEqual(fallback.calls, [])


if __name__ == "__main__":
    unittest.main()

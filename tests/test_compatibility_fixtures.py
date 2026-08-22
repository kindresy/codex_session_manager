import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from codex_session_manager.models import Session
from codex_session_manager.preview import PreviewService
from tests.fixture_loader import (
    copy_rollout_fixture,
    load_fallback_fixture,
    load_sql_fixture,
)


class CompatibilityFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_current_schema_filters_non_cli_sessions(self):
        sessions = load_sql_fixture(self.home, "current_schema.sql")

        self.assertEqual([item.id for item in sessions], ["cli-current"])
        self.assertEqual(sessions[0].first_question, "current question")
        self.assertEqual(sessions[0].created_at, 1_700_000_000.0)

    def test_minimal_schema_uses_legacy_timestamp_columns(self):
        sessions = load_sql_fixture(self.home, "minimal_schema.sql")

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].id, "cli-minimal")
        self.assertEqual(sessions[0].first_question, "minimal question")
        self.assertEqual(sessions[0].last_opened_at, 1_700_000_200.0)

    def test_incompatible_sqlite_uses_jsonl_filename_fallback(self):
        sessions = load_fallback_fixture(self.home)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].id, "fixture-fallback")
        self.assertEqual(sessions[0].first_question, "fixture real prompt")
        expected = datetime(2026, 8, 22, 20, 5, 43)
        self.assertEqual(sessions[0].created_at, expected.timestamp())

    def test_mixed_context_fixture_has_deterministic_preview(self):
        rollout = copy_rollout_fixture(self.home, "mixed-context.jsonl")
        session = Session(
            "preview-fixture",
            "fixture first question",
            "/tmp/fixture",
            1.0,
            2.0,
            str(rollout),
        )

        preview = PreviewService().get(session)

        self.assertEqual(preview.latest_user, "fixture latest question")
        self.assertEqual(preview.latest_assistant, "fixture latest answer")
        self.assertEqual(preview.error, "")


if __name__ == "__main__":
    unittest.main()

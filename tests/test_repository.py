import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from codex_session_manager.repository import (
    SessionRepository,
    clean_user_text,
    parse_timestamp,
)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def create_database(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.home / "state_5.sqlite")
        connection.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                source TEXT NOT NULL,
                cwd TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                first_user_message TEXT NOT NULL DEFAULT '',
                recency_at INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        return connection

    def insert_thread(
        self,
        connection,
        session_id,
        question,
        recency,
        *,
        source="cli",
        archived=0,
    ):
        connection.execute(
            "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                str(self.home / f"{session_id}.jsonl"),
                1_700_000_000,
                recency - 10,
                source,
                "/tmp/project",
                archived,
                question,
                recency,
            ),
        )

    def test_sqlite_filters_and_orders_cli_sessions(self):
        connection = self.create_database()
        self.insert_thread(connection, "cli-old", "旧问题", 1_700_000_100)
        self.insert_thread(connection, "cli-new", "最新问题", 1_700_000_300)
        self.insert_thread(connection, "archived", "归档", 1_700_000_400, archived=1)
        self.insert_thread(connection, "editor", "编辑器", 1_700_000_500, source="vscode")
        self.insert_thread(
            connection,
            "worker",
            "子代理",
            1_700_000_600,
            source='{"subagent":{"thread_spawn":{}}}',
        )
        connection.commit()
        connection.close()

        sessions = SessionRepository(self.home).list_sessions()

        self.assertEqual([item.id for item in sessions], ["cli-new", "cli-old"])
        self.assertEqual(sessions[0].first_question, "最新问题")
        self.assertEqual(sessions[0].last_opened_at, 1_700_000_300.0)

    def test_sqlite_uses_available_millisecond_columns(self):
        connection = sqlite3.connect(self.home / "state_6.sqlite")
        connection.execute(
            """
            CREATE TABLE threads (
                id TEXT, rollout_path TEXT, source TEXT, cwd TEXT,
                archived INTEGER, first_user_message TEXT,
                created_at_ms INTEGER, recency_at_ms INTEGER
            )
            """
        )
        connection.execute(
            "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "millis-id",
                "/tmp/millis.jsonl",
                "cli",
                "/tmp/millis",
                0,
                "毫秒问题",
                1_700_000_000_000,
                1_700_000_100_000,
            ),
        )
        connection.commit()
        connection.close()

        session = SessionRepository(self.home).list_sessions()[0]

        self.assertEqual(session.created_at, 1_700_000_000.0)
        self.assertEqual(session.last_opened_at, 1_700_000_100.0)

    def test_incompatible_database_falls_back_to_rollouts(self):
        connection = sqlite3.connect(self.home / "state_5.sqlite")
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.commit()
        connection.close()

        rollout = self.home / "sessions/2026/08/22/rollout.jsonl"
        rollout.parent.mkdir(parents=True)
        records = [
            {
                "timestamp": "2026-08-22T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": "fallback-id", "cwd": "/tmp/fallback", "source": "cli"},
            },
            {
                "timestamp": "2026-08-22T12:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "<environment_context>secret</environment_context>"},
                        {"type": "input_text", "text": "真正的问题"},
                    ],
                },
            },
        ]
        rollout.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records))
        (rollout.parent / "broken.jsonl").write_text("{bad json\n")

        sessions = SessionRepository(self.home).list_sessions()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].id, "fallback-id")
        self.assertEqual(sessions[0].first_question, "真正的问题")
        self.assertEqual(sessions[0].rollout_path, str(rollout))

    def test_clean_user_text_ignores_injected_context(self):
        self.assertEqual(clean_user_text("<environment_context>x</environment_context>"), "")
        self.assertEqual(clean_user_text("# AGENTS.md instructions for /tmp\n\n<INSTRUCTIONS>x</INSTRUCTIONS>"), "")
        self.assertEqual(clean_user_text("  帮我实现功能  "), "帮我实现功能")

    def test_parse_timestamp_accepts_iso_and_epoch(self):
        self.assertEqual(parse_timestamp("2023-11-14T22:13:20Z"), 1_700_000_000.0)
        self.assertEqual(parse_timestamp(1_700_000_000_000), 1_700_000_000.0)


if __name__ == "__main__":
    unittest.main()

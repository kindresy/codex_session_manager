import unittest
from unittest import mock

from codex_session_manager.cloud_client import CloudError
from codex_session_manager.models import Session
from codex_session_manager.sync import SyncResult, sync_sessions


def _session(session_id, updated_at, question=None, last_opened_at=None):
    return Session(
        session_id,
        question or f"question {session_id}",
        f"/work/{session_id}",
        updated_at - 10,
        updated_at if last_opened_at is None else last_opened_at,
        "",
        updated_at,
    )


def _entry(session_id, updated_at, question=None):
    return {
        "id": session_id,
        "question": question or f"question {session_id}",
        "created_at": updated_at - 10,
        "updated_at": updated_at,
        "cwd": f"/work/{session_id}",
    }


class _AppServer:
    def __init__(self, sessions, read_errors=None):
        self.sessions = sessions
        self.read_errors = read_errors or {}
        self.read_ids = []

    def list_sessions(self):
        return list(self.sessions)

    def read_thread(self, session_id):
        self.read_ids.append(session_id)
        if session_id in self.read_errors:
            raise self.read_errors[session_id]
        return {"thread": {"turns": []}}


class _Cloud:
    def __init__(self, index, upload_errors=None, index_error=None):
        self.index = index
        self.upload_errors = upload_errors or {}
        self.index_error = index_error
        self.uploads = []
        self.index_writes = []

    def get_index(self):
        return self.index

    def put_session(self, payload):
        self.uploads.append(payload)
        if payload["id"] in self.upload_errors:
            raise self.upload_errors[payload["id"]]
        return payload

    def put_index(self, payload):
        self.index_writes.append(payload)
        if self.index_error is not None:
            raise self.index_error
        return payload


class SyncSessionsTests(unittest.TestCase):
    def test_uploads_a_session_into_an_empty_cloud_index(self):
        app_server = _AppServer([_session("new", 20)])
        cloud = _Cloud({"schema_version": 1, "sessions": [], "deleted_ids": []})

        with mock.patch("codex_session_manager.sync.time.time", return_value=123.5):
            result = sync_sessions(app_server, cloud)

        self.assertEqual(result, SyncResult(uploaded=1, skipped=0, failed=()))
        self.assertEqual(app_server.read_ids, ["new"])
        self.assertEqual([payload["id"] for payload in cloud.uploads], ["new"])
        self.assertEqual(
            cloud.index_writes,
            [
                {
                    "schema_version": 1,
                    "generated_at": 123.5,
                    "sessions": [_entry("new", 20)],
                    "deleted_ids": [],
                }
            ],
        )

    def test_uploads_only_sessions_newer_than_the_remote_timestamp(self):
        app_server = _AppServer([_session("changed", 30), _session("same", 20)])
        cloud = _Cloud(
            {
                "schema_version": 1,
                "sessions": [_entry("changed", 25), _entry("same", 20)],
                "deleted_ids": [],
            }
        )

        result = sync_sessions(app_server, cloud)

        self.assertEqual(result, SyncResult(uploaded=1, skipped=1, failed=()))
        self.assertEqual(app_server.read_ids, ["changed"])
        self.assertEqual([payload["id"] for payload in cloud.uploads], ["changed"])
        self.assertEqual(
            [entry["id"] for entry in cloud.index_writes[0]["sessions"]],
            ["changed", "same"],
        )

    def test_uploads_when_content_changes_without_new_recency(self):
        app_server = _AppServer([_session("changed", 30, last_opened_at=20)])
        cloud = _Cloud(
            {
                "schema_version": 1,
                "sessions": [_entry("changed", 20)],
                "deleted_ids": [],
            }
        )

        result = sync_sessions(app_server, cloud)

        self.assertEqual(result, SyncResult(uploaded=1, skipped=0, failed=()))
        self.assertEqual(cloud.uploads[0]["updated_at"], 30)

    def test_force_all_reuploads_unchanged_sessions(self):
        app_server = _AppServer([_session("same", 20)])
        cloud = _Cloud(
            {
                "schema_version": 1,
                "sessions": [_entry("same", 20)],
                "deleted_ids": [],
            }
        )

        result = sync_sessions(app_server, cloud, force_all=True)

        self.assertEqual(result, SyncResult(uploaded=1, skipped=0, failed=()))
        self.assertEqual(app_server.read_ids, ["same"])

    def test_retains_remote_only_sessions_and_sorts_the_index_by_recency(self):
        remote_only = _entry("remote-only", 40)
        app_server = _AppServer([_session("new", 30)])
        cloud = _Cloud(
            {
                "schema_version": 1,
                "sessions": [remote_only],
                "deleted_ids": [],
            }
        )

        sync_sessions(app_server, cloud)

        self.assertEqual(
            cloud.index_writes[0]["sessions"],
            [remote_only, _entry("new", 30)],
        )

    def test_never_uploads_tombstoned_sessions_even_when_forced(self):
        app_server = _AppServer([_session("deleted", 30), _session("live", 20)])
        cloud = _Cloud(
            {
                "schema_version": 1,
                "sessions": [],
                "deleted_ids": ["deleted"],
            }
        )

        result = sync_sessions(app_server, cloud, force_all=True)

        self.assertEqual(result, SyncResult(uploaded=1, skipped=1, failed=()))
        self.assertEqual(app_server.read_ids, ["live"])
        self.assertEqual(cloud.index_writes[0]["deleted_ids"], ["deleted"])

    def test_failed_thread_read_is_reported_while_other_uploads_continue(self):
        old_entry = _entry("old", 10, "old remote question")
        app_server = _AppServer(
            [_session("old", 30), _session("good", 20)],
            {"old": RuntimeError("read broke")},
        )
        cloud = _Cloud(
            {
                "schema_version": 1,
                "sessions": [old_entry],
                "deleted_ids": [],
            }
        )

        result = sync_sessions(app_server, cloud)

        self.assertEqual(
            result,
            SyncResult(uploaded=1, skipped=0, failed=(("old", "read broke"),)),
        )
        self.assertEqual(app_server.read_ids, ["old", "good"])
        self.assertEqual([payload["id"] for payload in cloud.uploads], ["good"])
        self.assertIn(old_entry, cloud.index_writes[0]["sessions"])

    def test_failed_upload_is_reported_and_new_entry_is_not_indexed(self):
        app_server = _AppServer([_session("bad", 30), _session("good", 20)])
        cloud = _Cloud(
            {"schema_version": 1, "sessions": [], "deleted_ids": []},
            {"bad": CloudError("upload broke")},
        )

        result = sync_sessions(app_server, cloud)

        self.assertEqual(
            result,
            SyncResult(uploaded=1, skipped=0, failed=(("bad", "upload broke"),)),
        )
        self.assertEqual([payload["id"] for payload in cloud.uploads], ["bad", "good"])
        self.assertEqual(
            [entry["id"] for entry in cloud.index_writes[0]["sessions"]],
            ["good"],
        )

    def test_final_index_write_error_is_raised_after_session_uploads(self):
        app_server = _AppServer([_session("new", 20)])
        cloud = _Cloud(
            {"schema_version": 1, "sessions": [], "deleted_ids": []},
            index_error=CloudError("index broke"),
        )

        with self.assertRaisesRegex(CloudError, "index broke"):
            sync_sessions(app_server, cloud)

        self.assertEqual([payload["id"] for payload in cloud.uploads], ["new"])
        self.assertEqual(len(cloud.index_writes), 1)


if __name__ == "__main__":
    unittest.main()

import unittest

from codex_session_manager.cloud_client import CloudError
from codex_session_manager.cloud_repository import (
    CloudPreviewService,
    CloudSessionRepository,
)
from codex_session_manager.models import Preview, Session


class _Cloud:
    def __init__(self):
        self.session_calls = []
        self.index = {
            "schema_version": 1,
            "sessions": [
                {
                    "id": "newest",
                    "question": "first question",
                    "created_at": 10.0,
                    "updated_at": 20.0,
                    "cwd": "/work/project",
                }
            ],
        }
        self.session = {
            "schema_version": 1,
            "id": "newest",
            "question": "first question",
            "created_at": 10.0,
            "updated_at": 20.0,
            "cwd": "/work/project",
            "turns": [
                {
                    "items": [
                        {"type": "user", "text": "old user"},
                        {"type": "command", "output": "ignored"},
                        {"type": "assistant", "text": "old assistant"},
                    ]
                },
                {
                    "items": [
                        {"type": "assistant", "text": "latest assistant"},
                        {"type": "file_change", "diff": "ignored"},
                        {"type": "user", "text": "latest user"},
                    ]
                },
            ],
        }

    def get_index(self):
        return self.index

    def get_session(self, session_id):
        self.session_calls.append(session_id)
        return self.session


class CloudRepositoryTests(unittest.TestCase):
    def test_maps_index_entries_to_existing_session_model(self):
        cloud = _Cloud()

        sessions = CloudSessionRepository(cloud).list_sessions()

        self.assertEqual(
            sessions,
            [
                Session(
                    "newest",
                    "first question",
                    "/work/project",
                    10.0,
                    20.0,
                    "",
                )
            ],
        )

    def test_preview_uses_metadata_and_latest_messages_across_all_turns(self):
        cloud = _Cloud()
        session = CloudSessionRepository(cloud).list_sessions()[0]

        preview = CloudPreviewService(cloud).get(session)

        self.assertEqual(
            preview,
            Preview("first question", "latest user", "latest assistant"),
        )
        self.assertEqual(cloud.session_calls, ["newest"])

    def test_preview_cache_is_keyed_by_full_id_and_update_time(self):
        cloud = _Cloud()
        previews = CloudPreviewService(cloud)
        session = CloudSessionRepository(cloud).list_sessions()[0]

        first = previews.get(session)
        self.assertIs(previews.get(session), first)

        changed = Session(
            session.id,
            session.first_question,
            session.cwd,
            session.created_at,
            session.last_opened_at + 1,
            "",
        )
        previews.get(changed)

        self.assertEqual(cloud.session_calls, ["newest", "newest"])

    def test_invalid_index_containers_and_entries_raise_cloud_error(self):
        cloud = _Cloud()
        invalid_sessions = (
            None,
            [None],
            [{}],
        )

        for sessions in invalid_sessions:
            with self.subTest(sessions=sessions):
                cloud.index = {"schema_version": 1, "sessions": sessions}
                with self.assertRaises(CloudError):
                    CloudSessionRepository(cloud).list_sessions()

    def test_invalid_index_field_types_raise_cloud_error(self):
        cloud = _Cloud()
        valid = cloud.index["sessions"][0]
        invalid_values = {
            "id": 1,
            "question": None,
            "cwd": [],
            "created_at": "10",
            "updated_at": True,
        }

        for field, value in invalid_values.items():
            with self.subTest(field=field):
                cloud.index = {
                    "schema_version": 1,
                    "sessions": [{**valid, field: value}],
                }
                with self.assertRaises(CloudError):
                    CloudSessionRepository(cloud).list_sessions()

    def test_invalid_session_containers_raise_cloud_error(self):
        cloud = _Cloud()
        session = CloudSessionRepository(cloud).list_sessions()[0]
        invalid_turns = (
            None,
            [None],
            [{"items": None}],
            [{"items": [None]}],
        )

        for turns in invalid_turns:
            with self.subTest(turns=turns):
                cloud.session = {**cloud.session, "turns": turns}
                with self.assertRaises(CloudError):
                    CloudPreviewService(cloud).get(session)

    def test_invalid_session_field_types_raise_cloud_error(self):
        cloud = _Cloud()
        session = CloudSessionRepository(cloud).list_sessions()[0]
        valid = cloud.session
        invalid_values = {
            "id": None,
            "question": 1,
            "cwd": {},
            "created_at": "10",
            "updated_at": False,
        }

        for field, value in invalid_values.items():
            with self.subTest(field=field):
                cloud.session = {**valid, field: value}
                with self.assertRaises(CloudError):
                    CloudPreviewService(cloud).get(session)

    def test_invalid_message_item_fields_raise_cloud_error_but_unknown_types_are_ignored(self):
        cloud = _Cloud()
        session = CloudSessionRepository(cloud).list_sessions()[0]
        invalid_items = (
            {"type": None, "text": "message"},
            {"type": "user", "text": None},
            {"type": "assistant", "text": 1},
        )

        for item in invalid_items:
            with self.subTest(item=item):
                cloud.session = {**cloud.session, "turns": [{"items": [item]}]}
                with self.assertRaises(CloudError):
                    CloudPreviewService(cloud).get(session)

        cloud.session = {
            **cloud.session,
            "turns": [{"items": [{"type": "future_item", "text": 1}]}],
        }
        self.assertEqual(
            CloudPreviewService(cloud).get(session),
            Preview("first question", "", ""),
        )


if __name__ == "__main__":
    unittest.main()

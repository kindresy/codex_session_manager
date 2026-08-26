import unittest

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


if __name__ == "__main__":
    unittest.main()

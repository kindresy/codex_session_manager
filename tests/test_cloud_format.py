import unittest

from codex_session_manager.cloud_format import normalize_cloud_session
from codex_session_manager.models import Session


class CloudFormatTests(unittest.TestCase):
    def test_normalizes_supported_items_and_omits_private_or_unknown_items(self):
        session = Session(
            id="thread-123",
            first_question="保留的问题",
            cwd="/work/project",
            created_at=1_700_000_000.0,
            last_opened_at=1_700_000_100.0,
            rollout_path="",
            updated_at=1_700_000_200.0,
        )

        payload = normalize_cloud_session(
            session,
            {
                "thread": {
                    "turns": [
                        {
                            "items": [
                                {
                                    "type": "userMessage",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "<environment_context>private</environment_context>\n\n真实提问",
                                        }
                                    ],
                                },
                                {"type": "reasoning", "text": "private chain"},
                                {"type": "futureItem", "value": "ignore"},
                                {"type": "agentMessage", "text": "回答"},
                            ]
                        },
                        {
                            "items": [
                                {
                                    "type": "commandExecution",
                                    "command": "git status",
                                    "cwd": "/work/project",
                                    "status": "completed",
                                    "aggregatedOutput": "On branch main",
                                    "exitCode": 0,
                                },
                                {
                                    "type": "fileChange",
                                    "changes": [
                                        {
                                            "path": "src/example.py",
                                            "kind": {
                                                "type": "update",
                                                "move_path": None,
                                            },
                                            "diff": "- old\n+ new",
                                        }
                                    ],
                                },
                            ]
                        },
                    ]
                }
            },
        )

        self.assertEqual(
            payload,
            {
                "schema_version": 1,
                "id": "thread-123",
                "question": "保留的问题",
                "created_at": 1_700_000_000.0,
                "updated_at": 1_700_000_200.0,
                "cwd": "/work/project",
                "turns": [
                    {
                        "items": [
                            {"type": "user", "text": "真实提问"},
                            {"type": "assistant", "text": "回答"},
                        ]
                    },
                    {
                        "items": [
                            {
                                "type": "command",
                                "command": "git status",
                                "cwd": "/work/project",
                                "status": "completed",
                                "output": "On branch main",
                                "exit_code": 0,
                            },
                            {
                                "type": "file_change",
                                "path": "src/example.py",
                                "kind": "update",
                                "diff": "- old\n+ new",
                            },
                        ]
                    },
                ],
            },
        )

    def test_rejects_invalid_response_containers_and_malformed_known_items(self):
        session = Session("id", "question", "/work", 1.0, 2.0, "")
        for response in (
            None,
            {},
            {"thread": []},
            {"thread": {"turns": {}}},
            {"thread": {"turns": [{"items": "invalid"}]}},
            {"thread": {"turns": [{"items": [None]}]}},
            {"thread": {"turns": [{"items": [{"type": "agentMessage"}]}]}},
            {"thread": {"turns": [{"items": [{"type": "commandExecution"}]}]}},
            {"thread": {"turns": [{"items": [{"type": "fileChange"}]}]}},
        ):
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    normalize_cloud_session(session, response)

    def test_omits_well_formed_unknown_item_types(self):
        session = Session("id", "question", "/work", 1.0, 2.0, "")

        payload = normalize_cloud_session(
            session,
            {"thread": {"turns": [{"items": [{"type": "futureItem"}]}]}},
        )

        self.assertEqual(payload["turns"], [{"items": []}])

    def test_normalizes_missing_command_output_to_an_empty_string(self):
        session = Session("id", "question", "/work", 1.0, 2.0, "")

        payload = normalize_cloud_session(
            session,
            {
                "thread": {
                    "turns": [
                        {
                            "items": [
                                {
                                    "type": "commandExecution",
                                    "command": "true",
                                    "cwd": "/work",
                                    "status": "completed",
                                    "aggregatedOutput": None,
                                    "exitCode": 0,
                                }
                            ]
                        }
                    ]
                }
            },
        )

        self.assertEqual(
            payload["turns"],
            [
                {
                    "items": [
                        {
                            "type": "command",
                            "command": "true",
                            "cwd": "/work",
                            "status": "completed",
                            "output": "",
                            "exit_code": 0,
                        }
                    ]
                }
            ],
        )

    def test_preserves_a_null_command_exit_code(self):
        session = Session("id", "question", "/work", 1.0, 2.0, "")

        payload = normalize_cloud_session(
            session,
            {
                "thread": {
                    "turns": [
                        {
                            "items": [
                                {
                                    "type": "commandExecution",
                                    "command": "sleep 1",
                                    "cwd": "/work",
                                    "status": "inProgress",
                                    "aggregatedOutput": "still running",
                                    "exitCode": None,
                                }
                            ]
                        }
                    ]
                }
            },
        )

        self.assertEqual(
            payload["turns"][0]["items"],
            [
                {
                    "type": "command",
                    "command": "sleep 1",
                    "cwd": "/work",
                    "status": "inProgress",
                    "output": "still running",
                    "exit_code": None,
                }
            ],
        )

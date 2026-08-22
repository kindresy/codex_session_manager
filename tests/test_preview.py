import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_session_manager.models import Session
from codex_session_manager.preview import PreviewService


def message(role, text, *, text_type=None):
    return {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": role,
            "content": [
                {
                    "type": text_type or ("input_text" if role == "user" else "output_text"),
                    "text": text,
                }
            ],
        },
    }


class PreviewServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "rollout.jsonl"
        self.session = Session(
            "12345678-abcd",
            "第一条真实问题",
            "/tmp/project",
            1.0,
            2.0,
            str(self.path),
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def write_records(self, records):
        self.path.write_text(
            "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
            encoding="utf-8",
        )

    def test_extracts_latest_real_user_and_assistant_messages(self):
        self.write_records(
            [
                message("developer", "内部说明", text_type="input_text"),
                message("user", "<environment_context>隐藏</environment_context>"),
                message("user", "第一条真实问题"),
                message("assistant", "第一个回答"),
                {"type": "response_item", "payload": {"type": "function_call", "name": "tool"}},
                message("user", "最后一个问题"),
                message("assistant", "最后一个回答"),
            ]
        )

        preview = PreviewService().get(self.session)

        self.assertEqual(preview.first_question, "第一条真实问题")
        self.assertEqual(preview.latest_user, "最后一个问题")
        self.assertEqual(preview.latest_assistant, "最后一个回答")
        self.assertEqual(preview.error, "")

    def test_caches_by_path_and_modification_time(self):
        self.write_records([message("user", "第一条真实问题")])
        service = PreviewService()

        with patch.object(service, "_parse", wraps=service._parse) as parser:
            service.get(self.session)
            service.get(self.session)
            self.assertEqual(parser.call_count, 1)

            stat = self.path.stat()
            os.utime(self.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
            service.get(self.session)
            self.assertEqual(parser.call_count, 2)

    def test_missing_or_corrupt_rollout_returns_localized_error(self):
        missing = PreviewService().get(self.session)
        self.assertEqual(missing.error, "预览不可用")

        self.path.write_text("{broken json\n", encoding="utf-8")
        corrupt = PreviewService().get(self.session)
        self.assertEqual(corrupt.error, "预览不可用")
        self.assertEqual(corrupt.first_question, "第一条真实问题")


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timezone

from codex_session_manager.models import Preview, Session, normalize_epoch
from codex_session_manager.text import (
    clip_display,
    clip_display_left,
    display_width,
    wrap_display,
)


class ModelAndTextTests(unittest.TestCase):
    def test_normalize_epoch_accepts_seconds_and_milliseconds(self):
        expected = datetime.fromtimestamp(1_700_000_000, timezone.utc)
        self.assertEqual(normalize_epoch(1_700_000_000), expected)
        self.assertEqual(normalize_epoch(1_700_000_000_000), expected)

    def test_normalize_epoch_rejects_missing_values(self):
        with self.assertRaises(ValueError):
            normalize_epoch(None)

    def test_session_derived_labels(self):
        session = Session(
            id="12345678-abcd",
            first_question="问题",
            cwd="/tmp/work",
            created_at=1_700_000_000.0,
            last_opened_at=1_700_000_100.0,
            rollout_path="/tmp/a.jsonl",
        )
        self.assertEqual(session.short_id, "12345678")
        self.assertEqual(session.directory_name, "work")

    def test_preview_defaults_to_no_error(self):
        preview = Preview("首问", "最近问题", "最近回答")
        self.assertEqual(preview.error, "")

    def test_display_width_handles_chinese_and_combining_marks(self):
        self.assertEqual(display_width("ab中文"), 6)
        self.assertEqual(display_width("e\u0301"), 1)

    def test_clip_display_preserves_column_width(self):
        self.assertEqual(clip_display("ab中文cd", 7), "ab中文…")
        self.assertEqual(clip_display("short", 8), "short")

    def test_clip_display_left_keeps_newest_suffix(self):
        self.assertEqual(clip_display_left("abcdef", 4), "…def")
        self.assertEqual(clip_display_left("你好世界", 5), "…世界")
        self.assertEqual(clip_display_left("short", 8), "short")

    def test_wrap_display_does_not_split_wide_characters(self):
        self.assertEqual(wrap_display("甲乙丙", 4), ["甲乙", "丙"])
        self.assertEqual(wrap_display("", 4), [""])


if __name__ == "__main__":
    unittest.main()

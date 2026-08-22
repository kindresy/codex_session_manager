import curses
import unittest

from codex_session_manager.models import Preview, Session
from codex_session_manager.tui import (
    ViewState,
    _init_palette,
    build_preview_lines,
    calculate_layout,
    format_absolute,
    format_relative,
)


class LayoutTests(unittest.TestCase):
    def test_wide_terminal_uses_split_layout(self):
        layout = calculate_layout(40, 140)
        self.assertEqual(layout.mode, "split")
        self.assertEqual(layout.list_rect[0], 2)
        self.assertEqual(layout.list_rect[2], layout.preview_rect[2])

    def test_narrow_terminal_uses_stacked_layout(self):
        layout = calculate_layout(40, 80)
        self.assertEqual(layout.mode, "stacked")
        self.assertEqual(layout.preview_rect[0], layout.list_rect[0] + layout.list_rect[2])

    def test_tiny_terminal_uses_safe_empty_layout(self):
        layout = calculate_layout(15, 50)
        self.assertEqual(layout.mode, "small")
        self.assertEqual(layout.list_rect, (0, 0, 0, 0))


class ViewStateTests(unittest.TestCase):
    def test_jk_and_arrows_move_with_clamping(self):
        state = ViewState()
        self.assertIsNone(state.handle_key(ord("j"), 3, 0))
        self.assertEqual(state.selected, 1)
        state.handle_key(curses.KEY_DOWN, 3, 0)
        state.handle_key(ord("j"), 3, 0)
        self.assertEqual(state.selected, 2)
        state.handle_key(ord("k"), 3, 0)
        state.handle_key(curses.KEY_UP, 3, 0)
        state.handle_key(ord("k"), 3, 0)
        self.assertEqual(state.selected, 0)

    def test_jump_and_selection_reset_preview_scroll(self):
        state = ViewState(selected=1, preview_offset=8)
        state.handle_key(ord("G"), 5, 20)
        self.assertEqual((state.selected, state.preview_offset), (4, 0))
        state.preview_offset = 6
        state.handle_key(ord("g"), 5, 20)
        self.assertEqual((state.selected, state.preview_offset), (0, 0))

    def test_preview_scrolling_and_actions(self):
        state = ViewState()
        state.handle_key(4, 2, 12)
        self.assertEqual(state.preview_offset, 5)
        state.handle_key(curses.KEY_NPAGE, 2, 12)
        self.assertEqual(state.preview_offset, 10)
        state.handle_key(21, 2, 12)
        self.assertEqual(state.preview_offset, 5)
        self.assertEqual(state.handle_key(ord("r"), 2, 12), "reload")
        self.assertEqual(state.handle_key(10, 2, 12), "select")
        self.assertEqual(state.handle_key(ord("q"), 2, 12), "quit")
        self.assertEqual(state.handle_key(27, 2, 12), "quit")

    def test_ensure_visible_tracks_selected_row(self):
        state = ViewState(selected=8)
        state.ensure_visible(visible_rows=5, count=10)
        self.assertEqual(state.list_offset, 4)
        state.selected = 1
        state.ensure_visible(visible_rows=5, count=10)
        self.assertEqual(state.list_offset, 1)


class FormattingTests(unittest.TestCase):
    def setUp(self):
        self.session = Session(
            "12345678-abcd",
            "第一条问题比较长",
            "/tmp/project",
            1_700_000_000.0,
            1_700_000_100.0,
            "/tmp/rollout.jsonl",
        )

    def test_time_formatting(self):
        self.assertRegex(format_absolute(1_700_000_000.0), r"\d\d-\d\d \d\d:\d\d")
        self.assertEqual(format_relative(1_000.0, now=1_020.0), "刚刚")
        self.assertEqual(format_relative(1_000.0, now=1_300.0), "5分钟前")
        self.assertEqual(format_relative(1_000.0, now=8_200.0), "2小时前")
        self.assertEqual(format_relative(1_000.0, now=173_800.0), "2天前")

    def test_preview_lines_include_metadata_and_recent_messages(self):
        preview = Preview("第一条问题比较长", "最近用户消息", "最近助手回复")
        lines = build_preview_lines(self.session, preview, 20)
        text = "\n".join(line for line, _style in lines)
        self.assertIn("12345678-abcd", text)
        self.assertIn("/tmp/project", text)
        self.assertIn("第一条问题", text)
        self.assertIn("最近用户消息", text)
        self.assertIn("最近助手回复", text)

    def test_monochrome_palette_keeps_selection_visible(self):
        palette = _init_palette(False)
        self.assertNotEqual(palette.selected, 0)
        self.assertTrue(palette.selected & curses.A_REVERSE)


if __name__ == "__main__":
    unittest.main()

import curses
import unittest
from unittest.mock import patch

from codex_session_manager.models import Preview, Session
from codex_session_manager.tui import (
    Palette,
    SearchState,
    ViewState,
    _draw_chrome,
    _event_loop,
    _init_palette,
    _is_backspace,
    build_preview_lines,
    calculate_layout,
    find_session_matches,
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


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.sessions = [
            Session("AbCdEf00-0000", "setup Straße", "/tmp/alpha", 1.0, 2.0, "/tmp/0"),
            Session("11111111-1111", "修复网络问题", "/tmp/beta", 1.0, 2.0, "/tmp/1"),
            Session("22222222-2222", "其他工作", "/srv/Project-X", 1.0, 2.0, "/tmp/2"),
            Session("33333333-3333", "再次修复", "/tmp/delta", 1.0, 2.0, "/tmp/3"),
        ]

    def test_matches_question_full_id_and_directory(self):
        self.assertEqual(find_session_matches(self.sessions, "修复"), (1, 3))
        self.assertEqual(find_session_matches(self.sessions, "ABCDEF"), (0,))
        self.assertEqual(find_session_matches(self.sessions, "project-x"), (2,))
        self.assertEqual(find_session_matches(self.sessions, "STRASSE"), (0,))
        self.assertEqual(find_session_matches(self.sessions, ""), ())

    def test_activate_starts_after_selection_and_wraps(self):
        search = SearchState()

        self.assertEqual(search.activate("修复", self.sessions, 1), 3)
        self.assertEqual(search.matches, (1, 3))
        self.assertEqual(search.activate("修复", self.sessions, 3), 1)

    def test_next_and_previous_wrap_from_matches_or_other_rows(self):
        search = SearchState()
        search.activate("修复", self.sessions, 0)

        self.assertEqual(search.next(1, 1), 3)
        self.assertEqual(search.next(3, 1), 1)
        self.assertEqual(search.next(1, -1), 3)
        self.assertEqual(search.next(3, -1), 1)
        self.assertEqual(search.next(2, 1), 3)
        self.assertEqual(search.next(2, -1), 1)

    def test_no_match_and_clear(self):
        search = SearchState()

        self.assertIsNone(search.activate("不存在", self.sessions, 2))
        self.assertEqual(search.query, "不存在")
        self.assertEqual(search.matches, ())
        self.assertIsNone(search.next(2, 1))
        search.clear()
        self.assertEqual((search.query, search.matches), ("", ()))


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
        self.assertEqual(state.handle_key("/", 2, 12), "search")
        self.assertEqual(state.handle_key("n", 2, 12), "next_match")
        self.assertEqual(state.handle_key("N", 2, 12), "previous_match")

    def test_ensure_visible_tracks_selected_row(self):
        state = ViewState(selected=8)
        state.ensure_visible(visible_rows=5, count=10)
        self.assertEqual(state.list_offset, 4)
        state.selected = 1
        state.ensure_visible(visible_rows=5, count=10)
        self.assertEqual(state.list_offset, 1)

    def test_resume_error_keeps_browser_open_after_enter(self):
        session = Session("12345678-abcd", "问题", "/tmp", 1.0, 2.0, "/tmp/a.jsonl")

        class FakeScreen:
            def __init__(self):
                self.keys = iter((10, ord("q")))

            def keypad(self, _enabled):
                pass

            def getmaxyx(self):
                return (40, 140)

            def erase(self):
                pass

            def noutrefresh(self):
                pass

            def get_wch(self):
                return next(self.keys)

            def derwin(self, *_args):
                return object()

        class Repository:
            def list_sessions(self):
                return [session]

        class Previews:
            def get(self, _session):
                return Preview("问题", "问题", "回答")

        with (
            patch("codex_session_manager.tui.curses.curs_set"),
            patch("codex_session_manager.tui.curses.doupdate"),
            patch("codex_session_manager.tui._init_palette"),
            patch("codex_session_manager.tui._draw_list"),
            patch("codex_session_manager.tui._draw_preview", return_value=0),
            patch("codex_session_manager.tui._draw_chrome") as chrome,
        ):
            selected = _event_loop(
                FakeScreen(), Repository(), Previews(), True, "找不到 codex"
            )

        self.assertIsNone(selected)
        statuses = [call.args[3] for call in chrome.call_args_list]
        self.assertIn("找不到 codex", statuses)


class ChromeTests(unittest.TestCase):
    class FakeScreen:
        def getmaxyx(self):
            return (24, 20)

    def test_search_prompt_keeps_suffix_and_success_is_not_error(self):
        palette = Palette(title=11, time=22, muted=33, error=44)

        with patch("codex_session_manager.tui._safe_addstr") as addstr:
            _draw_chrome(
                self.FakeScreen(), 3, palette, "", "abcdefghijklmnopqrstuvwxyz", False
            )
        footer = addstr.call_args_list[-1].args
        self.assertTrue(footer[3].startswith("…"))
        self.assertTrue(footer[3].endswith("z"))
        self.assertEqual(footer[4], palette.title)

        with patch("codex_session_manager.tui._safe_addstr") as addstr:
            _draw_chrome(self.FakeScreen(), 3, palette, "匹配 1/2：目标", None, False)
        self.assertEqual(addstr.call_args_list[-1].args[4], palette.time)

        with patch("codex_session_manager.tui._safe_addstr") as addstr:
            _draw_chrome(self.FakeScreen(), 3, palette, "未找到：目标", None, True)
        self.assertEqual(addstr.call_args_list[-1].args[4], palette.error)

    def test_backspace_variants(self):
        for key in (curses.KEY_BACKSPACE, 8, 127, "\b", "\x7f"):
            with self.subTest(key=key):
                self.assertTrue(_is_backspace(key))


class SearchEventLoopTests(unittest.TestCase):
    class FakeScreen:
        def __init__(self, keys):
            self.keys = iter(keys)

        def keypad(self, _enabled):
            pass

        def getmaxyx(self):
            return (40, 140)

        def erase(self):
            pass

        def noutrefresh(self):
            pass

        def get_wch(self):
            return next(self.keys)

        def derwin(self, *_args):
            return object()

    class Repository:
        def __init__(self, sessions):
            self.sessions = sessions
            self.calls = 0

        def list_sessions(self):
            self.calls += 1
            return list(self.sessions)

    class Previews:
        def get(self, session):
            return Preview(session.first_question, session.first_question, "回答")

    def setUp(self):
        self.sessions = [
            Session("00000000-0000", "普通会话", "/tmp/alpha", 1.0, 2.0, "/tmp/0"),
            Session("11111111-1111", "目标问题", "/tmp/beta", 1.0, 2.0, "/tmp/1"),
            Session("22222222-2222", "另一个目标", "/tmp/gamma", 1.0, 2.0, "/tmp/2"),
        ]

    def run_loop(self, keys, repository=None, resume_error=""):
        repository = repository or self.Repository(self.sessions)
        with (
            patch("codex_session_manager.tui.curses.curs_set"),
            patch("codex_session_manager.tui.curses.doupdate"),
            patch("codex_session_manager.tui._init_palette"),
            patch("codex_session_manager.tui._draw_list"),
            patch("codex_session_manager.tui._draw_message"),
            patch("codex_session_manager.tui._draw_preview", return_value=0) as preview,
            patch("codex_session_manager.tui._draw_chrome") as chrome,
        ):
            selected = _event_loop(
                self.FakeScreen(keys), repository, self.Previews(), True, resume_error
            )
        return selected, repository, preview, chrome

    def test_unicode_query_selects_matching_session(self):
        selected, _, _, _ = self.run_loop(("/", "目", "标", "\n", "\n"))

        self.assertEqual(selected, "11111111-1111")

    def test_n_jumps_to_next_match(self):
        selected, _, _, _ = self.run_loop(("/", "目", "标", "\n", "n", "\n"))

        self.assertEqual(selected, "22222222-2222")

    def test_upper_n_jumps_to_previous_match(self):
        selected, _, _, _ = self.run_loop(("/", "目", "标", "\n", "N", "\n"))

        self.assertEqual(selected, "22222222-2222")

    def test_backspace_edits_query_and_escape_cancels(self):
        selected, _, _, _ = self.run_loop(
            ("/", "错", "\x7f", "目", "标", "\n", "\n")
        )
        self.assertEqual(selected, "11111111-1111")

        selected, _, preview, _ = self.run_loop(("/", "目", "\x1b", "q"))
        self.assertIsNone(selected)
        previewed_ids = [call.args[1].id for call in preview.call_args_list]
        self.assertEqual(set(previewed_ids), {"00000000-0000"})

    def test_no_match_keeps_selection_and_reports_status(self):
        selected, _, preview, chrome = self.run_loop(("/", "不存在", "\n", "q"))

        self.assertIsNone(selected)
        previewed_ids = [call.args[1].id for call in preview.call_args_list]
        self.assertEqual(set(previewed_ids), {"00000000-0000"})
        statuses = [call.args[3] for call in chrome.call_args_list]
        self.assertIn("未找到：不存在", statuses)

    def test_reload_clears_matches(self):
        repository = self.Repository(self.sessions)
        selected, repository, _, chrome = self.run_loop(
            ("/", "目标", "\n", "r", "n", "q"), repository
        )

        self.assertIsNone(selected)
        self.assertEqual(repository.calls, 2)
        statuses = [call.args[3] for call in chrome.call_args_list]
        self.assertIn("尚未搜索", statuses)

    def test_search_with_empty_session_list_is_safe(self):
        repository = self.Repository([])

        selected, _, preview, chrome = self.run_loop(("/", "目标", "\n", "q"), repository)

        self.assertIsNone(selected)
        preview.assert_not_called()
        statuses = [call.args[3] for call in chrome.call_args_list]
        self.assertIn("未找到：目标", statuses)

    def test_repository_warning_is_displayed_after_initial_load_as_information(self):
        repository = self.Repository(self.sessions)
        repository.warning = "已切换到本地兼容模式"

        selected, _, _, chrome = self.run_loop(("q",), repository)

        self.assertIsNone(selected)
        self.assertEqual(chrome.call_args_list[0].args[3], repository.warning)
        self.assertFalse(chrome.call_args_list[0].args[5])

    def test_refresh_updates_repository_warning(self):
        class WarningRepository(self.Repository):
            def list_sessions(inner_self):
                sessions = super(WarningRepository, inner_self).list_sessions()
                inner_self.warning = (
                    "初始兼容性警告" if inner_self.calls == 1 else "刷新后的兼容性警告"
                )
                return sessions

        selected, _, _, chrome = self.run_loop(
            ("r", "q"), WarningRepository(self.sessions)
        )

        self.assertIsNone(selected)
        statuses = [call.args[3] for call in chrome.call_args_list]
        self.assertEqual(statuses[:2], ["初始兼容性警告", "刷新后的兼容性警告"])
        self.assertFalse(chrome.call_args_list[1].args[5])

    def test_missing_codex_error_takes_priority_over_repository_warning(self):
        repository = self.Repository(self.sessions)
        repository.warning = "已切换到本地兼容模式"

        selected, _, _, chrome = self.run_loop(
            ("q",), repository, "在 PATH 中找不到 codex"
        )

        self.assertIsNone(selected)
        self.assertEqual(chrome.call_args_list[0].args[3], "在 PATH 中找不到 codex")
        self.assertTrue(chrome.call_args_list[0].args[5])


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

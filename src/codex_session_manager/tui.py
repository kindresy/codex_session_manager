"""Responsive curses interface for browsing Codex sessions."""

from __future__ import annotations

import curses
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .models import Preview, Session
from .text import clip_display, display_width, wrap_display


class Repository(Protocol):
    def list_sessions(self) -> list[Session]: ...


class Previews(Protocol):
    def get(self, session: Session) -> Preview: ...


@dataclass(frozen=True, slots=True)
class Layout:
    mode: str
    list_rect: tuple[int, int, int, int]
    preview_rect: tuple[int, int, int, int]


def calculate_layout(rows: int, cols: int) -> Layout:
    if rows < 20 or cols < 60:
        return Layout("small", (0, 0, 0, 0), (0, 0, 0, 0))
    content_y = 2
    content_height = rows - 4
    if cols >= 110:
        list_width = max(64, int(cols * 0.58))
        return Layout(
            "split",
            (content_y, 0, content_height, list_width),
            (content_y, list_width, content_height, cols - list_width),
        )
    list_height = max(8, content_height // 2)
    return Layout(
        "stacked",
        (content_y, 0, list_height, cols),
        (content_y + list_height, 0, content_height - list_height, cols),
    )


def find_session_matches(sessions: list[Session], query: str) -> tuple[int, ...]:
    """Return indices whose loaded metadata contains the query."""
    needle = query.casefold()
    if not needle:
        return ()
    return tuple(
        index
        for index, session in enumerate(sessions)
        if needle in "\n".join((session.id, session.first_question, session.cwd)).casefold()
    )


@dataclass(slots=True)
class SearchState:
    query: str = ""
    matches: tuple[int, ...] = ()

    def activate(self, query: str, sessions: list[Session], selected: int) -> int | None:
        self.query = query
        self.matches = find_session_matches(sessions, query)
        if not self.matches:
            return None
        return next((index for index in self.matches if index > selected), self.matches[0])

    def next(self, selected: int, direction: int) -> int | None:
        if not self.matches:
            return None
        if direction >= 0:
            return next((index for index in self.matches if index > selected), self.matches[0])
        return next(
            (index for index in reversed(self.matches) if index < selected),
            self.matches[-1],
        )

    def clear(self) -> None:
        self.query = ""
        self.matches = ()


@dataclass(slots=True)
class ViewState:
    selected: int = 0
    list_offset: int = 0
    preview_offset: int = 0

    def move(self, delta: int, count: int) -> None:
        before = self.selected
        self.selected = max(0, min(max(count - 1, 0), self.selected + delta))
        if self.selected != before:
            self.preview_offset = 0

    def ensure_visible(self, visible_rows: int, count: int) -> None:
        if count <= 0 or visible_rows <= 0:
            self.list_offset = 0
            return
        self.selected = min(self.selected, count - 1)
        if self.selected < self.list_offset:
            self.list_offset = self.selected
        elif self.selected >= self.list_offset + visible_rows:
            self.list_offset = self.selected - visible_rows + 1
        self.list_offset = max(0, min(self.list_offset, max(0, count - visible_rows)))

    def handle_key(self, key: int | str, count: int, max_preview_offset: int) -> str | None:
        code = ord(key) if isinstance(key, str) and len(key) == 1 else key
        if code in (ord("j"), curses.KEY_DOWN):
            self.move(1, count)
        elif code in (ord("k"), curses.KEY_UP):
            self.move(-1, count)
        elif code == ord("g"):
            self.move(-self.selected, count)
        elif code == ord("G"):
            self.move(max(count - 1, 0) - self.selected, count)
        elif code in (4, curses.KEY_NPAGE):
            self.preview_offset = min(max_preview_offset, self.preview_offset + 5)
        elif code in (21, curses.KEY_PPAGE):
            self.preview_offset = max(0, self.preview_offset - 5)
        elif code == ord("r"):
            return "reload"
        elif code == ord("/"):
            return "search"
        elif code == ord("n"):
            return "next_match"
        elif code == ord("N"):
            return "previous_match"
        elif code in (10, 13, curses.KEY_ENTER):
            return "select" if count else None
        elif code in (ord("q"), 27):
            return "quit"
        return None


@dataclass(frozen=True, slots=True)
class Palette:
    title: int = 0
    selected: int = 0
    time: int = 0
    muted: int = 0
    border: int = 0
    error: int = 0


def format_absolute(timestamp: float) -> str:
    if timestamp <= 0:
        return "--"
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%m-%d %H:%M")


def format_relative(timestamp: float, *, now: float | None = None) -> str:
    if timestamp <= 0:
        return "未知"
    delta = max(0, (time.time() if now is None else now) - timestamp)
    if delta < 60:
        return "刚刚"
    if delta < 3_600:
        return f"{int(delta // 60)}分钟前"
    if delta < 86_400:
        return f"{int(delta // 3_600)}小时前"
    if delta < 30 * 86_400:
        return f"{int(delta // 86_400)}天前"
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%m-%d")


def build_preview_lines(
    session: Session,
    preview: Preview,
    width: int,
) -> list[tuple[str, str]]:
    content_width = max(1, width)
    lines: list[tuple[str, str]] = []

    def section(title: str, content: str, style: str = "normal") -> None:
        if lines:
            lines.append(("", "normal"))
        lines.append((title, "title"))
        for wrapped in wrap_display(content or "（暂无）", content_width):
            lines.append((wrapped, style))

    lines.append((f"UUID  {session.id}", "title"))
    lines.extend((line, "muted") for line in wrap_display(f"目录  {session.cwd or '未知'}", content_width))
    section("第一条问题", preview.first_question)
    section("最近用户消息", preview.latest_user)
    section("最近助手回复", preview.latest_assistant)
    if preview.error:
        section("状态", preview.error, "error")
    return lines


def _pad_display(text: str, width: int) -> str:
    clipped = clip_display(text, width)
    return clipped + " " * max(0, width - display_width(clipped))


def _init_palette(enabled: bool) -> Palette:
    monochrome = Palette(
        title=curses.A_BOLD,
        selected=curses.A_REVERSE | curses.A_BOLD,
        time=curses.A_BOLD,
        muted=curses.A_DIM,
        error=curses.A_BOLD,
    )
    if not enabled or not curses.has_colors():
        return monochrome
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_BLUE, -1)
        curses.init_pair(5, curses.COLOR_WHITE, -1)
        curses.init_pair(6, curses.COLOR_RED, -1)
        return Palette(
            title=curses.color_pair(1) | curses.A_BOLD,
            selected=curses.color_pair(2) | curses.A_BOLD,
            time=curses.color_pair(3),
            muted=curses.color_pair(4),
            border=curses.color_pair(5),
            error=curses.color_pair(6) | curses.A_BOLD,
        )
    except curses.error:
        return monochrome


def _safe_addstr(window, y: int, x: int, text: str, attr: int = 0) -> None:
    try:
        height, width = window.getmaxyx()
        if y < 0 or y >= height or x < 0 or x >= width:
            return
        clipped = clip_display(text, width - x)
        window.addstr(y, x, clipped, attr)
    except curses.error:
        pass


def _draw_border(window, palette: Palette, title: str) -> None:
    try:
        window.attron(palette.border)
        window.border()
        window.attroff(palette.border)
    except curses.error:
        pass
    _safe_addstr(window, 0, 2, f" {title} ", palette.title)


def _draw_list(window, sessions: list[Session], state: ViewState, palette: Palette) -> None:
    window.erase()
    height, width = window.getmaxyx()
    _draw_border(window, palette, f"会话 {len(sessions)}")
    inner_width = max(1, width - 2)
    directory_width = 12
    question_width = max(6, inner_width - 44)
    header = (
        f"{'ID':<8} {_pad_display('FIRST QUESTION', question_width)} "
        f"{'CREATED':<11} {'OPENED':<8} {_pad_display('WORKDIR', directory_width)}"
    )
    _safe_addstr(window, 1, 1, header, palette.muted)
    visible_rows = max(0, height - 3)
    state.ensure_visible(visible_rows, len(sessions))
    for screen_row, index in enumerate(
        range(state.list_offset, min(len(sessions), state.list_offset + visible_rows)),
        start=2,
    ):
        session = sessions[index]
        question = " ".join(session.first_question.split())
        row = (
            f"{session.short_id:<8} {_pad_display(question, question_width)} "
            f"{format_absolute(session.created_at):<11} "
            f"{_pad_display(format_relative(session.last_opened_at), 8)} "
            f"{_pad_display(session.directory_name, directory_width)}"
        )
        attr = palette.selected if index == state.selected else 0
        _safe_addstr(window, screen_row, 1, _pad_display(row, inner_width), attr)
    window.noutrefresh()


def _draw_preview(
    window,
    session: Session,
    preview: Preview,
    state: ViewState,
    palette: Palette,
) -> int:
    window.erase()
    height, width = window.getmaxyx()
    _draw_border(window, palette, "预览")
    lines = build_preview_lines(session, preview, max(1, width - 4))
    visible_rows = max(0, height - 2)
    max_offset = max(0, len(lines) - visible_rows)
    state.preview_offset = min(state.preview_offset, max_offset)
    styles = {
        "title": palette.title,
        "muted": palette.muted,
        "error": palette.error,
        "normal": 0,
    }
    for row, (text, style) in enumerate(
        lines[state.preview_offset : state.preview_offset + visible_rows], start=1
    ):
        _safe_addstr(window, row, 2, text, styles.get(style, 0))
    if max_offset:
        indicator = f" {state.preview_offset + 1}/{len(lines)} "
        _safe_addstr(window, 0, max(1, width - len(indicator) - 2), indicator, palette.muted)
    window.noutrefresh()
    return max_offset


def _draw_chrome(
    stdscr,
    count: int,
    palette: Palette,
    status: str,
    search_prompt: str | None = None,
) -> None:
    rows, cols = stdscr.getmaxyx()
    _safe_addstr(stdscr, 0, 1, "CODEX SESSIONS", palette.title)
    count_label = f"{count} sessions"
    _safe_addstr(stdscr, 0, max(1, cols - len(count_label) - 2), count_label, palette.muted)
    footer = (
        f"/{search_prompt}"
        if search_prompt is not None
        else status
        or "j/k 移动  / 搜索  n/N 匹配  Ctrl-d/u 滚动  r 刷新  Enter 打开  q 退出"
    )
    attr = palette.title if search_prompt is not None else palette.error if status else palette.time
    _safe_addstr(stdscr, rows - 1, 1, footer, attr)


def _draw_message(stdscr, text: str, palette: Palette) -> None:
    rows, cols = stdscr.getmaxyx()
    _safe_addstr(stdscr, rows // 2, max(1, (cols - display_width(text)) // 2), text, palette.title)


def _key_code(key: int | str) -> int | str:
    return ord(key) if isinstance(key, str) and len(key) == 1 else key


def _is_backspace(key: int | str) -> bool:
    return _key_code(key) in (8, 127, curses.KEY_BACKSPACE)


def _match_status(search: SearchState, selected: int) -> str:
    if not search.matches:
        return f"未找到：{search.query}"
    position = search.matches.index(selected) + 1
    return f"匹配 {position}/{len(search.matches)}：{search.query}"


def _event_loop(
    stdscr,
    repository: Repository,
    previews: Previews,
    use_color: bool,
    resume_error: str = "",
) -> str | None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.keypad(True)
    palette = _init_palette(use_color)
    sessions = repository.list_sessions()
    state = ViewState()
    search = SearchState()
    search_input: str | None = None
    status = ""

    while True:
        stdscr.erase()
        rows, cols = stdscr.getmaxyx()
        layout = calculate_layout(rows, cols)
        max_preview_offset = 0
        _draw_chrome(stdscr, len(sessions), palette, status, search_input)

        if layout.mode == "small":
            _draw_message(stdscr, "终端尺寸不足，需要至少 60×20", palette)
        elif not sessions:
            _draw_message(stdscr, "没有找到可恢复的 Codex CLI 会话，按 r 刷新", palette)
        else:
            state.selected = min(state.selected, len(sessions) - 1)
            list_window = stdscr.derwin(*layout.list_rect[2:], *layout.list_rect[:2])
            preview_window = stdscr.derwin(*layout.preview_rect[2:], *layout.preview_rect[:2])
            _draw_list(list_window, sessions, state, palette)
            selected = sessions[state.selected]
            max_preview_offset = _draw_preview(
                preview_window,
                selected,
                previews.get(selected),
                state,
                palette,
            )
        stdscr.noutrefresh()
        curses.doupdate()
        status = ""
        key = stdscr.get_wch()

        if search_input is not None:
            code = _key_code(key)
            if code in (10, 13, curses.KEY_ENTER):
                query = search_input
                search_input = None
                if not query:
                    status = "搜索已取消"
                    continue
                target = search.activate(query, sessions, state.selected)
                if target is None:
                    status = f"未找到：{query}"
                    continue
                state.move(target - state.selected, len(sessions))
                status = _match_status(search, state.selected)
            elif code == 27:
                search_input = None
                status = "已取消搜索"
            elif _is_backspace(key):
                search_input = search_input[:-1]
            elif isinstance(key, str) and key.isprintable():
                search_input += key
            continue

        action = state.handle_key(key, len(sessions), max_preview_offset)
        if action == "quit":
            return None
        if action == "search":
            search_input = ""
            continue
        if action in ("next_match", "previous_match"):
            direction = 1 if action == "next_match" else -1
            target = search.next(state.selected, direction)
            if target is None:
                status = "尚未搜索" if not search.query else f"未找到：{search.query}"
                continue
            state.move(target - state.selected, len(sessions))
            status = _match_status(search, state.selected)
            continue
        if action == "select" and sessions:
            if resume_error:
                status = resume_error
                continue
            return sessions[state.selected].id
        if action == "reload":
            search.clear()
            selected_id = sessions[state.selected].id if sessions else ""
            try:
                sessions = repository.list_sessions()
                state.selected = next(
                    (index for index, item in enumerate(sessions) if item.id == selected_id),
                    min(state.selected, max(len(sessions) - 1, 0)),
                )
                state.list_offset = 0
                state.preview_offset = 0
                status = f"已刷新：{len(sessions)} 个会话"
            except Exception as error:  # curses must stay usable after an I/O failure
                status = f"刷新失败：{error}"


def run_tui(
    repository: Repository,
    previews: Previews,
    *,
    use_color: bool = True,
    resume_error: str = "",
) -> str | None:
    return curses.wrapper(_event_loop, repository, previews, use_color, resume_error)

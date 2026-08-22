"""Command-line entry point and Codex process handoff."""

from __future__ import annotations

import argparse
import curses
import os
import shutil
import sys
from pathlib import Path
from typing import Sequence

from .preview import PreviewService
from .repository import SessionRepository
from .tui import run_tui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-session",
        description="浏览、预览并恢复 Codex CLI 会话",
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        help="Codex 数据目录（默认使用 $CODEX_HOME 或 ~/.codex）",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="禁用彩色界面",
    )
    return parser


def resolve_codex_home(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"


def resume_command(session_id: str) -> None:
    os.execvp("codex", ["codex", "resume", session_id])


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if shutil.which("codex") is None:
        print("错误：在 PATH 中找不到 codex，无法恢复会话。", file=sys.stderr)
        return 2

    repository = SessionRepository(resolve_codex_home(args.codex_home))
    previews = PreviewService()
    try:
        selected_id = run_tui(repository, previews, use_color=not args.no_color)
    except KeyboardInterrupt:
        return 130
    except (OSError, curses.error) as error:
        print(f"错误：无法启动终端界面：{error}", file=sys.stderr)
        return 2

    if selected_id is None:
        return 0
    try:
        resume_command(selected_id)
    except OSError as error:
        print(f"错误：无法启动 codex resume：{error}", file=sys.stderr)
        return 2
    return 0

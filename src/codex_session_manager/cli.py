"""Command-line entry point and Codex process handoff."""

from __future__ import annotations

import argparse
import curses
import os
import shutil
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .app_server import AppServerClient
from .compatibility import (
    CompatibilityState,
    CompatiblePreviewService,
    CompatibleSessionRepository,
)
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
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def resolve_codex_home(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"


def resume_command(session_id: str, codex_path: str, codex_home: Path) -> None:
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    os.execvpe(
        codex_path,
        ["codex", "resume", session_id],
        environment,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    codex_path = shutil.which("codex")
    resume_error = "" if codex_path else "在 PATH 中找不到 codex，当前只能浏览会话"
    codex_home = resolve_codex_home(args.codex_home)

    local_repository = SessionRepository(codex_home)
    local_previews = PreviewService()
    repository = local_repository
    previews = local_previews
    app_server: AppServerClient | None = None
    try:
        if codex_path:
            app_server = AppServerClient(codex_path, codex_home, __version__)
            compatibility = CompatibilityState()
            repository = CompatibleSessionRepository(
                app_server, local_repository, compatibility
            )
            previews = CompatiblePreviewService(
                app_server,
                local_repository,
                local_previews,
                compatibility,
            )
        try:
            tui_options = {"use_color": not args.no_color}
            if resume_error:
                tui_options["resume_error"] = resume_error
            selected_id = run_tui(repository, previews, **tui_options)
        except KeyboardInterrupt:
            return 130
        except (OSError, curses.error) as error:
            print(f"错误：无法启动终端界面：{error}", file=sys.stderr)
            return 2
    finally:
        if app_server is not None:
            app_server.close()

    if selected_id is None:
        return 0
    if not codex_path:
        print(f"错误：{resume_error}", file=sys.stderr)
        return 2
    try:
        resume_command(selected_id, codex_path, codex_home)
    except OSError as error:
        print(f"错误：无法启动 codex resume：{error}", file=sys.stderr)
        return 2
    return 0

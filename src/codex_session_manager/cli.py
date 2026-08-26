"""Command-line entry point and Codex process handoff."""

from __future__ import annotations

import argparse
import curses
import getpass
import os
import shutil
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .app_server import AppServerClient, AppServerError
from .cloud_client import (
    CloudClient,
    CloudError,
    SyncConfig,
    default_config_path,
    load_config,
    save_config,
)
from .cloud_repository import CloudPreviewService, CloudSessionRepository
from .compatibility import (
    CompatibilityState,
    CompatiblePreviewService,
    CompatibleSessionRepository,
)
from .preview import PreviewService
from .repository import SessionRepository
from .sync import SyncResult, sync_sessions
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
    commands = parser.add_subparsers(dest="command")
    sync_parser = commands.add_parser("sync", help="同步 Codex 会话到云端")
    sync_parser.add_argument(
        "--all",
        action="store_true",
        dest="force_all",
        help="上传所有未删除的会话",
    )
    sync_commands = sync_parser.add_subparsers(dest="sync_command")
    sync_commands.add_parser("setup", help="配置云端 Worker 和访问令牌")
    sync_commands.add_parser("status", help="检查云端同步状态")
    commands.add_parser("cloud", help="只读浏览云端会话")
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


def _browse_local(codex_home: Path, no_color: bool) -> int:
    codex_path = shutil.which("codex")
    resume_error = "" if codex_path else "在 PATH 中找不到 codex，当前只能浏览会话"

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
            tui_options = {"use_color": not no_color}
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


def _sync_setup() -> int:
    config_path = default_config_path()
    save_config(
        config_path,
        SyncConfig(input("Worker URL: ").strip(), getpass.getpass("Access token: ")),
    )
    print(f"saved: {config_path}")
    return 0


def _print_sync_result(result: SyncResult) -> int:
    print(f"uploaded: {result.uploaded}")
    print(f"skipped: {result.skipped}")
    print(f"failed: {len(result.failed)}")
    for session_id, message in result.failed:
        print(f"{session_id}: {message}")
    return 1 if result.failed else 0


def _sync_status() -> int:
    cloud = CloudClient(load_config(default_config_path()))
    cloud.health()
    index = cloud.get_index()
    print(f"count: {len(index.get('sessions', []))}")
    print(f"generated_at: {index.get('generated_at')}")
    return 0


def _sync_upload(codex_home: Path, force_all: bool) -> int:
    config = load_config(default_config_path())
    codex_path = shutil.which("codex")
    if not codex_path:
        print("错误：在 PATH 中找不到 codex，无法同步会话", file=sys.stderr)
        return 2

    app_server: AppServerClient | None = None
    try:
        app_server = AppServerClient(codex_path, codex_home, __version__)
        cloud = CloudClient(config)
        return _print_sync_result(
            sync_sessions(app_server, cloud, force_all=force_all)
        )
    finally:
        if app_server is not None:
            app_server.close()


def _run_sync(args: argparse.Namespace, codex_home: Path) -> int:
    try:
        if args.sync_command == "setup":
            return _sync_setup()
        if args.sync_command == "status":
            return _sync_status()
        return _sync_upload(codex_home, args.force_all)
    except (CloudError, AppServerError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2


def _browse_cloud(no_color: bool) -> int:
    try:
        cloud = CloudClient(load_config(default_config_path()))
        run_tui(
            CloudSessionRepository(cloud),
            CloudPreviewService(cloud),
            use_color=not no_color,
            allow_select=False,
            empty_message="云端没有会话，按 r 刷新",
        )
    except KeyboardInterrupt:
        return 130
    except CloudError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    except (OSError, curses.error) as error:
        print(f"错误：无法启动终端界面：{error}", file=sys.stderr)
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "cloud":
        return _browse_cloud(args.no_color)
    codex_home = resolve_codex_home(args.codex_home)
    if args.command == "sync":
        return _run_sync(args, codex_home)
    return _browse_local(codex_home, args.no_color)

"""Helpers for loading committed synthetic Codex storage fixtures."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from codex_session_manager.models import Session
from codex_session_manager.repository import SessionRepository


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_sql_fixture(home: Path, name: str) -> list[Session]:
    database = home / "state_5.sqlite"
    script = (FIXTURES / name).read_text(encoding="utf-8")
    with sqlite3.connect(database) as connection:
        connection.executescript(script)
    return SessionRepository(home).list_sessions()


def copy_rollout_fixture(home: Path, relative_path: str) -> Path:
    source = FIXTURES / relative_path
    destination = home / "sessions" / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return destination


def load_fallback_fixture(home: Path) -> list[Session]:
    database = home / "state_5.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE incompatible (value TEXT)")
    copy_rollout_fixture(
        home,
        "fallback/rollout-2026-08-22T20-05-43-fixture.jsonl",
    )
    return SessionRepository(home).list_sessions()

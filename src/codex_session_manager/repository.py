"""Read-only discovery of Codex CLI sessions."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from .models import Session, normalize_epoch


class RepositoryError(RuntimeError):
    """Raised when a storage source is present but incompatible."""


_INJECTED_BLOCKS = (
    re.compile(
        r"(?:^|\n)# AGENTS\.md instructions[^\n]*\n+"
        r"<INSTRUCTIONS>.*?</INSTRUCTIONS>\s*",
        re.DOTALL,
    ),
    re.compile(
        r"<permissions instructions>.*?</permissions(?: instructions)?>\s*",
        re.DOTALL,
    ),
    re.compile(
        r"<(?P<tag>(?:[a-z][a-z0-9_-]*(?:_instructions|_context)|"
        r"recommended_plugins|claude-mem-context|permissions|"
        r"collaboration_mode|multi_agent_mode))\b[^>]*>.*?</(?P=tag)>\s*",
        re.DOTALL,
    ),
)

_INJECTED_OPENING = re.compile(
    r"<(?:[a-z][a-z0-9_-]*(?:_instructions|_context)|recommended_plugins|"
    r"claude-mem-context|permissions|collaboration_mode|multi_agent_mode)\b"
)


def clean_user_text(text: str) -> str:
    """Return genuine prompt text, excluding known injected context blocks."""
    value = text
    for pattern in _INJECTED_BLOCKS:
        value = pattern.sub("", value)
    if _INJECTED_OPENING.search(value):
        return ""
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    if not value:
        return ""
    if value.startswith("# AGENTS.md instructions"):
        return ""
    return value


def parse_timestamp(value: Any) -> float:
    """Normalize an epoch or ISO-8601 timestamp to Unix seconds."""
    if isinstance(value, (int, float)):
        return normalize_epoch(value).timestamp()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("missing timestamp")
        try:
            return normalize_epoch(float(stripped)).timestamp()
        except ValueError:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            return parsed.timestamp()
    raise ValueError("unsupported timestamp")


def message_texts(payload: dict[str, Any], role: str) -> list[str]:
    """Extract clean text fragments from a Codex response-item message."""
    if payload.get("type") != "message" or payload.get("role") != role:
        return []
    wanted_type = "input_text" if role == "user" else "output_text"
    result: list[str] = []
    for item in payload.get("content", []):
        if not isinstance(item, dict) or item.get("type") != wanted_type:
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        cleaned = clean_user_text(text) if role == "user" else text.strip()
        if cleaned:
            result.append(cleaned)
    return result


class SessionRepository:
    def __init__(self, codex_home: Path):
        self.codex_home = Path(codex_home).expanduser()

    def list_sessions(self) -> list[Session]:
        for database in self._database_candidates():
            try:
                sessions = self._read_database(database)
            except (OSError, sqlite3.Error, RepositoryError, ValueError):
                continue
            if sessions:
                return self._sort(sessions)
        return self._sort(self._scan_rollouts())

    def _database_candidates(self) -> list[Path]:
        try:
            candidates = list(self.codex_home.glob("state_*.sqlite"))
            return sorted(candidates, key=lambda path: path.stat().st_mtime_ns, reverse=True)
        except OSError:
            return []

    def _read_database(self, path: Path) -> list[Session]:
        uri = f"file:{quote(str(path.resolve()))}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='threads'"
            ).fetchone()
            if table is None:
                raise RepositoryError("threads table is missing")
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(threads)").fetchall()
            }
            required = {"id", "rollout_path"}
            if not required.issubset(columns):
                raise RepositoryError("threads table is incompatible")
            rows = connection.execute("SELECT * FROM threads").fetchall()

        sessions: list[Session] = []
        for row in rows:
            if "archived" in columns and bool(row["archived"]):
                continue
            if "source" in columns and row["source"] != "cli":
                continue
            rollout_path = self._resolve_rollout(row["rollout_path"])
            question = ""
            if "first_user_message" in columns and isinstance(row["first_user_message"], str):
                question = clean_user_text(row["first_user_message"])
            if not question:
                question = self._first_question_from_rollout(rollout_path)
            if not question:
                continue

            created = self._creation_timestamp(
                row,
                columns,
                rollout_path,
            )
            recency = self._row_timestamp(
                row,
                columns,
                ("recency_at_ms", "recency_at", "updated_at_ms", "updated_at"),
                rollout_path,
            )
            sessions.append(
                Session(
                    id=str(row["id"]),
                    first_question=question,
                    cwd=str(row["cwd"] or "") if "cwd" in columns else "",
                    created_at=created,
                    last_opened_at=recency,
                    rollout_path=str(rollout_path),
                )
            )
        return sessions

    def _resolve_rollout(self, raw_path: Any) -> Path:
        path = Path(str(raw_path)).expanduser()
        return path if path.is_absolute() else self.codex_home / path

    @staticmethod
    def _row_value_timestamp(
        row: sqlite3.Row,
        columns: set[str],
        candidates: Iterable[str],
    ) -> float | None:
        for name in candidates:
            if name not in columns:
                continue
            value = row[name]
            if value in (None, "", 0):
                continue
            try:
                return parse_timestamp(value)
            except (TypeError, ValueError, OverflowError):
                continue
        return None

    def _creation_timestamp(
        self,
        row: sqlite3.Row,
        columns: set[str],
        rollout_path: Path,
    ) -> float:
        stored = self._row_value_timestamp(
            row,
            columns,
            ("created_at_ms", "created_at"),
        )
        if stored is not None:
            return stored
        metadata = self._session_meta_timestamp(rollout_path)
        return metadata or self._filename_timestamp(rollout_path)

    @classmethod
    def _row_timestamp(
        cls,
        row: sqlite3.Row,
        columns: set[str],
        candidates: Iterable[str],
        rollout_path: Path,
    ) -> float:
        stored = cls._row_value_timestamp(row, columns, candidates)
        if stored is not None:
            return stored
        try:
            return rollout_path.stat().st_mtime
        except OSError:
            return 0.0

    def _session_meta_timestamp(self, path: Path) -> float:
        try:
            for record in self._records(path):
                if record.get("type") != "session_meta":
                    continue
                try:
                    return parse_timestamp(record.get("timestamp"))
                except (TypeError, ValueError, OverflowError):
                    return 0.0
        except OSError:
            return 0.0
        return 0.0

    @staticmethod
    def _filename_timestamp(path: Path) -> float:
        match = re.search(r"rollout-(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-", path.name)
        if match is None:
            return 0.0
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%dT%H-%M-%S").timestamp()
        except ValueError:
            return 0.0

    def _first_question_from_rollout(self, path: Path) -> str:
        try:
            for record in self._records(path):
                if record.get("type") != "response_item":
                    continue
                texts = message_texts(record.get("payload", {}), "user")
                if texts:
                    return "\n\n".join(texts)
        except OSError:
            return ""
        return ""

    def _scan_rollouts(self) -> list[Session]:
        sessions: list[Session] = []
        root = self.codex_home / "sessions"
        try:
            paths = root.glob("**/*.jsonl")
            for path in paths:
                session = self._parse_rollout(path)
                if session is not None:
                    sessions.append(session)
        except OSError:
            return sessions
        return sessions

    def _parse_rollout(self, path: Path) -> Session | None:
        session_id = ""
        cwd = ""
        source: Any = None
        created = 0.0
        question = ""
        try:
            for record in self._records(path):
                if record.get("type") == "session_meta":
                    payload = record.get("payload", {})
                    session_id = str(payload.get("id", ""))
                    cwd = str(payload.get("cwd", ""))
                    source = payload.get("source")
                    try:
                        created = parse_timestamp(record.get("timestamp"))
                    except (TypeError, ValueError, OverflowError):
                        pass
                elif not question and record.get("type") == "response_item":
                    texts = message_texts(record.get("payload", {}), "user")
                    if texts:
                        question = "\n\n".join(texts)
                if session_id and source is not None and question:
                    break
        except OSError:
            return None
        if source != "cli" or not session_id or not question:
            return None
        if not created:
            created = self._filename_timestamp(path)
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = created
        return Session(session_id, question, cwd, created, modified, str(path))

    @staticmethod
    def _records(path: Path) -> Iterable[dict[str, Any]]:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(record, dict):
                    yield record

    @staticmethod
    def _sort(sessions: list[Session]) -> list[Session]:
        return sorted(
            sessions,
            key=lambda item: (item.last_opened_at, item.created_at, item.id),
            reverse=True,
        )

"""Lazy conversation previews for selected Codex sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Preview, Session
from .repository import message_texts


class PreviewService:
    def __init__(self):
        self._cache: dict[str, tuple[int, Preview]] = {}

    def get(self, session: Session) -> Preview:
        path = Path(session.rollout_path)
        try:
            stamp = path.stat().st_mtime_ns
            cache_key = str(path)
            cached = self._cache.get(cache_key)
            if cached is not None and cached[0] == stamp:
                return cached[1]
            preview = self._parse(path, session.first_question)
            self._cache[cache_key] = (stamp, preview)
            return preview
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            return Preview(session.first_question, "", "", "预览不可用")

    def _parse(self, path: Path, first_question: str) -> Preview:
        users: list[str] = []
        assistants: list[str] = []
        saw_message = False
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    record: Any = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict) or record.get("type") != "response_item":
                    continue
                payload = record.get("payload")
                if not isinstance(payload, dict) or payload.get("type") != "message":
                    continue
                saw_message = True
                user_parts = message_texts(payload, "user")
                assistant_parts = message_texts(payload, "assistant")
                if user_parts:
                    users.append("\n\n".join(user_parts))
                if assistant_parts:
                    assistants.append("\n\n".join(assistant_parts))
        if not saw_message:
            raise ValueError("rollout contains no previewable messages")
        return Preview(
            first_question=first_question,
            latest_user=users[-1] if users else "",
            latest_assistant=assistants[-1] if assistants else "",
        )

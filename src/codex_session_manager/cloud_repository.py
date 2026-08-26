"""Adapters that expose cloud sessions through the existing TUI models."""

from __future__ import annotations

from .cloud_client import CloudClient
from .models import Preview, Session


class CloudSessionRepository:
    def __init__(self, cloud: CloudClient):
        self._cloud = cloud

    def list_sessions(self) -> list[Session]:
        return [
            Session(
                entry["id"],
                entry["question"],
                entry["cwd"],
                entry["created_at"],
                entry["updated_at"],
                "",
            )
            for entry in self._cloud.get_index().get("sessions", [])
        ]


class CloudPreviewService:
    def __init__(self, cloud: CloudClient):
        self._cloud = cloud
        self._cache: dict[tuple[str, float], Preview] = {}

    def get(self, session: Session) -> Preview:
        key = (session.id, session.last_opened_at)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        latest_user = ""
        latest_assistant = ""
        payload = self._cloud.get_session(session.id)
        for turn in payload.get("turns", []):
            for item in turn.get("items", []):
                if item.get("type") == "user" and isinstance(item.get("text"), str):
                    latest_user = item["text"]
                elif item.get("type") == "assistant" and isinstance(item.get("text"), str):
                    latest_assistant = item["text"]

        preview = Preview(session.first_question, latest_user, latest_assistant)
        self._cache[key] = preview
        return preview

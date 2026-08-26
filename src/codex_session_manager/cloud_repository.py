"""Adapters that expose cloud sessions through the existing TUI models."""

from __future__ import annotations

from typing import Any

from .cloud_client import CloudClient, CloudError
from .models import Preview, Session


def _validate_metadata(value: Any, message: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(
        not isinstance(value.get(field), str) for field in ("id", "question", "cwd")
    ):
        raise CloudError(message)
    if any(
        isinstance(value.get(field), bool)
        or not isinstance(value.get(field), (int, float))
        for field in ("created_at", "updated_at")
    ):
        raise CloudError(message)
    return value


class CloudSessionRepository:
    def __init__(self, cloud: CloudClient):
        self._cloud = cloud

    def list_sessions(self) -> list[Session]:
        payload = self._cloud.get_index()
        sessions = payload.get("sessions") if isinstance(payload, dict) else None
        if not isinstance(sessions, list):
            raise CloudError("Cloud session index is invalid.")
        result: list[Session] = []
        for value in sessions:
            entry = _validate_metadata(value, "Cloud session index is invalid.")
            result.append(
                Session(
                    entry["id"],
                    entry["question"],
                    entry["cwd"],
                    entry["created_at"],
                    entry["updated_at"],
                    "",
                )
            )
        return result


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
        payload = _validate_metadata(
            self._cloud.get_session(session.id), "Cloud session data is invalid."
        )
        turns = payload.get("turns")
        if not isinstance(turns, list):
            raise CloudError("Cloud session data is invalid.")
        for turn in turns:
            if not isinstance(turn, dict) or not isinstance(turn.get("items"), list):
                raise CloudError("Cloud session data is invalid.")
            for item in turn["items"]:
                if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                    raise CloudError("Cloud session data is invalid.")
                item_type = item["type"]
                if item_type not in ("user", "assistant"):
                    continue
                text = item.get("text")
                if not isinstance(text, str):
                    raise CloudError("Cloud session data is invalid.")
                if item_type == "user":
                    latest_user = text
                else:
                    latest_assistant = text

        preview = Preview(session.first_question, latest_user, latest_assistant)
        self._cache[key] = preview
        return preview

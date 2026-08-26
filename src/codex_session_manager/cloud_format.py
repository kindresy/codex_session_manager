"""Normalize Codex App Server threads for cloud storage."""

from __future__ import annotations

from typing import Any

from .models import Session
from .repository import clean_user_text


def normalize_cloud_session(session: Session, response: Any) -> dict[str, Any]:
    """Return a versioned cloud-safe representation of a thread/read result."""
    if not isinstance(response, dict):
        raise ValueError("invalid thread/read response")
    thread = response.get("thread")
    if not isinstance(thread, dict):
        raise ValueError("invalid thread/read thread")
    turns = thread.get("turns")
    if not isinstance(turns, list):
        raise ValueError("invalid thread/read turns")

    return {
        "schema_version": 1,
        "id": session.id,
        "question": session.first_question,
        "created_at": session.created_at,
        "updated_at": session.content_updated_at,
        "cwd": session.cwd,
        "turns": [{"items": _normalize_turn(turn)} for turn in turns],
    }


def _normalize_turn(turn: Any) -> list[dict[str, Any]]:
    if not isinstance(turn, dict) or not isinstance(turn.get("items"), list):
        raise ValueError("invalid thread turn")
    result: list[dict[str, Any]] = []
    for item in turn["items"]:
        normalized = _normalize_item(item)
        if normalized is not None:
            result.extend(normalized)
    return result


def _normalize_item(item: Any) -> list[dict[str, Any]] | None:
    if not isinstance(item, dict):
        raise ValueError("invalid thread item")
    item_type = item.get("type")
    if not isinstance(item_type, str) or not item_type:
        raise ValueError("invalid thread item type")
    if item_type == "userMessage":
        return _user_message(item)
    if item_type == "agentMessage":
        return _agent_message(item)
    if item_type == "commandExecution":
        return _command_execution(item)
    if item_type == "fileChange":
        return _file_changes(item)
    return None


def _user_message(item: dict[str, Any]) -> list[dict[str, Any]] | None:
    content = item.get("content")
    if not isinstance(content, list):
        raise ValueError("invalid user message content")
    parts: list[str] = []
    for entry in content:
        if not isinstance(entry, dict) or not isinstance(entry.get("type"), str):
            raise ValueError("invalid user message content entry")
        if entry["type"] != "text":
            continue
        text = entry.get("text")
        if not isinstance(text, str):
            raise ValueError("invalid user message text")
        cleaned = clean_user_text(text)
        if cleaned:
            parts.append(cleaned)
    if not parts:
        return None
    return [{"type": "user", "text": "\n\n".join(parts)}]


def _agent_message(item: dict[str, Any]) -> list[dict[str, Any]] | None:
    text = item.get("text")
    if not isinstance(text, str):
        raise ValueError("invalid agent message text")
    if not (text := text.strip()):
        return None
    return [{"type": "assistant", "text": text}]


def _command_execution(item: dict[str, Any]) -> list[dict[str, Any]] | None:
    command = item.get("command")
    cwd = item.get("cwd")
    status = item.get("status")
    output = item.get("aggregatedOutput")
    exit_code = item.get("exitCode")
    if output is None:
        output = ""
    if (
        not isinstance(command, str)
        or not isinstance(cwd, str)
        or not isinstance(status, str)
        or not isinstance(output, str)
        or (exit_code is not None and type(exit_code) is not int)
    ):
        raise ValueError("invalid command execution")
    return [
        {
            "type": "command",
            "command": command,
            "cwd": cwd,
            "status": status,
            "output": output,
            "exit_code": exit_code,
        }
    ]


def _file_changes(item: dict[str, Any]) -> list[dict[str, Any]] | None:
    changes = item.get("changes")
    if not isinstance(changes, list):
        raise ValueError("invalid file changes")
    result: list[dict[str, Any]] = []
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("invalid file change")
        path = change.get("path")
        kind = change.get("kind")
        diff = change.get("diff")
        if not isinstance(path, str) or not isinstance(kind, str) or not isinstance(diff, str):
            raise ValueError("invalid file change")
        result.append({"type": "file_change", "path": path, "kind": kind, "diff": diff})
    return result or None

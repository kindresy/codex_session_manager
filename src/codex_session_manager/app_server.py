"""Read Codex sessions through the App Server JSON-RPC protocol."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .models import Preview, Session, normalize_epoch
from .repository import clean_user_text


class AppServerError(RuntimeError):
    """Raised when an App Server response or transport is incompatible."""


def _object(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppServerError(f"invalid {description}")
    return value


def _string(value: Any, description: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise AppServerError(f"invalid {description}")
    return value


def _timestamp(value: Any, description: str) -> float:
    try:
        return normalize_epoch(value).timestamp()
    except (OSError, OverflowError, TypeError, ValueError) as error:
        raise AppServerError(f"invalid {description}") from error


def _message_texts(turns: Any) -> tuple[list[str], list[str]]:
    if not isinstance(turns, list):
        raise AppServerError("invalid thread turns")
    users: list[str] = []
    assistants: list[str] = []
    for turn in turns:
        payload = _object(turn, "thread turn")
        items = payload.get("items")
        if not isinstance(items, list):
            raise AppServerError("invalid thread turn items")
        for item in items:
            payload = _object(item, "thread item")
            if payload.get("type") == "userMessage":
                content = payload.get("content")
                if not isinstance(content, list):
                    raise AppServerError("invalid user message content")
                parts: list[str] = []
                for entry in content:
                    payload = _object(entry, "user message content entry")
                    item_type = _string(payload.get("type"), "user message content type")
                    if item_type != "text":
                        continue
                    text = _string(payload.get("text"), "user message text", allow_empty=True)
                    cleaned = clean_user_text(text)
                    if cleaned:
                        parts.append(cleaned)
                if parts:
                    users.append("\n\n".join(parts))
            elif payload.get("type") == "agentMessage":
                text = payload.get("text")
                if not isinstance(text, str):
                    raise AppServerError("invalid agent message text")
                cleaned = text.strip()
                if cleaned:
                    assistants.append(cleaned)
    return users, assistants


def parse_thread(value: Any) -> Session:
    """Convert a ``thread/list`` thread object into the shared session model."""
    thread = _object(value, "thread")
    session_id = _string(thread.get("id"), "thread id")
    cwd = _string(thread.get("cwd"), "thread cwd", allow_empty=True)
    created_at = _timestamp(thread.get("createdAt"), "thread creation time")
    recency_value = thread.get("recencyAt")
    last_opened_at = _timestamp(
        thread.get("updatedAt") if recency_value is None else recency_value,
        "thread recency time",
    )
    path = thread.get("path")
    if path is not None and not isinstance(path, str):
        raise AppServerError("invalid thread path")

    preview = thread.get("preview", "")
    if not isinstance(preview, str):
        raise AppServerError("invalid thread preview")
    first_question = clean_user_text(preview)
    if not first_question:
        users, _ = _message_texts(thread.get("turns"))
        if not users:
            raise AppServerError("thread has no user message")
        first_question = users[0]

    return Session(
        id=session_id,
        first_question=first_question,
        cwd=cwd,
        created_at=created_at,
        last_opened_at=last_opened_at,
        rollout_path=path or "",
    )


def parse_preview(value: Any) -> Preview:
    """Convert a ``thread/read`` result into a lazy conversation preview."""
    response = _object(value, "thread/read response")
    thread = _object(response.get("thread"), "thread/read thread")
    users, assistants = _message_texts(thread.get("turns"))
    if not users and not assistants:
        raise AppServerError("thread has no previewable messages")
    return Preview(
        first_question=users[0] if users else "",
        latest_user=users[-1] if users else "",
        latest_assistant=assistants[-1] if assistants else "",
    )


class AppServerClient:
    """A synchronous, read-only client for one Codex App Server process."""

    def __init__(
        self,
        codex_path: str | Path,
        codex_home: str | Path,
        version: str,
        timeout: float = 5.0,
    ):
        self.codex_path = str(codex_path)
        self.codex_home = Path(codex_home).expanduser()
        self.version = version
        self.timeout = timeout
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[dict[str, Any] | AppServerError] = queue.Queue()
        self._request_lock = threading.RLock()
        self._next_id = 1
        self._timed_out_ids: set[int] = set()
        self._closed = False
        self._reader: threading.Thread | None = None

    def list_sessions(self) -> list[Session]:
        """Return all non-archived Codex CLI threads, ordered by recency."""
        sessions: list[Session] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {
                "sourceKinds": ["cli"],
                "archived": False,
                "sortKey": "recency_at",
                "sortDirection": "desc",
            }
            if cursor is not None:
                params["cursor"] = cursor
            result = self._request("thread/list", params)
            response = _object(result, "thread/list response")
            data = response.get("data")
            if not isinstance(data, list):
                raise AppServerError("invalid thread/list data")
            sessions.extend(parse_thread(item) for item in data)
            next_cursor = response.get("nextCursor")
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise AppServerError("invalid thread/list cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return sorted(
            sessions,
            key=lambda item: (item.last_opened_at, item.created_at, item.id),
            reverse=True,
        )

    def get_preview(self, session: Session) -> Preview:
        """Read the latest user and agent messages for a selected session."""
        result = self._request(
            "thread/read", {"threadId": session.id, "includeTurns": True}
        )
        parsed = parse_preview(result)
        return Preview(
            first_question=session.first_question or parsed.first_question,
            latest_user=parsed.latest_user,
            latest_assistant=parsed.latest_assistant,
        )

    def close(self) -> None:
        """Stop the child process; this operation may be safely repeated."""
        with self._request_lock:
            if self._closed:
                return
            self._closed = True
            process = self._process
            if process is None:
                return
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if self._reader is not None:
                self._reader.join(timeout=self.timeout)
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError:
                    pass

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        with self._request_lock:
            self._ensure_started()
            return self._send_request(method, params)

    def _ensure_started(self) -> None:
        if self._closed:
            raise AppServerError("App Server client is closed")
        if self._process is not None:
            return
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(self.codex_home)
        try:
            self._process = subprocess.Popen(
                [self.codex_path, "app-server"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=environment,
            )
        except OSError as error:
            raise AppServerError("could not start Codex App Server") from error
        self._reader = threading.Thread(target=self._read_responses, daemon=True)
        self._reader.start()
        try:
            self._send_request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "codex-session-manager",
                        "version": self.version,
                    },
                    "capabilities": {"experimentalApi": False},
                },
            )
            self._send_notification("initialized")
        except AppServerError:
            self.close()
            raise

    def _send_notification(self, method: str) -> None:
        self._write({"jsonrpc": "2.0", "method": method})

    def _send_request(self, method: str, params: dict[str, Any]) -> Any:
        request_id = self._next_id
        self._next_id += 1
        self._write(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._timed_out_ids.add(request_id)
                raise AppServerError(f"App Server request timed out: {method}")
            try:
                response = self._responses.get(timeout=remaining)
            except queue.Empty as error:
                process = self._process
                if process is not None and process.poll() is not None:
                    raise AppServerError("Codex App Server exited") from error
                self._timed_out_ids.add(request_id)
                raise AppServerError(f"App Server request timed out: {method}") from error
            if isinstance(response, AppServerError):
                raise response
            response_id = response.get("id")
            if type(response_id) is not int:
                raise AppServerError("invalid App Server response id")
            if response_id in self._timed_out_ids:
                self._timed_out_ids.remove(response_id)
                continue
            if response_id != request_id:
                raise AppServerError("unexpected App Server response id")
            has_result = "result" in response
            has_error = "error" in response
            if has_result == has_error:
                raise AppServerError("invalid App Server response envelope")
            if has_result:
                result = response["result"]
                if not isinstance(result, dict):
                    raise AppServerError("invalid App Server result")
                return result
            error = response["error"]
            if not isinstance(error, dict):
                raise AppServerError("invalid App Server error")
            code = error.get("code")
            message = error.get("message")
            if type(code) is not int or not isinstance(message, str):
                raise AppServerError("invalid App Server error")
            raise AppServerError(message)

    def _write(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise AppServerError("Codex App Server is not running")
        try:
            process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            raise AppServerError("could not write to Codex App Server") from error

    def _read_responses(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            self._responses.put(AppServerError("Codex App Server output is unavailable"))
            return
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as error:
                    self._responses.put(AppServerError("malformed App Server JSON"))
                    return
                if not isinstance(message, dict):
                    self._responses.put(AppServerError("malformed App Server response"))
                    return
                if "method" in message and "id" not in message:
                    continue
                self._responses.put(message)
        except (OSError, UnicodeError) as error:
            self._responses.put(AppServerError("could not read Codex App Server output"))
            return
        self._responses.put(AppServerError("Codex App Server closed its output"))

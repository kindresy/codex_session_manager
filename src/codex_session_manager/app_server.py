"""Read Codex sessions through the App Server JSON-RPC protocol."""

from __future__ import annotations

import json
import os
import queue
import selectors
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from .models import Preview, Session, normalize_epoch
from .repository import clean_user_text


class AppServerError(RuntimeError):
    """Raised when an App Server response or transport is incompatible."""


@dataclass(frozen=True)
class _QueuedResponse:
    message: dict[str, Any]
    arrived_at: float


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
        self._responses: queue.Queue[_QueuedResponse | AppServerError] = queue.Queue()
        self._request_lock = threading.RLock()
        self._next_id = 1
        self._timed_out_ids: set[int] = set()
        self._closed = False
        self._reader: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._terminal_error: str | None = None
        self._cleanup_lock = threading.Lock()
        self._cleanup_started = False
        self._reaper: threading.Thread | None = None

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
            with self._state_lock:
                self._closed = True
            process = self._process
            if process is None:
                return
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
            if self._claim_cleanup():
                self._shutdown_bounded(process)
            reader = self._reader
            if reader is not None and reader is not threading.current_thread():
                reader.join(timeout=max(0.0, self.timeout))
            if reader is not None and reader.is_alive():
                self._start_stream_cleanup(process)
            else:
                self._close_stdout(process)

    def _claim_cleanup(self) -> bool:
        with self._cleanup_lock:
            if self._cleanup_started:
                return False
            self._cleanup_started = True
            return True

    def _wait_bounded(self, process: subprocess.Popen[str]) -> bool:
        try:
            process.wait(timeout=max(0.0, self.timeout))
            return True
        except subprocess.TimeoutExpired:
            return False
        except OSError:
            return True

    @staticmethod
    def _signal_process(process: subprocess.Popen[str], method: str) -> None:
        try:
            getattr(process, method)()
        except OSError:
            pass

    def _shutdown_bounded(self, process: subprocess.Popen[str]) -> None:
        try:
            running = process.poll() is None
        except OSError:
            running = False
        if running:
            self._signal_process(process, "terminate")
        if self._wait_bounded(process):
            return
        self._signal_process(process, "kill")
        if not self._wait_bounded(process):
            self._start_late_cleanup(process)

    def _start_terminal_cleanup(self) -> None:
        process = self._process
        if process is None or not self._claim_cleanup():
            return
        reaper = threading.Thread(
            target=self._background_shutdown,
            args=(process,),
            daemon=True,
        )
        with self._cleanup_lock:
            self._reaper = reaper
        reaper.start()

    def _background_shutdown(self, process: subprocess.Popen[str]) -> None:
        try:
            try:
                running = process.poll() is None
            except OSError:
                running = False
            if running:
                self._signal_process(process, "terminate")
            if not self._wait_bounded(process):
                self._signal_process(process, "kill")
                try:
                    process.wait()
                except OSError:
                    pass
        finally:
            self._finish_stream_cleanup(process)

    def _start_late_cleanup(self, process: subprocess.Popen[str]) -> None:
        reaper = threading.Thread(
            target=self._late_cleanup,
            args=(process,),
            daemon=True,
        )
        with self._cleanup_lock:
            self._reaper = reaper
        reaper.start()

    def _start_stream_cleanup(self, process: subprocess.Popen[str]) -> None:
        with self._cleanup_lock:
            if self._reaper is not None and self._reaper.is_alive():
                return
            reaper = threading.Thread(
                target=self._finish_stream_cleanup,
                args=(process,),
                daemon=True,
            )
            self._reaper = reaper
        reaper.start()

    def _late_cleanup(self, process: subprocess.Popen[str]) -> None:
        try:
            process.wait()
        except OSError:
            pass
        self._finish_stream_cleanup(process)

    def _finish_stream_cleanup(self, process: subprocess.Popen[str]) -> None:
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join()
        self._close_stdout(process)

    @staticmethod
    def _close_stdout(process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        try:
            process.stdout.close()
        except (OSError, ValueError):
            pass

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        with self._request_lock:
            self._raise_terminal_error()
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
            if self._process.stdin is None:
                raise OSError("App Server input is unavailable")
            os.set_blocking(self._process.stdin.fileno(), False)
        except OSError as error:
            if self._process is not None:
                self.close()
            raise AppServerError("could not start Codex App Server") from error
        self._reader = threading.Thread(target=self._read_responses, daemon=True)
        self._reader.start()
        deadline = time.monotonic() + self.timeout
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
                deadline=deadline,
            )
            self._send_notification("initialized", deadline=deadline)
        except AppServerError:
            self.close()
            raise

    def _send_notification(self, method: str, *, deadline: float | None = None) -> None:
        if deadline is None:
            deadline = time.monotonic() + self.timeout
        self._write(
            {"jsonrpc": "2.0", "method": method},
            deadline,
            f"App Server request timed out: {method}",
        )

    def _send_request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        deadline: float | None = None,
    ) -> Any:
        if deadline is None:
            deadline = time.monotonic() + self.timeout
        request_id = self._next_id
        self._next_id += 1
        self._write(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            deadline,
            f"App Server request timed out: {method}",
        )
        while True:
            remaining = deadline - time.monotonic()
            try:
                queued = self._responses.get(timeout=max(0.0, remaining))
            except queue.Empty as error:
                process = self._process
                if process is not None and process.poll() is not None:
                    raise AppServerError("Codex App Server exited") from error
                self._timed_out_ids.add(request_id)
                raise AppServerError(f"App Server request timed out: {method}") from error
            if isinstance(queued, AppServerError):
                raise queued
            response = queued.message
            response_id = response.get("id")
            if type(response_id) is not int:
                raise AppServerError("invalid App Server response id")
            if response_id in self._timed_out_ids:
                self._timed_out_ids.remove(response_id)
                continue
            if response_id != request_id:
                raise AppServerError("unexpected App Server response id")
            if queued.arrived_at > deadline:
                raise AppServerError(f"App Server request timed out: {method}")
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

    def _write(
        self,
        message: dict[str, Any],
        deadline: float,
        timeout_message: str,
    ) -> None:
        self._raise_terminal_error()
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            self._fail_transport("Codex App Server is not running")
        selector: selectors.BaseSelector | None = None
        try:
            try:
                payload = (json.dumps(message, ensure_ascii=False) + "\n").encode(
                    "utf-8"
                )
                descriptor = process.stdin.fileno()
                selector = selectors.DefaultSelector()
                selector.register(descriptor, selectors.EVENT_WRITE)
            except (OSError, UnicodeError, ValueError) as error:
                self._fail_transport("could not write to Codex App Server", error)

            remaining_payload = memoryview(payload)
            while remaining_payload:
                self._raise_terminal_error()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._fail_transport(timeout_message)
                try:
                    written = os.write(descriptor, remaining_payload)
                except InterruptedError:
                    continue
                except BlockingIOError:
                    try:
                        ready = selector.select(remaining)
                    except OSError as error:
                        self._fail_transport("could not write to Codex App Server", error)
                    if not ready:
                        self._fail_transport(timeout_message)
                    continue
                except (BrokenPipeError, OSError, ValueError) as error:
                    self._fail_transport("could not write to Codex App Server", error)
                if written <= 0:
                    self._fail_transport("could not write to Codex App Server")
                remaining_payload = remaining_payload[written:]
        finally:
            if selector is not None:
                selector.close()

    def _raise_terminal_error(self) -> None:
        with self._state_lock:
            message = self._terminal_error
        if message is not None:
            raise AppServerError(message)

    def _fail_transport(
        self, message: str, cause: BaseException | None = None
    ) -> NoReturn:
        latched = self._latch_terminal_error(message)
        if cause is None:
            raise AppServerError(latched)
        raise AppServerError(latched) from cause

    def _latch_terminal_error(self, message: str) -> str:
        publish = False
        with self._state_lock:
            if self._closed:
                return message
            if self._terminal_error is None:
                self._terminal_error = message
                publish = True
            latched = self._terminal_error
        if publish:
            self._responses.put(AppServerError(latched))
            self._start_terminal_cleanup()
        return latched

    def _read_responses(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            self._latch_terminal_error("Codex App Server output is unavailable")
            return
        try:
            for line in process.stdout:
                arrived_at = time.monotonic()
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as error:
                    self._latch_terminal_error("malformed App Server JSON")
                    return
                if not isinstance(message, dict):
                    self._latch_terminal_error("malformed App Server response")
                    return
                if "method" in message and "id" not in message:
                    continue
                self._responses.put(_QueuedResponse(message, arrived_at))
        except (OSError, UnicodeError) as error:
            self._latch_terminal_error("could not read Codex App Server output")
            return
        self._latch_terminal_error("Codex App Server closed its output")

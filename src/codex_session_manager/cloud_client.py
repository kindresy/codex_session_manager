"""Configuration and HTTP client for the cloud session service."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class CloudError(RuntimeError):
    """A user-facing cloud configuration or service error."""


@dataclass(frozen=True)
class SyncConfig:
    worker_url: str
    token: str


def default_config_path() -> Path:
    return Path.home() / ".config" / "codex-session" / "sync.json"


def load_config(path: str | Path) -> SyncConfig:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CloudError("Cloud sync is not configured; run codex-session sync setup.") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CloudError("Cloud sync configuration is invalid.") from error
    return _config_from_value(value)


def save_config(path: str | Path, config: SyncConfig) -> None:
    path = Path(path)
    _config_from_value({"worker_url": config.worker_url, "token": config.token})
    temporary_name: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_name = temporary.name
            json.dump({"worker_url": config.worker_url, "token": config.token}, temporary, ensure_ascii=False)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except (OSError, UnicodeError) as error:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise CloudError("Could not save cloud sync configuration.") from error


class CloudClient:
    def __init__(self, config: SyncConfig):
        config = _config_from_value({"worker_url": config.worker_url, "token": config.token})
        try:
            parsed = urlparse(config.worker_url)
        except (UnicodeError, ValueError) as error:
            raise CloudError("Cloud worker URL is invalid.") from error
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or "?" in config.worker_url or "#" in config.worker_url:
            raise CloudError("Cloud worker URL is invalid.")
        self._worker_url = config.worker_url.rstrip("/")
        self._token = config.token

    def get_index(self) -> dict[str, Any]:
        return self._versioned(self._request("GET", "/api/sessions"))

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._versioned(self._request("GET", self._session_path(session_id)))

    def put_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_version(payload)
        session_id = payload.get("id")
        if not isinstance(session_id, str) or not session_id:
            raise CloudError("Cloud session payload is invalid.")
        return self._versioned(self._request("PUT", self._session_path(session_id), payload))

    def put_index(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_version(payload)
        return self._versioned(self._request("PUT", "/api/index", payload))

    def delete_session(self, session_id: str) -> dict[str, Any]:
        return self._versioned(self._request("DELETE", self._session_path(session_id)))

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def _session_path(self, session_id: str) -> str:
        if not isinstance(session_id, str) or not session_id:
            raise CloudError("Cloud session ID is invalid.")
        try:
            return "/api/sessions/" + quote(session_id, safe="")
        except UnicodeError as error:
            raise CloudError("Cloud session ID is invalid.") from error

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else _encode_json(payload)
        headers = {"Authorization": f"Bearer {self._token}"}
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        try:
            request = Request(self._worker_url + path, data=data, headers=headers, method=method)
            with build_opener(_NoRedirect()).open(request) as response:
                return _decode_json(response.read())
        except HTTPError as error:
            if error.code == 401:
                raise CloudError("Cloud authentication failed; update your sync token.") from error
            raise CloudError(f"Cloud request failed (HTTP {error.code}).") from error
        except URLError as error:
            raise CloudError(f"Could not reach cloud service: {error.reason}") from error
        except (UnicodeError, ValueError) as error:
            raise CloudError("Cloud request is invalid.") from error

    def _versioned(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_version(payload)
        return payload

    @staticmethod
    def _validate_version(payload: Any) -> None:
        if not isinstance(payload, dict):
            raise CloudError("Cloud service returned invalid JSON.")
        if payload.get("schema_version") != 1:
            raise CloudError("Cloud data uses an unsupported schema; upgrade Codex Session Manager.")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _config_from_value(value: Any) -> SyncConfig:
    if not isinstance(value, dict):
        raise CloudError("Cloud sync configuration is invalid.")
    worker_url = value.get("worker_url")
    token = value.get("token")
    if not isinstance(worker_url, str) or not worker_url or not isinstance(token, str) or not token:
        raise CloudError("Cloud sync configuration is invalid.")
    return SyncConfig(worker_url, token)


def _encode_json(payload: dict[str, Any]) -> bytes:
    try:
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CloudError("Cloud payload is invalid.") from error


def _decode_json(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CloudError("Cloud service returned invalid JSON.") from error
    if not isinstance(value, dict):
        raise CloudError("Cloud service returned invalid JSON.")
    return value

"""Incrementally synchronize Codex sessions to cloud storage."""

from __future__ import annotations

from dataclasses import dataclass
import time

from .app_server import AppServerClient
from .cloud_client import CloudClient
from .cloud_format import normalize_cloud_session


@dataclass(frozen=True, slots=True)
class SyncResult:
    uploaded: int
    skipped: int
    failed: tuple[tuple[str, str], ...]


def sync_sessions(
    app_server: AppServerClient,
    cloud: CloudClient,
    force_all: bool = False,
) -> SyncResult:
    """Upload new or changed sessions and then replace the remote index."""
    remote_index = cloud.get_index()
    deleted_ids = set(remote_index.get("deleted_ids", []))
    indexed = {
        entry["id"]: entry
        for entry in remote_index.get("sessions", [])
        if entry["id"] not in deleted_ids
    }
    uploaded = 0
    skipped = 0
    failed: list[tuple[str, str]] = []

    for session in app_server.list_sessions():
        remote = indexed.get(session.id)
        if session.id in deleted_ids or (
            not force_all
            and remote is not None
            and session.content_updated_at <= remote["updated_at"]
        ):
            skipped += 1
            continue

        try:
            payload = normalize_cloud_session(
                session, app_server.read_thread(session.id)
            )
            cloud.put_session(payload)
        except Exception as error:
            failed.append((session.id, str(error) or type(error).__name__))
            continue

        indexed[session.id] = {
            key: payload[key]
            for key in ("id", "question", "created_at", "updated_at", "cwd")
        }
        uploaded += 1

    cloud.put_index(
        {
            "schema_version": 1,
            "generated_at": time.time(),
            "sessions": sorted(
                indexed.values(), key=lambda entry: entry["updated_at"], reverse=True
            ),
            "deleted_ids": remote_index.get("deleted_ids", []),
        }
    )
    return SyncResult(uploaded, skipped, tuple(failed))

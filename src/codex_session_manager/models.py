"""Normalized data models shared across storage and UI layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def normalize_epoch(value: int | float | str | None) -> datetime:
    """Convert Unix seconds or milliseconds to an aware UTC datetime."""
    if value is None or value == "":
        raise ValueError("missing timestamp")
    timestamp = float(value)
    if abs(timestamp) > 10_000_000_000:
        timestamp /= 1000.0
    return datetime.fromtimestamp(timestamp, timezone.utc)


@dataclass(frozen=True, slots=True)
class Session:
    id: str
    first_question: str
    cwd: str
    created_at: float
    last_opened_at: float
    rollout_path: str

    @property
    def short_id(self) -> str:
        return self.id[:8]

    @property
    def directory_name(self) -> str:
        return Path(self.cwd).name or self.cwd


@dataclass(frozen=True, slots=True)
class Preview:
    first_question: str
    latest_user: str
    latest_assistant: str
    error: str = ""


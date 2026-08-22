"""Fallback adapters for App Server-backed session access."""

from __future__ import annotations

from .app_server import AppServerError
from .models import Preview, Session


class CompatibleSessionRepository:
    """Prefer App Server sessions while retaining local-storage compatibility."""

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback
        self.warning = ""

    def list_sessions(self) -> list[Session]:
        try:
            sessions = self.primary.list_sessions()
        except AppServerError:
            sessions = self.fallback.list_sessions()
            self.warning = (
                "Codex App Server 不可用，已切换到本地兼容模式。"
                if sessions
                else "Codex App Server 不可用，且本地会话不可读；请升级 codex-session-manager。"
            )
            return sessions

        self.warning = ""
        return sessions


class CompatiblePreviewService:
    """Prefer App Server previews while retaining local-preview compatibility."""

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback

    def get(self, session: Session) -> Preview:
        try:
            return self.primary.get_preview(session)
        except AppServerError:
            return self.fallback.get(session)

"""Fallback adapters for App Server-backed session access."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .app_server import AppServerError
from .models import Preview, Session


@dataclass(slots=True)
class CompatibilityState:
    """Mutable compatibility status shared across list and preview adapters."""

    generation: int = 0
    listing_degraded: bool = False
    preview_degraded: bool = False
    warning: str = ""

    def begin_refresh(self) -> None:
        self.generation += 1
        self.listing_degraded = False
        self.preview_degraded = False
        self.warning = ""

    def degrade_listing(self, has_local_sessions: bool) -> None:
        self.listing_degraded = True
        self.warning = (
            "Codex App Server 不可用，已切换到本地兼容模式。"
            if has_local_sessions
            else "Codex App Server 不可用，且本地会话不可读；请升级 codex-session-manager。"
        )

    def degrade_preview(self) -> None:
        self.preview_degraded = True
        if not self.warning:
            self.warning = "Codex App Server 预览不可用，已切换到本地兼容模式。"


class CompatibleSessionRepository:
    """Prefer App Server sessions while retaining local-storage compatibility."""

    def __init__(self, primary, fallback, state: CompatibilityState):
        self.primary = primary
        self.fallback = fallback
        self.state = state

    @property
    def warning(self) -> str:
        return self.state.warning

    @warning.setter
    def warning(self, value: str) -> None:
        self.state.warning = value

    def list_sessions(self) -> list[Session]:
        self.state.begin_refresh()
        try:
            sessions = self.primary.list_sessions()
        except AppServerError:
            sessions = self.fallback.list_sessions()
            self.state.degrade_listing(bool(sessions))
            return sessions

        return sessions


class CompatiblePreviewService:
    """Prefer App Server previews while retaining local-preview compatibility."""

    def __init__(
        self,
        primary,
        fallback_repository,
        fallback,
        state: CompatibilityState,
    ):
        self.primary = primary
        self.fallback_repository = fallback_repository
        self.fallback = fallback
        self.state = state
        self._cache_generation = state.generation
        self._cache: dict[
            tuple[int, str, str, str, float, float, str], Preview
        ] = {}

    def get(self, session: Session) -> Preview:
        self._invalidate_after_refresh()
        cache_key = (self.state.generation, *self._fingerprint(session))
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        if self.state.listing_degraded or self.state.preview_degraded:
            return self.fallback.get(self._resolve_local_session(session))
        try:
            preview = self.primary.get_preview(session)
        except AppServerError:
            self.state.degrade_preview()
            return self.fallback.get(self._resolve_local_session(session))
        self._cache[cache_key] = preview
        return preview

    def _invalidate_after_refresh(self) -> None:
        if self._cache_generation == self.state.generation:
            return
        self._cache.clear()
        self._cache_generation = self.state.generation

    @staticmethod
    def _fingerprint(session: Session) -> tuple[str, str, str, float, float, str]:
        return (
            session.id,
            session.first_question,
            session.cwd,
            session.created_at,
            session.last_opened_at,
            session.rollout_path,
        )

    def _resolve_local_session(self, session: Session) -> Session:
        if session.rollout_path:
            return session
        for local_session in self.fallback_repository.list_sessions():
            if local_session.id == session.id and local_session.rollout_path:
                return replace(session, rollout_path=local_session.rollout_path)
        return session

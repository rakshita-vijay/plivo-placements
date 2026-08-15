"""Storage for in-flight call sessions.

The IVR is stateless where it safely can be — the selected language and the
prompt reason travel in the callback URL — but authentication state and attempt
counters must never be caller-controllable, so they live server side.

:class:`InMemoryCallSessionStore` is the default and sits behind the
:class:`CallSessionStore` protocol: swapping in Redis for a multi-worker
deployment means implementing this interface and changing one line in
``app/dependencies.py``.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.core.models import CallSession


class CallSessionStore(Protocol):
    """Interface every session backend must satisfy."""

    def create(self, session: CallSession) -> CallSession: ...

    def get(self, session_id: str) -> CallSession | None: ...

    def get_by_call_uuid(self, call_uuid: str) -> CallSession | None: ...

    def save(self, session: CallSession) -> CallSession: ...

    def delete(self, session_id: str) -> None: ...

    def list_recent(self, limit: int = 20) -> list[CallSession]: ...


class InMemoryCallSessionStore:
    """Thread-safe, TTL-bounded, process-local session store.

    Expired entries are evicted lazily on access, so no background task is
    needed. A secondary index maps Plivo's ``CallUUID`` back to our session,
    which is how hangup events find their call when the URL is not ours.
    """

    def __init__(self, ttl_seconds: int = 3600, max_sessions: int = 1000) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_sessions = max_sessions
        self._sessions: dict[str, CallSession] = {}
        self._call_uuid_index: dict[str, str] = {}
        self._lock = threading.RLock()

    def create(self, session: CallSession) -> CallSession:
        with self._lock:
            self._evict_expired()
            self._enforce_capacity()
            self._sessions[session.session_id] = session
            self._reindex(session)
            return session

    def get(self, session_id: str) -> CallSession | None:
        with self._lock:
            self._evict_expired()
            return self._sessions.get(session_id)

    def get_by_call_uuid(self, call_uuid: str) -> CallSession | None:
        with self._lock:
            self._evict_expired()
            session_id = self._call_uuid_index.get(call_uuid)
            return self._sessions.get(session_id) if session_id else None

    def save(self, session: CallSession) -> CallSession:
        with self._lock:
            session.touch()
            self._sessions[session.session_id] = session
            self._reindex(session)
            return session

    def delete(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session and session.call_uuid:
                self._call_uuid_index.pop(session.call_uuid, None)

    def list_recent(self, limit: int = 20) -> list[CallSession]:
        with self._lock:
            self._evict_expired()
            newest_first = sorted(
                self._sessions.values(), key=lambda item: item.created_at, reverse=True
            )
            return newest_first[:limit]

    def clear(self) -> None:
        """Drop all sessions. Used by the test suite between cases."""
        with self._lock:
            self._sessions.clear()
            self._call_uuid_index.clear()

    # ------------------------------------------------------------------
    # Internals — callers already hold the lock.
    # ------------------------------------------------------------------
    def _reindex(self, session: CallSession) -> None:
        if session.call_uuid:
            self._call_uuid_index[session.call_uuid] = session.session_id

    def _evict_expired(self) -> None:
        cutoff = datetime.now(UTC) - self._ttl
        expired_ids = [
            session_id
            for session_id, session in self._sessions.items()
            if session.updated_at < cutoff
        ]
        for session_id in expired_ids:
            session = self._sessions.pop(session_id)
            if session.call_uuid:
                self._call_uuid_index.pop(session.call_uuid, None)

    def _enforce_capacity(self) -> None:
        overflow = len(self._sessions) - self._max_sessions + 1
        if overflow <= 0:
            return
        oldest_first = sorted(self._sessions.items(), key=lambda item: item[1].updated_at)
        for session_id, session in oldest_first[:overflow]:
            del self._sessions[session_id]
            if session.call_uuid:
                self._call_uuid_index.pop(session.call_uuid, None)

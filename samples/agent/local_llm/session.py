"""In-memory session store with TTL-based eviction."""

import time
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["user", "assistant"]

MAX_SESSIONS = 100
SESSION_TTL_SECONDS = 3600  # 1 hour
MAX_MESSAGES_PER_SESSION = 40  # sliding window


@dataclass
class Session:
    id: str
    messages: list[dict] = field(default_factory=list)
    last_accessed: float = field(default_factory=time.time)


class SessionStore:
    """In-memory session manager with TTL eviction and max-size cap."""

    def __init__(self, max_sessions: int = MAX_SESSIONS, ttl: float = SESSION_TTL_SECONDS):
        self._sessions: dict[str, Session] = {}
        self._max_sessions = max_sessions
        self._ttl = ttl

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if now - s.last_accessed > self._ttl]
        for sid in expired:
            del self._sessions[sid]

    def _evict_oldest_if_full(self) -> None:
        if len(self._sessions) >= self._max_sessions:
            oldest_id = min(self._sessions, key=lambda sid: self._sessions[sid].last_accessed)
            del self._sessions[oldest_id]

    def create(self, session_id: str) -> Session:
        self._evict_expired()
        self._evict_oldest_if_full()
        session = Session(id=session_id)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if time.time() - session.last_accessed > self._ttl:
            del self._sessions[session_id]
            return None
        session.last_accessed = time.time()
        return session

    def get_or_create(self, session_id: str) -> Session:
        session = self.get(session_id)
        if session is None:
            return self.create(session_id)
        return session

    def add_message(self, session_id: str, role: Role, content: str) -> None:
        session = self.get_or_create(session_id)
        session.messages.append({"role": role, "content": content})
        # Sliding window: keep last N messages to bound memory and LLM token cost
        if len(session.messages) > MAX_MESSAGES_PER_SESSION:
            session.messages = session.messages[-MAX_MESSAGES_PER_SESSION:]

    @property
    def size(self) -> int:
        return len(self._sessions)

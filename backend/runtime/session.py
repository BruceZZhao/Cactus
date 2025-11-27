from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class SessionState:
    session_id: str
    language: str = "ENG"
    current_token: Optional[str] = None
    history: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    logs: Dict[str, List[dict]] = field(default_factory=dict)


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def create(self, session_id: str) -> SessionState:
        async with self._lock:
            state = SessionState(session_id=session_id)
            self._sessions[session_id] = state
            return state

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def get(self, session_id: str) -> Optional[SessionState]:
        async with self._lock:
            return self._sessions.get(session_id)

    async def set_token(self, session_id: str, token: str) -> None:
        async with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].current_token = token

    async def append_history(self, session_id: str, text: str) -> None:
        async with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].history.append(text)


session_registry = SessionRegistry()


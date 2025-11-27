from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from backend.runtime.session import session_registry


async def get_session_value(session_id: str, key: str) -> Optional[Any]:
    state = await session_registry.get(session_id)
    if not state:
        return None
    return state.data.get(key)


async def set_session_value(session_id: str, key: str, value: Any) -> None:
    state = await session_registry.get(session_id)
    if not state:
        state = await session_registry.create(session_id)
    state.data[key] = value


async def append_log(session_id: str, character: str, log_entry: dict) -> None:
    state = await session_registry.get(session_id)
    if not state:
        state = await session_registry.create(session_id)
    logs = state.logs.setdefault(character, [])
    logs.append(log_entry)


async def get_conversation_log(session_id: str, character: str) -> List[dict]:
    state = await session_registry.get(session_id)
    if not state:
        return []
    return list(state.logs.get(character, []))


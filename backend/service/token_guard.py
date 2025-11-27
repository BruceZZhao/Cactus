from __future__ import annotations

from backend.runtime.session import session_registry


async def set_current_token(session_id: str, token: str) -> None:
    await session_registry.set_token(session_id, token)


async def is_token_current(session_id: str, token: str) -> bool:
    state = await session_registry.get(session_id)
    if not state:
        return False
    return state.current_token == token


"""Example test for session management."""
import pytest
from backend.runtime.session import session_registry


@pytest.mark.asyncio
async def test_session_create():
    session_id = "test_session_123"
    state = await session_registry.create(session_id)
    assert state.session_id == session_id
    retrieved = await session_registry.get(session_id)
    assert retrieved is not None
    assert retrieved.session_id == session_id


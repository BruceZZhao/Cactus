from __future__ import annotations

import asyncio

from backend.runtime.bus import audio_bus
from backend.runtime.queues import queue_registry
from backend.runtime.session import session_registry
from backend.service.llm import llm_worker
from backend.service.tts import tts_worker


class SessionOrchestrator:
    async def start(self, session_id: str) -> None:
        await session_registry.create(session_id)
        queue_registry.get(session_id)
        audio_bus.queue(session_id)
        asyncio.create_task(llm_worker(session_id))
        asyncio.create_task(tts_worker(session_id))

    async def stop(self, session_id: str) -> None:
        await session_registry.delete(session_id)
        queue_registry.delete(session_id)
        audio_bus.delete(session_id)


orchestrator = SessionOrchestrator()


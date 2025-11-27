from __future__ import annotations

import asyncio
from typing import Dict

from dataclasses import dataclass


@dataclass
class SessionQueues:
    asr_queue: asyncio.Queue
    sentence_queue: asyncio.Queue


class QueueRegistry:
    def __init__(self) -> None:
        self._queues: Dict[str, SessionQueues] = {}

    def get(self, session_id: str) -> SessionQueues:
        if session_id not in self._queues:
            self._queues[session_id] = SessionQueues(
                asr_queue=asyncio.Queue(),
                sentence_queue=asyncio.Queue(),
            )
        return self._queues[session_id]

    def delete(self, session_id: str) -> None:
        self._queues.pop(session_id, None)


queue_registry = QueueRegistry()


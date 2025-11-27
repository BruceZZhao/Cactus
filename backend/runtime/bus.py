from __future__ import annotations

import asyncio
from typing import Any, Dict

from dataclasses import dataclass


class AudioBus:
    def __init__(self) -> None:
        self._queues: Dict[str, asyncio.Queue[Dict[str, Any]]] = {}

    def queue(self, session_id: str) -> asyncio.Queue[Dict[str, Any]]:
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue()
        return self._queues[session_id]

    def delete(self, session_id: str) -> None:
        self._queues.pop(session_id, None)


audio_bus = AudioBus()


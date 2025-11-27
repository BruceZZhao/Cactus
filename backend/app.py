from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load .env from project root (parent folder)
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

log_level_name = os.getenv("CLEAN_LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_name, logging.DEBUG)
logging.basicConfig(level=log_level)

import time

from backend.config import get_settings
from backend.data_loader import get_characters, get_scripts
from backend.runtime.bus import audio_bus
from backend.runtime.queues import queue_registry
from backend.runtime.session import session_registry
from backend.service import asr
from backend.service.orchestrator import orchestrator
from backend.service.token_guard import set_current_token

logger = logging.getLogger(__name__)

app = FastAPI(title="Clean Voice Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
async def get_config() -> dict[str, dict]:
    return {"characters": get_characters(), "scripts": get_scripts()}


@app.post("/sessions")
async def create_session() -> dict[str, str]:
    session_id = uuid.uuid4().hex
    await orchestrator.start(session_id)
    return {"session_id": session_id}


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    if not await session_registry.get(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    await orchestrator.stop(session_id)
    return {"status": "stopped"}


@app.post("/respond")
async def respond(request: Request) -> dict[str, str]:
    """Handle text input from user, enqueue to ASR queue for LLM processing."""
    data = await request.json()
    text = data.get("text", "").strip()
    session_id = data.get("session_id", "")

    logger.info(f"/respond called: session_id={session_id}, text={text[:50]}...")

    if not session_id:
        logger.error("Missing session_id in /respond request")
        raise HTTPException(status_code=400, detail="Missing session_id")
    if not text:
        logger.error("Missing text in /respond request")
        raise HTTPException(status_code=400, detail="Missing text")

    state = await session_registry.get(session_id)
    if not state:
        logger.error(f"Session not found: {session_id}")
        raise HTTPException(status_code=404, detail="Session not found")

    logger.info(f"Session found, enqueueing text to ASR queue for session {session_id}")

    # Send stop signal to audio bus
    await audio_bus.queue(session_id).put({"type": "stop"})

    # Generate token and enqueue to ASR queue
    token = f"t{session_id}_{int(time.time() * 1000)}"
    await set_current_token(session_id, token)

    queue = queue_registry.get(session_id)
    await queue.asr_queue.put(
        {
            "text": text,
            "token": token,
            "session_id": session_id,
            "timestamp": time.time(),
        }
    )

    await session_registry.append_history(session_id, text)
    logger.info(f"Text enqueued to ASR queue for session {session_id}, token={token}")

    return {"status": "enqueued"}


@app.websocket("/ws/audio-in/{session_id}")
async def audio_in(ws: WebSocket, session_id: str) -> None:
    state = await session_registry.get(session_id)
    if not state:
        await ws.close(code=4404)
        return
    await asr.asr_websocket_handler(ws, session_id)


@app.websocket("/ws/audio-out/{session_id}")
async def audio_out(ws: WebSocket, session_id: str) -> None:
    state = await session_registry.get(session_id)
    if not state:
        await ws.close(code=4404)
        return
    queue = audio_bus.queue(session_id)
    await ws.accept()
    try:
        while True:
            packet = await queue.get()
            metadata = packet.copy()
            audio_bytes = metadata.pop("audio", None)
            if metadata:
                await ws.send_json({"type": "metadata", **metadata})
            if audio_bytes:
                await ws.send_bytes(audio_bytes)
    except WebSocketDisconnect:
        return


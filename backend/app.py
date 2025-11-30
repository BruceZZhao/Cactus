from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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

# Load Google Cloud credentials
# Supports GOOGLE_APPLICATION_CREDENTIALS (absolute) or Google_CLOUD_KEY (relative)
# Handles BOM in .env files from PowerShell
_google_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("\ufeffGOOGLE_APPLICATION_CREDENTIALS")
_google_key_path = os.getenv("Google_CLOUD_KEY") or os.getenv("\ufeffGoogle_CLOUD_KEY")

if _google_creds:
    # Use GOOGLE_APPLICATION_CREDENTIALS if set (absolute path)
    _cred_path = Path(_google_creds)
    if _cred_path.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_cred_path)
        logger.info(f"Google Cloud credentials loaded from GOOGLE_APPLICATION_CREDENTIALS: {_cred_path}")
    else:
        logger.warning(f"Google Cloud credentials file not found at: {_cred_path}")
        logger.warning("TTS and ASR features will not work without credentials.")
elif _google_key_path:
    # Use Google_CLOUD_KEY if set (relative path from project root)
    _key_path = _project_root / _google_key_path
    if _key_path.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_key_path)
        logger.info(f"Google Cloud credentials loaded from Google_CLOUD_KEY: {_key_path}")
    else:
        logger.warning(f"Google Cloud credentials file not found at: {_key_path}")
        logger.warning("TTS and ASR features will not work without credentials.")
else:
    logger.info("Neither GOOGLE_APPLICATION_CREDENTIALS nor Google_CLOUD_KEY set in .env")
    logger.info("TTS and ASR features will not work without credentials.")

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
    try:
        session_id = uuid.uuid4().hex
        logger.info(f"Creating session: {session_id}")
        await orchestrator.start(session_id)
        logger.info(f"Session {session_id} created successfully")
        return {"session_id": session_id}
    except Exception as e:
        logger.exception(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    if not await session_registry.get(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    await orchestrator.stop(session_id)
    return {"status": "stopped"}


@app.post("/sessions/{session_id}/settings")
async def set_session_settings(session_id: str, request: Request) -> dict[str, str]:
    """Set session settings: rag_mode, character, script, language"""
    from backend.runtime.session_store import set_session_value
    
    state = await session_registry.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    
    data = await request.json()
    
    if "rag_mode" in data:
        await set_session_value(session_id, "rag_mode", data["rag_mode"])
    if "character" in data:
        await set_session_value(session_id, "character", data["character"])
    if "script" in data:
        await set_session_value(session_id, "script", data["script"])
    if "language" in data:
        await set_session_value(session_id, "language", data["language"])
    
    return {"status": "updated"}


@app.post("/set-character")
async def set_character(request: Request) -> JSONResponse:
    """Set character for a session"""
    try:
        from backend.runtime.session_store import set_session_value, get_session_value
        
        data = await request.json()
        session_id = data.get("session_id", "")
        character_name = data.get("name", "")
        
        logger.info(f"/set-character called: session_id={session_id}, character_name={character_name}")
        
        if not session_id:
            logger.error("Missing session_id in /set-character request")
            raise HTTPException(status_code=400, detail="Missing session_id")
        if not character_name:
            logger.error("Missing character name in /set-character request")
            raise HTTPException(status_code=400, detail="Missing character name")
        
        state = await session_registry.get(session_id)
        if not state:
            logger.error(f"Session not found in /set-character: {session_id}")
            raise HTTPException(status_code=404, detail="Session not found")
        
        await set_session_value(session_id, "character", character_name)
        logger.info(f"Character for session {session_id} set to: {character_name}")
        
        # Verify setting
        verify_char = await get_session_value(session_id, "character")
        logger.info(f"Verified character for session {session_id}: {verify_char}")
        
        return JSONResponse(content={"success": True, "character": character_name})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in /set-character: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/set-script")
async def set_script(request: Request) -> JSONResponse:
    """Set script for a session"""
    try:
        from backend.runtime.session_store import set_session_value
        
        data = await request.json()
        session_id = data.get("session_id", "")
        script_name = data.get("script", "")
        
        logger.info(f"/set-script called: session_id={session_id}, script_name={script_name}")
        
        if not session_id:
            logger.error("Missing session_id in /set-script request")
            raise HTTPException(status_code=400, detail="Missing session_id")
        if not script_name:
            logger.error("Missing script name in /set-script request")
            raise HTTPException(status_code=400, detail="Missing script name")
        
        state = await session_registry.get(session_id)
        if not state:
            logger.error(f"Session not found in /set-script: {session_id}")
            raise HTTPException(status_code=404, detail="Session not found")
        
        await set_session_value(session_id, "script", script_name)
        logger.info(f"Script for session {session_id} set to: {script_name}")
        
        return JSONResponse(content={"status": "ok", "script": script_name})
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in /set-script: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


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


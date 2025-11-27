"""
Simple end-to-end client that uses the FastAPI app directly.

Usage:
    source venv/bin/activate
    python quick_launch/simple_repl.py

It will create a backend session, stream microphone audio to
/ws/audio-in/<session>, and play TTS responses coming from
/ws/audio-out/<session>. Requires working microphone permissions and
the backend running locally on port 8000.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import numpy as np
import sounddevice as sd
import websockets
import httpx

logging.basicConfig(level=logging.INFO, format="[simple-client] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8000"
WS_BASE = "ws://127.0.0.1:8000"
SAMPLE_RATE = 16000
CHUNK_SIZE = 3200


async def create_session() -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{BASE_URL}/sessions")
        resp.raise_for_status()
        data = resp.json()
        return data["session_id"]


async def stream_mic(session_id: str, pause_flag: asyncio.Event) -> None:
    url = f"{WS_BASE}/ws/audio-in/{session_id}"
    logger.info(f"streaming microphone to {url}")
    loop = asyncio.get_running_loop()
    pcm_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def callback(indata, frames, time_info, status):  # type: ignore[override]
        if status:
            logger.warning("input status: %s", status)
        if not pause_flag.is_set():
            chunk = bytes(indata)
            rms = np.sqrt(np.mean(np.frombuffer(chunk, dtype=np.int16) ** 2))
            logger.debug("mic chunk rms=%.2f frames=%d", rms, frames)
            loop.call_soon_threadsafe(pcm_queue.put_nowait, chunk)

    stream = sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK_SIZE,
        callback=callback,
    )
    stream.start()

    async def handle_server_messages(ws: websockets.WebSocketClientProtocol) -> None:
        try:
            async for msg in ws:
                if isinstance(msg, str):
                    try:
                        data = json.loads(msg)
                    except json.JSONDecodeError:
                        continue
                    msg_type = data.get("type")
                    text = data.get("text", "").strip()
                    if msg_type == "voice_interim" and text:
                        logger.info("you (interim): %s", text)
                    elif msg_type == "voice_final" and text:
                        logger.info("you: %s", text)
                # ignore binary coming back on audio-in socket
        except websockets.ConnectionClosed:
            logger.info("ASR websocket closed")

    try:
        async with websockets.connect(url, ping_interval=None, ping_timeout=None) as ws:
            recv_task = asyncio.create_task(handle_server_messages(ws))
            try:
                while True:
                    chunk = await pcm_queue.get()
                    if chunk is None:
                        break
                    await ws.send(chunk)
            finally:
                await ws.close()
                await recv_task
    finally:
        stream.stop()
        stream.close()
        await pcm_queue.put(None)


async def play_tts(session_id: str, pause_flag: asyncio.Event) -> None:
    url = f"{WS_BASE}/ws/audio-out/{session_id}"
    logger.info(f"listening for TTS on {url}")

    async with websockets.connect(url, ping_interval=None, ping_timeout=None) as ws:
        while True:
            msg = await ws.recv()
            if isinstance(msg, str):
                data = json.loads(msg)
                if data.get("type") == "metadata" and data.get("sentence"):
                    logger.info("assistant: %s", data["sentence"])
            else:
                audio = np.frombuffer(msg, dtype=np.int16).copy()
                if len(audio) > 800:
                    audio = audio[800:]
                pause_flag.set()
                sd.play(audio, samplerate=16000)
                await asyncio.sleep(len(audio) / 16000 + 0.05)
                pause_flag.clear()


async def main() -> None:
    session_id = await create_session()
    logger.info("session=%s", session_id)
    pause_flag = asyncio.Event()
    pause_flag.clear()
    await asyncio.gather(stream_mic(session_id, pause_flag), play_tts(session_id, pause_flag))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting simple client")



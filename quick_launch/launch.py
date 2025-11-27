"""Launch script for testing microphone input and ASR output."""
import asyncio
import json
import logging
import time
from typing import Optional

import numpy as np
import sounddevice as sd
import websockets
import httpx

logging.basicConfig(level=logging.INFO, format="[mic-test] %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "http://127.0.0.1:8000"
WS_BASE = "ws://127.0.0.1:8000"
SAMPLE_RATE = 16000
CHUNK_SIZE = 3200

# Switch to enable/disable microphone pausing during audio playback
PAUSE_MIC_DURING_PLAYBACK = True


async def create_session() -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{BASE_URL}/sessions")
        resp.raise_for_status()
        data = resp.json()
        return data["session_id"]


async def stream_microphone(session_id: str, mic_paused: asyncio.Event):
    url = f"{WS_BASE}/ws/audio-in/{session_id}"
    async with websockets.connect(url, ping_interval=None, ping_timeout=None) as ws:
        logger.info(f"streaming mic to {url}")

        def callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"status: {status}")
            if not mic_paused.is_set():
                pcm = (indata[:, 0] * 32767).astype("int16").tobytes()
                asyncio.create_task(ws.send(pcm))
                # Check volume for interruption
                if PAUSE_MIC_DURING_PLAYBACK:
                    rms = np.sqrt(np.mean(indata**2)) * 1000
                    if rms > 100:
                        mic_paused.clear()

        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=CHUNK_SIZE, callback=callback
        ):
            while True:
                msg = await ws.recv()
                if isinstance(msg, str):
                    data = json.loads(msg)
                    if data.get("type") == "voice_final":
                        logger.info(f"voice_final: {data.get('text')}")
                    elif data.get("type") == "voice_interim":
                        pass  # Removed print statement


async def listen_chat(session_id: str, mic_paused: asyncio.Event):
    url = f"{WS_BASE}/ws/audio-out/{session_id}"
    async with websockets.connect(url, ping_interval=None, ping_timeout=None) as ws:
        logger.info(f"listening for chat on {url}")

        audio_queue = asyncio.Queue()
        is_playing = False

        async def play_audio_worker():
            nonlocal is_playing
            while True:
                item = await audio_queue.get()
                if item is None:
                    break
                audio_bytes, sample_rate = item
                is_playing = True
                if PAUSE_MIC_DURING_PLAYBACK:
                    mic_paused.set()

                audio = np.frombuffer(audio_bytes, dtype=np.int16).copy()
                
                # Skip first 500 samples if first sample is large (>1000)
                if len(audio) > 500 and abs(audio[0]) > 1000:
                    audio = audio[500:]
                    logger.debug(f"Skipped 500 samples from audio chunk (first sample was {audio[0]})")

                duration = len(audio) / sample_rate
                sd.play(audio, samplerate=sample_rate)
                await asyncio.sleep(duration + 0.1)
                is_playing = False
                if PAUSE_MIC_DURING_PLAYBACK:
                    await asyncio.sleep(0.2)
                    mic_paused.clear()

        play_task = asyncio.create_task(play_audio_worker())

        try:
            while True:
                msg = await ws.recv()
                if isinstance(msg, str):
                    data = json.loads(msg)
                    if data.get("type") == "metadata" and data.get("sentence"):
                        logger.info(f"assistant: {data.get('sentence')}")
                    elif data.get("type") == "stop":
                        logger.info("chat payload (stop): clearing audio queue")
                        while not audio_queue.empty():
                            try:
                                audio_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                elif isinstance(msg, bytes):
                    sample_rate = 16000
                    await audio_queue.put((msg, sample_rate))
                    logger.info(f"Queued audio chunk: {len(msg) // 2} samples @ {sample_rate}Hz")
        finally:
            await audio_queue.put(None)
            await play_task


async def main():
    session_id = await create_session()
    logger.info(f"session={session_id}")
    mic_paused = asyncio.Event()
    if not PAUSE_MIC_DURING_PLAYBACK:
        mic_paused.clear()
    else:
        mic_paused.set()
    await asyncio.gather(stream_microphone(session_id, mic_paused), listen_chat(session_id, mic_paused))


if __name__ == "__main__":
    asyncio.run(main())


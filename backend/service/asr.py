"""Google Speech-to-Text streaming handler for clean backend."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from fastapi import WebSocket
from google.cloud import speech
from starlette.websockets import WebSocketDisconnect, WebSocketState

from backend.config import get_settings
from backend.runtime.bus import audio_bus
from backend.runtime.queues import queue_registry
from backend.runtime.session import session_registry
from backend.runtime.session_store import set_session_value
from backend.service.token_guard import set_current_token

logger = logging.getLogger(__name__)


class ASRStream:
    def __init__(self, session_id: str) -> None:
        settings = get_settings().asr
        self.session_id = session_id
        self.sample_rate = settings.sample_rate
        self.frame_ms = settings.frame_ms
        self.frame_bytes = 2 * self.sample_rate * self.frame_ms // 1000
        self.stop_event = asyncio.Event()
        self.audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        self._loop = asyncio.get_running_loop()

    async def receive_audio(self, websocket: WebSocket) -> None:
        try:
            while True:
                msg = await websocket.receive()
                if msg.get("type") == "websocket.receive":
                    data = msg.get("bytes")
                    if data:
                        await self.audio_queue.put(data)
                        logger.debug("ASR received %d bytes from session %s", len(data), self.session_id)
                elif msg.get("type") == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            logger.info("ASR websocket disconnected: %s", self.session_id)
        finally:
            self.stop_event.set()
            await self.audio_queue.put(None)

    def request_generator(self) -> speech.StreamingRecognizeRequest:
        while not self.stop_event.is_set():
            fut = asyncio.run_coroutine_threadsafe(self.audio_queue.get(), self._loop)
            chunk = fut.result()
            if chunk is None:
                return
            for idx in range(0, len(chunk), self.frame_bytes):
                frame = chunk[idx : idx + self.frame_bytes]
                if frame:
                    yield speech.StreamingRecognizeRequest(audio_content=frame)


async def asr_websocket_handler(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    asr_stream = ASRStream(session_id)
    queue = queue_registry.get(session_id).asr_queue
    settings = get_settings()

    client = speech.SpeechClient()
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=asr_stream.sample_rate,
        language_code=settings.asr.language,
        enable_automatic_punctuation=True,
        max_alternatives=1,
        use_enhanced=True,
    )
    stream_config = speech.StreamingRecognitionConfig(config=config, interim_results=True, single_utterance=False)

    async def transcribe() -> None:
        loop = asyncio.get_event_loop()
        response_queue: asyncio.Queue[Optional[speech.StreamingRecognizeResponse]] = asyncio.Queue()

        def _run_stream() -> None:
            try:
                responses = client.streaming_recognize(stream_config, asr_stream.request_generator())
                for resp in responses:
                    loop.call_soon_threadsafe(response_queue.put_nowait, resp)
            except Exception as exc:  # pragma: no cover
                error_msg = str(exc)
                # Google Speech-to-Text throws timeout errors when audio stream stops
                # This is expected when WebSocket closes or user stops speaking
                if "Audio Timeout Error: Long duration elapsed without audio" in error_msg:
                    logger.debug("ASR stream timeout (expected when audio stops): %s", error_msg)
                else:
                    logger.warning("ASR stream error: %s", exc)
            finally:
                loop.call_soon_threadsafe(response_queue.put_nowait, None)

        loop.run_in_executor(None, _run_stream)
        last_interim = ""
        token = None

        while True:
            if websocket.client_state != WebSocketState.CONNECTED:
                break
            resp = await response_queue.get()
            if resp is None:
                break
            if not resp.results:
                continue
            result = resp.results[-1]
            text = result.alternatives[0].transcript.strip() if result.alternatives else ""
            if not text:
                continue

            if result.is_final:
                if token and text:
                    logger.info("ASR final (%s): %s", session_id, text)
                    await websocket.send_json({"type": "voice_final", "text": text})
                    await queue.put(
                        {
                            "text": text,
                            "token": token,
                            "session_id": session_id,
                            "timestamp": time.time(),
                        }
                    )
                    await set_current_token(session_id, token)
                    await session_registry.append_history(session_id, text)
                last_interim = ""
                token = None
                continue

            if text != last_interim:
                last_interim = text
                if not token:
                    token = f"t{session_id}_{int(time.time() * 1000)}"
                    await audio_bus.queue(session_id).put({"type": "stop"})
                logger.debug("ASR interim (%s): %s", session_id, text)
                await websocket.send_json({"type": "voice_interim", "text": text})
                await set_session_value(session_id, "language", settings.asr.language)

    await asyncio.gather(asr_stream.receive_audio(websocket), transcribe())


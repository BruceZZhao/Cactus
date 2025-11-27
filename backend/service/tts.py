"""TTS streaming worker for clean backend."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from google.cloud import texttospeech

from backend.config import get_settings
from backend.runtime.bus import audio_bus
from backend.runtime.queues import queue_registry
from backend.service.token_guard import is_token_current

logger = logging.getLogger(__name__)


OUTPUT_SAMPLE_RATE = 16000


class TTSClient:
    def __init__(self) -> None:
        self._client = texttospeech.TextToSpeechClient()
        cfg = get_settings().tts
        self.voice = texttospeech.VoiceSelectionParams(
            language_code=cfg.language_code,
            name=cfg.voice,
        )
        self.audio_cfg = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=OUTPUT_SAMPLE_RATE,
        )

    async def synthesize(self, text: str) -> Optional[bytes]:
        input_cfg = texttospeech.SynthesisInput(text=text)
        try:
            response = await asyncio.to_thread(
                self._client.synthesize_speech,
                request={
                    "input": input_cfg,
                    "voice": self.voice,
                    "audio_config": self.audio_cfg,
                },
            )
            return response.audio_content
        except Exception as exc:  # pragma: no cover
            logger.error("TTS synthesis failed: %s", exc)
            return None


async def tts_worker(session_id: str) -> None:
    """Continuously consumes sentences and streams audio via audio bus."""
    queues = queue_registry.get(session_id)
    client = TTSClient()
    out_queue = audio_bus.queue(session_id)

    async def _drain_sentence_queue() -> None:
        while not queues.sentence_queue.empty():
            try:
                queues.sentence_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    while True:
        task = await queues.sentence_queue.get()
        sentence = task.get("sentence")
        if not sentence:
            logger.warning("Empty sentence received, skipping")
            continue
        token = task.get("token")
        if not await is_token_current(session_id, token):
            logger.warning("Token no longer current, skipping sentence: %s", sentence[:50])
            await _drain_sentence_queue()
            continue

        logger.info("Synthesizing sentence: %s", sentence)
        audio_bytes = await client.synthesize(sentence)
        if not audio_bytes:
            logger.error("TTS synthesis failed for sentence: %s", sentence[:50])
            continue
        if not await is_token_current(session_id, token):
            logger.warning("Token changed after synthesis, discarding audio for: %s", sentence[:50])
            continue

        logger.info("Sending audio to bus for sentence: %s (audio size: %d bytes)", sentence[:50], len(audio_bytes))
        await out_queue.put(
            {
                "audio": audio_bytes,
                "sentence": sentence,
                "emotion": task.get("emotion", "NEU"),
                "sample_rate": OUTPUT_SAMPLE_RATE,
            }
        )


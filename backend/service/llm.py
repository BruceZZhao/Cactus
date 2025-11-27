"""LLM streaming worker for clean backend."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import AsyncIterator

import google.generativeai as genai
from dotenv import load_dotenv

from backend.config import get_settings
from backend.prompt import generate_general_prompt
from backend.runtime.bus import audio_bus
from backend.runtime.queues import queue_registry
from backend.runtime.session_store import append_log, get_conversation_log, get_session_value
from backend.service.token_guard import is_token_current, set_current_token

# Configure genai at module level like reference code - load from parent folder
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_project_root / ".env")
genai.configure(api_key=os.getenv("Google_LLM_API"))
LLM_MODEL_NAME = os.getenv("CLEAN_LLM_MODEL", "models/gemini-2.5-flash-lite")
LLM_THINKER_MODEL_NAME = os.getenv("CLEAN_LLM_THINKER_MODEL", "models/gemini-2.5-flash")

logger = logging.getLogger(__name__)
SENTENCE_RE = re.compile(r"(.+?[。．\.！？!?…])(\s*.*)")
MAX_SENT_BYTES = 800


async def _gemini_stream(prompt: str) -> AsyncIterator[str]:
    model = genai.GenerativeModel(LLM_MODEL_NAME)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _producer() -> None:
        try:
            # Use config values or defaults like reference code
            settings = get_settings().llm
            stream = model.generate_content(
                prompt,
                stream=True,
                generation_config={
                    "temperature": settings.temperature,
                    "max_output_tokens": settings.max_output_tokens,
                },
            )
            for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    loop.call_soon_threadsafe(queue.put_nowait, text)
        except Exception as exc:  # pragma: no cover
            logger.error("Gemini stream failed: %s", exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop.run_in_executor(None, _producer)

    while True:
        token = await queue.get()
        if token is None:
            break
        yield token


async def llm_worker(session_id: str) -> None:
    queues = queue_registry.get(session_id)
    while True:
        task = await queues.asr_queue.get()
        text = task.get("text", "").strip()
        token = task.get("token")
        if not text:
            continue

        language = (await get_session_value(session_id, "language") or "ENG").upper()
        character_id = await get_session_value(session_id, "character") or "model_5"
        script_id = await get_session_value(session_id, "script") or "script_1"
        from backend.data_loader import get_characters, get_scripts

        all_characters = get_characters()
        all_scripts = get_scripts()
        character = all_characters.get(str(character_id), {"name": "Companion", "identity": ""})
        script = all_scripts.get(str(script_id), {"description": "", "assistant_role": "", "assistant_goal": "", "user_role": ""})
        rag_enabled = await get_session_value(session_id, "rag_mode")
        rag_enabled = bool(rag_enabled) if isinstance(rag_enabled, bool) else str(rag_enabled or "").lower() == "true"
        topic = await get_session_value(session_id, f"topic:{character_id}") or ""
        use_mode = await get_session_value(session_id, "use_mode") or ""
        current_history = await get_session_value(session_id, f"history:{character_id}") or ""
        conversation_log = await get_conversation_log(session_id, str(character_id))
        await append_log(session_id, str(character_id), {"user said": text, "timestamp": time.strftime("%H:%M:%S")})

        try:
            prompt = generate_general_prompt(
                message=text,
                topic=topic,
                use_mode=use_mode,
                current_history=current_history,
                conversation_log=conversation_log,
                character=character,
                script=script,
                language=language,
                rag_enabled=rag_enabled,
            )
        except Exception as exc:
            logger.warning("Prompt generation failed: %s, using fallback", exc)
            # Fallback to simple prompt if generation fails
            prompt = f"You are a friendly voice companion. Respond concisely but with natural speech.\nUser: {text}\nAssistant:"

        full_response = ""
        sentence_buffer = ""
        
        async for chunk in _gemini_stream(prompt):
            if not chunk:
                continue

            if not await is_token_current(session_id, token):
                break

            await set_current_token(session_id, token)
            full_response += chunk
            sentence_buffer += chunk
            
            # Log the current sentence buffer state for debugging
            if sentence_buffer:
                logger.debug("Sentence buffer after adding chunk: %s (length: %d)", sentence_buffer[:100], len(sentence_buffer))

            # Process all complete sentences from the buffer
            processed_any = False
            while True:
                # Clean up buffer first (remove leading dots/spaces that might prevent matching)
                sentence_buffer = sentence_buffer.lstrip('. \t\n\r')
                
                if not sentence_buffer:
                    break
                
                # Try to find the first sentence ending
                match = SENTENCE_RE.match(sentence_buffer)
                if match:
                    sentence = match.group(1).strip()
                    remaining = match.group(2).lstrip()
                    sentence_buffer = remaining
                    processed_any = True
                elif len(sentence_buffer.encode("utf-8")) >= MAX_SENT_BYTES:
                    # Force split if too long - find last sentence boundary
                    # Try to split at punctuation if possible
                    split_pos = MAX_SENT_BYTES // 3
                    for punct in ['.', '!', '?', '。', '！', '？']:
                        last_punct = sentence_buffer.rfind(punct, 0, split_pos)
                        if last_punct > 0:
                            split_pos = last_punct + 1
                            break
                    sentence = sentence_buffer[:split_pos].strip()
                    sentence_buffer = sentence_buffer[split_pos:].lstrip()
                    processed_any = True
                else:
                    # No match and not too long - might be incomplete sentence
                    # Log what we couldn't match for debugging
                    if sentence_buffer and not processed_any:
                        logger.debug("Could not match sentence pattern in buffer: %s", sentence_buffer[:100])
                    break
                
                if not sentence:
                    # If we got an empty sentence, skip it and try again
                    continue
                
                # Clean up sentence (remove extra dots/spaces, but preserve single dots)
                sentence = re.sub(r'\.{3,}', '...', sentence)  # Replace 3+ dots with ellipsis
                sentence = re.sub(r'\s+', ' ', sentence)  # Normalize whitespace
                sentence = sentence.strip()
                
                if not sentence:
                    continue
                
                if not await is_token_current(session_id, token):
                    logger.warning("Token no longer current, skipping sentence: %s", sentence[:50])
                    break
                
                logger.info("Queuing sentence to TTS (%d chars): %s", len(sentence), sentence)
                await queues.sentence_queue.put(
                    {
                        "sentence": sentence,
                        "token": token,
                        "session_id": session_id,
                    }
                )

        tail = sentence_buffer.strip()
        if tail and await is_token_current(session_id, token):
            logger.info("Queuing tail sentence to TTS: %s", tail)
            await queues.sentence_queue.put(
                {
                    "sentence": tail,
                    "token": token,
                    "session_id": session_id,
                }
            )

        await append_log(session_id, str(character_id), {"assistant said": full_response.strip(), "timestamp": time.strftime("%H:%M:%S")})


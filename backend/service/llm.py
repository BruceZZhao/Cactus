"""LLM streaming worker for clean backend."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import AsyncIterator

import google.generativeai as genai
from dotenv import load_dotenv

from backend.config import get_settings
from backend.prompt import generate_general_prompt, generate_thinker_prompt, generate_coach_prompt
from backend.runtime.bus import audio_bus
from backend.runtime.queues import queue_registry
from backend.runtime.session_store import (
    append_log,
    get_conversation_log,
    get_session_value,
    set_session_value,
)
from backend.service.token_guard import is_token_current, set_current_token

# Configure genai at module level
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
        logger.info(f"RAG enabled for session {session_id}: {rag_enabled}, character: {character_id}")
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
            # Use simple fallback prompt
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

            # Process complete sentences from buffer
            processed_any = False
            while True:
                # Clean buffer
                sentence_buffer = sentence_buffer.lstrip('. \t\n\r')
                
                if not sentence_buffer:
                    break
                
                # Find sentence ending
                match = SENTENCE_RE.match(sentence_buffer)
                if match:
                    sentence = match.group(1).strip()
                    remaining = match.group(2).lstrip()
                    sentence_buffer = remaining
                    processed_any = True
                elif len(sentence_buffer.encode("utf-8")) >= MAX_SENT_BYTES:
                    # Force split if too long
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
                    # Incomplete sentence
                    break
                
                if not sentence:
                    continue
                
                # Clean sentence
                sentence = re.sub(r'\.{3,}', '...', sentence)
                sentence = re.sub(r'\s+', ' ', sentence)
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

        # Trigger Thinker Agent for history and topic update
        updated_conversation_log = await get_conversation_log(session_id, str(character_id))
        logger.info(f"[Thinker] Conversation log length: {len(updated_conversation_log)}, threshold: 6")
        if len(updated_conversation_log) > 6:
            logger.info(f"[Thinker] Triggering background thinker update for session {session_id}, character {character_id}")
            asyncio.create_task(
                background_thinker_update(
                    session_id,
                    str(character_id),
                    current_history,
                    updated_conversation_log,
                )
            )
        else:
            logger.info(f"[Thinker] Not triggered yet (need > 6 messages, current: {len(updated_conversation_log)})")


def _first_text_from_response(resp) -> str:
    """Extract text from Gemini response safely."""
    try:
        for cand in getattr(resp, "candidates", []) or []:
            content = getattr(cand, "content", None)
            if not content:
                continue
            for p in getattr(content, "parts", []) or []:
                t = getattr(p, "text", None)
                if isinstance(t, str) and t.strip():
                    return t
        t = getattr(resp, "text", None)
        return t if isinstance(t, str) else ""
    except Exception:
        return ""


async def call_thinker_llm(character_history: str, new_logs: list) -> dict:
    """Call thinker LLM to generate character history summary and next topic."""
    logger.info(f"[Thinker] Calling LLM with history length: {len(character_history)}, new logs: {len(new_logs)}")
    summary_prompt = generate_thinker_prompt(character_history, new_logs)
    model = genai.GenerativeModel(LLM_THINKER_MODEL_NAME)

    try:
        logger.info("[Thinker] Sending request to Gemini for summary and next topic...")
        # Offload blocking SDK call to worker thread
        def _call_generate_content():
            return model.generate_content(
                summary_prompt,
                stream=False,
                generation_config={
                    "temperature": 0.1,
                    "top_p": 1.0,
                    "max_output_tokens": 1000
                }
            )
        resp = await asyncio.to_thread(_call_generate_content)
        logger.info("[Thinker] Received response from Gemini")
    except Exception as e:
        logger.warning(f"[Thinker] Generation failed: {e}")
        return {"summary": "", "next_topic": ""}

    txt = _first_text_from_response(resp)
    if not txt:
        logger.warning("[Thinker] Returned no text; skipping update.")
        return {"summary": "", "next_topic": ""}

    logger.info(f"[Thinker] Received text response (length: {len(txt)})")
    try:
        # Parse JSON, handle code fences
        txt_clean = txt.strip().strip("`").strip()
        if txt_clean.startswith("json"):
            txt_clean = txt_clean[4:].strip()
        parsed = json.loads(txt_clean)
        logger.info(f"[Thinker] Successfully parsed JSON: summary length={len(parsed.get('summary', ''))}, next_topic={parsed.get('next_topic', '')[:50]}...")
        return parsed
    except json.JSONDecodeError:
        logger.warning("[Thinker] JSON parse failed; using raw text as summary.")
        return {"summary": txt.strip(), "next_topic": ""}


async def background_thinker_update(
    session_id: str,
    character_id: str,
    character_history: str,
    log_entries: list,
):
    """Update conversation history and next topic in background."""
    logger.info(f"[Thinker] Starting background update for session {session_id}, character {character_id}")
    logger.info(f"[Thinker] Processing {len(log_entries)} log entries")
    try:
        thinker_output = await call_thinker_llm(character_history, log_entries)
    except Exception as e:
        logger.warning(f"[Thinker] Failed (bg): {e}")
        return

    summary = (thinker_output.get("summary") or "").strip()
    next_topic = (thinker_output.get("next_topic") or "").strip()

    logger.info(f"[Thinker] Got summary (length: {len(summary)}), next_topic: {next_topic[:50] if next_topic else 'None'}...")

    if summary:
        try:
            history_key = f"history:{character_id}"
            await set_session_value(session_id, history_key, summary)
            logger.info(f"[Thinker] ✅ Updated character history for session {session_id}, character {character_id}")
        except Exception as e:
            logger.warning(f"[Thinker] Failed to set history (bg): {e}")

    if next_topic:
        try:
            topic_key = f"topic:{character_id}"
            await set_session_value(session_id, topic_key, next_topic)
            logger.info(f"[Thinker] ✅ Updated next topic for session {session_id}, character {character_id}: {next_topic}")
        except Exception as e:
            logger.warning(f"[Thinker] Failed to set next topic (bg): {e}")
    
    if not summary and not next_topic:
        logger.warning("[Thinker] No summary or next_topic generated")

    # Keep only last two log entries
    try:
        current_logs = await get_conversation_log(session_id, character_id)
        if len(current_logs) > 2:
            # Keep only last 2 entries
            await set_session_value(session_id, f"logs:{character_id}", current_logs[-2:])
    except Exception as e:
        logger.warning("Thinker log trim failed (bg): %s", e)


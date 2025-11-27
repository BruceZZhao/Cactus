"""Prompt helpers adapted from the legacy backend."""
from __future__ import annotations

import datetime
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

from backend.config import get_settings

# Check if RAG is enabled in config
_rag_enabled = get_settings().rag.enabled

if _rag_enabled:
    try:
        from sentence_transformers import SentenceTransformer
        from qdrant_client.local.qdrant_local import QdrantLocal
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        _QdrantLocal = QdrantLocal
        SentenceTransformer_available = True
        QdrantLocal_available = True
    except Exception:  # pragma: no cover
        SentenceTransformer_available = False
        QdrantLocal_available = False
        _embed_model = None
        _QdrantLocal = None
        print("Warning: RAG enabled but sentence_transformers/qdrant not available")
else:
    SentenceTransformer_available = False
    QdrantLocal_available = False
    _embed_model = None
    _QdrantLocal = None

_project_root = os.path.dirname(os.path.abspath(__file__))
_qdrant_client = None


def _get_qdrant_client():
    global _qdrant_client
    if not _rag_enabled or not QdrantLocal_available or not _QdrantLocal:
        return None
    if _qdrant_client is None:
        location = os.getenv("CLEAN_QDRANT_LOCATION")
        if location:
            try:
                _qdrant_client = _QdrantLocal(location=location)
            except Exception as exc:  # pragma: no cover
                print(f"Warning: Could not initialize Qdrant client: {exc}")
    return _qdrant_client


character_rag_mapping = {
    "model_5": "profile_adam",
    "model_6": "profile_william",
    "model_7": "profile_anne",
}


def query_rag(input_text: str, character: str, limit: int = 3):
    if not _rag_enabled or not input_text.strip() or not _embed_model:
        return []

    client = _get_qdrant_client()
    if not client:
        return []

    query_vec = _embed_model.encode(input_text).tolist()
    collection_name = character_rag_mapping.get(character, "profile_adam")
    
    results = client.query(
        collection_name=collection_name,
        query_vector=query_vec,
        limit=limit,
    )
    return [
        {
            "text": r.payload.get("full_paragraph"),
            "score": r.score,
        }
        for r in results
        if r.payload.get("full_paragraph")
    ]


def generate_general_prompt(
    message: str,
    topic: str,
    use_mode: str,
    current_history: str,
    conversation_log: List[dict],
    character: Dict[str, Any],
    script: Dict[str, Any],
    language: str,
    rag_enabled: bool = False,
) -> str:
    lang = (language or "ENG").upper()
    language_directive = "Chinese." if lang == "CHN" else "English."
    character_identity = f"{character.get('name', 'Assistant')},{character.get('identity', '')}"
    identity = f"{character_identity}(Assistant is a human, not AI)"
    relevant_info = ""
    if rag_enabled:
        character_id = character.get("id", "")
        raw_results = query_rag(message, character_id, 3)
        formatted = [f"[{entry['score']:.2f}] {entry['text']}" for entry in raw_results if entry.get("score", 0) > 0.1]
        relevant_info = "\n".join(formatted)

    description = script.get("description", "")
    assistant_role = script.get("assistant_role", "")
    assistant_goal = script.get("assistant_goal", "")
    user_role = script.get("user_role", "")

    instructions = f"""
    Respond naturally and conversationally in spoken {language_directive}.
    Keep your responses concise and appropriate for voice conversation.
    IMPORTANT: Do NOT use any non-readable characters in your response, such as:
    - Parentheses: ( )
    - Square brackets: [ ]
    - Asterisks: *
    - Curly braces: {{ }}
    - Other special formatting characters
    Write only plain, readable text that can be spoken naturally. Use commas, periods, and question marks for punctuation only.
    """

    full_prompt = f"""
    Conversation Setting for User: {description}
    Assistant(You)'s Identity: {identity}
    Assistant(You)'s Role: {assistant_role}
    Assistant(You)'s Goal: {assistant_goal}
    Assistant(You)'s Background: {relevant_info}
    Recent Conversations: {conversation_log}
    Past Key Info: {current_history}
    Suggested Topic: {topic}
    User's Role: {user_role}
    User's Message: {message}
    Use_Mode: {use_mode}

    IMPORTANT: You must respond in {language_directive} only.

    Instructions: {instructions}
    Assistant_Response:"""
    return full_prompt


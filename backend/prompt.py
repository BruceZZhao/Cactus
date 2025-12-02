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

# Lazy loading for models - only import when needed
_SentenceTransformer = None
_QdrantLocal = None
_embed_model = None
SentenceTransformer_available = False
QdrantLocal_available = False

if _rag_enabled:
    try:
        from sentence_transformers import SentenceTransformer
        from qdrant_client.local.qdrant_local import QdrantLocal
        _SentenceTransformer = SentenceTransformer
        _QdrantLocal = QdrantLocal
        SentenceTransformer_available = True
        QdrantLocal_available = True
    except Exception:  # pragma: no cover
        SentenceTransformer_available = False
        QdrantLocal_available = False
        print("Warning: RAG enabled but sentence_transformers/qdrant not available")


def _get_embed_model():
    """Lazy load embedding model - only load when actually needed."""
    global _embed_model
    if _embed_model is None and _rag_enabled and SentenceTransformer_available and _SentenceTransformer:
        print("Loading embedding model (this may take a moment on first run)...")
        # Disable proxy to avoid SOCKS issues
        import os
        original_no_proxy = os.environ.get("NO_PROXY", "")
        original_no_proxy_lower = os.environ.get("no_proxy", "")
        try:
            os.environ["NO_PROXY"] = "*"
            os.environ["no_proxy"] = "*"
            _embed_model = _SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
            print("Embedding model loaded successfully.")
        finally:
            # Restore original proxy settings
            if original_no_proxy:
                os.environ["NO_PROXY"] = original_no_proxy
            else:
                os.environ.pop("NO_PROXY", None)
            if original_no_proxy_lower:
                os.environ["no_proxy"] = original_no_proxy_lower
            else:
                os.environ.pop("no_proxy", None)
    return _embed_model

_project_root = os.path.dirname(os.path.abspath(__file__))
_qdrant_client = None


def _get_qdrant_client():
    global _qdrant_client
    if not _rag_enabled or not QdrantLocal_available or not _QdrantLocal:
        return None
    if _qdrant_client is None:
        from backend.rag.qdrant_path import QDRANT_LOCATION
        location = os.getenv("CLEAN_QDRANT_LOCATION", QDRANT_LOCATION)
        try:
            _qdrant_client = _QdrantLocal(location=location)
        except Exception as exc:  # pragma: no cover
            error_msg = str(exc)
            # Retry if another instance is accessing
            if "already accessed" in error_msg.lower():
                try:
                    import time
                    time.sleep(0.1)
                    _qdrant_client = _QdrantLocal(location=location)
                except:
                    print(f"Warning: Could not initialize Qdrant client: {exc}")
            else:
                print(f"Warning: Could not initialize Qdrant client: {exc}")
    return _qdrant_client


character_rag_mapping = {
    "model_1": "default_profile",
}


def query_rag(input_text: str, character: str, limit: int = 3):
    """Query RAG database for character profile information."""
    if not _rag_enabled:
        print(f"[RAG] RAG not enabled globally")
        return []
    if not input_text.strip():
        print(f"[RAG] Empty input text")
        return []

    embed_model = _get_embed_model()
    if not embed_model:
        print(f"[RAG] Embed model not available")
        return []

    client = _get_qdrant_client()
    if not client:
        print(f"[RAG] Qdrant client not available")
        return []

    collection_to_query = character_rag_mapping.get(character)
    if not collection_to_query:
        print(f"[RAG] No collection mapping for character: {character}")
        return []

    try:
        print(f"[RAG] Searching collection: {collection_to_query}")
        query_vec = embed_model.encode(input_text).tolist()
        results = client.search(
            collection_name=collection_to_query,
            query_vector=query_vec,
            limit=limit
        )
        print(f"[RAG] Search returned {len(results)} results")
        return [
            {
                "text": r.payload.get("full_paragraph", ""),
                "score": r.score,
            }
            for r in results
            if r.payload.get("full_paragraph")
        ]
    except ValueError as e:
        # Collection not found if vector DB not built
        if "not found" in str(e).lower():
            print(f"[RAG] Collection {collection_to_query} not found. Please build vector database for this character.")
        else:
            print(f"[RAG] Query failed: {e}")
        return []
    except Exception as e:
        print(f"[RAG] Query failed: {e}")
        import traceback
        traceback.print_exc()
        return []


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
    custom_prompt: str = "",
) -> str:
    lang = (language or "ENG").upper()
    language_directive = "Chinese." if lang == "CHN" else "English."
    character_identity = f"{character.get('name', 'Assistant')},{character.get('identity', '')}"
    identity = f"{character_identity}(Assistant is a human, not AI)"
    relevant_info = ""
    if rag_enabled:
        character_id = character.get("id", "")
        print(f"[RAG] Querying for character: {character_id}, message: {message[:50]}")
        raw_results = query_rag(message, character_id, 3)
        print(f"[RAG] Found {len(raw_results)} results")
        threshold = 0.1
        formatted = [f"[{entry['score']:.2f}] {entry['text']}" for entry in raw_results if entry.get("score", 0) > threshold and entry.get("text")]
        relevant_info = "\n".join(formatted)
        if relevant_info:
            print(f"[RAG] Added background info ({len(relevant_info)} chars)")
        else:
            print(f"[RAG] No relevant info found (all scores below threshold or empty)")

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
    print("RAG RESULTS",relevant_info)

    # Apply custom prompt customization if provided
    if custom_prompt.strip():
        # Custom prompt can override or append to the base prompt
        # If it starts with "OVERRIDE:", replace the entire prompt structure
        if custom_prompt.strip().startswith("OVERRIDE:"):
            custom_content = custom_prompt.strip()[9:].strip()
            full_prompt = f"""{custom_content}

    User's Message: {message}
    Assistant_Response:"""
        else:
            # Otherwise, append custom instructions to the base prompt
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

    Custom Instructions: {custom_prompt}

    Instructions: {instructions}
    Assistant_Response:"""
    else:
        # Standard prompt without customization
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


def generate_thinker_prompt(character_history: str, new_logs: list) -> str:
    """Generate prompt for thinker agent to summarize conversation and suggest next topic."""
    summary_prompt = f"""
    You are a helpful assistant reasoning about ongoing conversations.

    Given:
    - History: {character_history}
    - New Logs: {new_logs}
    - User Score: N/A

    Instructions:
    1. Summarize the conversation between the user and the assistant so far.
    2. Make sure to identify their roles clearly and include any key names, numbers, and events.
    3. Suggest an interesting next long-term topic of conversation.

    IMPORTANT:
    - Return the result as a **valid JSON object only**
    - Do **not** include any explanation, extra text, or Markdown formatting like ```json

    Respond in **strict JSON format**, like this:
    {{
      "summary": "...",
      "next_topic": "..."
    }}
    """
    return summary_prompt


def generate_coach_prompt(new_logs: list) -> str:
    """Generate prompt for coach agent to provide teaching feedback."""
    summary_prompt = f"""
    You are a helpful English teacher.

    Recent: {new_logs[:-1] if len(new_logs) > 1 else []}
    Current: {new_logs[-1] if new_logs else {}}

    Based on what user said (do not comment on what assistant said), respond with:
    {{
      "type": "OK" | "WRONG",
      "original": "...",
      "correction": "...",
      "explanation": "..."
    }}
    """
    return summary_prompt


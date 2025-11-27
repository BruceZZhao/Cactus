"""Configuration settings for clean backend."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ASRConfig:
    api_key: str = os.getenv("GOOGLE_ASR_API_KEY", "")
    sample_rate: int = int(os.getenv("CLEAN_ASR_SAMPLE_RATE", "16000"))
    language: str = os.getenv("CLEAN_ASR_LANGUAGE", "en-US")
    frame_ms: int = int(os.getenv("CLEAN_FRAME_MS", "10"))


@dataclass
class LLMConfig:
    api_key: str = os.getenv("Google_LLM_API", "") or os.getenv("GOOGLE_LLM_API_KEY", "")
    model: str = os.getenv("CLEAN_LLM_MODEL", "models/gemini-2.5-flash")
    thinker_model: str = os.getenv("CLEAN_LLM_THINKER_MODEL", "models/gemini-2.5-flash")
    temperature: float = float(os.getenv("CLEAN_LLM_TEMPERATURE", "0.7"))
    max_output_tokens: int = int(os.getenv("CLEAN_LLM_MAX_TOKENS", "500"))


@dataclass
class TTSConfig:
    language_code: str = os.getenv("CLEAN_TTS_LANGUAGE", "en-US")
    voice: str = os.getenv("CLEAN_TTS_VOICE", "en-US-Neural2-D")


@dataclass
class RAGConfig:
    enabled: bool = os.getenv("CLEAN_RAG_ENABLED", "false").lower() == "true"


@dataclass
class Settings:
    asr: ASRConfig = None
    llm: LLMConfig = None
    tts: TTSConfig = None
    rag: RAGConfig = None
    
    def __post_init__(self):
        if self.asr is None:
            self.asr = ASRConfig()
        if self.llm is None:
            self.llm = LLMConfig()
        if self.tts is None:
            self.tts = TTSConfig()
        if self.rag is None:
            self.rag = RAGConfig()


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


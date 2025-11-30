"""Qdrant database path configuration."""
import os
import pathlib

QDRANT_LOCATION = os.getenv(
    "CLEAN_QDRANT_LOCATION",
    str(pathlib.Path(__file__).resolve().parents[1] / "rag" / "qdrant_data")
)


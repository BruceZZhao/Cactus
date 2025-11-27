"""Load character, script, and RAG data from static JSON files."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

_project_root = Path(__file__).resolve().parent
_data_dir = _project_root / "data"


def _load_json(filename: str) -> Dict[str, Any]:
    filepath = _data_dir / filename
    if not filepath.exists():
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def get_characters() -> Dict[str, Any]:
    """Load characters from data/characters.json."""
    return _load_json("characters.json")


def get_scripts() -> Dict[str, Any]:
    """Load scripts from data/scripts.json."""
    return _load_json("scripts.json")


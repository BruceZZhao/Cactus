"""Load default character and script data."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

_project_root = Path(__file__).resolve().parent
_data_dir = _project_root / "data"

# Default character and script IDs
DEFAULT_CHARACTER_ID = "model_1"
DEFAULT_SCRIPT_ID = "script_1"


def _load_json(filename: str) -> Dict[str, Any]:
    """Load JSON file from data directory."""
    filepath = _data_dir / filename
    if not filepath.exists():
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def get_default_character() -> Dict[str, Any]:
    """Get the default character (model_1 - Anne)."""
    characters = _load_json("characters.json")
    return characters.get(DEFAULT_CHARACTER_ID, {
        "id": DEFAULT_CHARACTER_ID,
        "name": "Anne",
        "identity": "A helpful teacher"
    })


def get_default_script() -> Dict[str, Any]:
    """Get the default script (script_1)."""
    scripts = _load_json("scripts.json")
    return scripts.get(DEFAULT_SCRIPT_ID, {
        "id": DEFAULT_SCRIPT_ID,
        "description": "A casual conversation",
        "assistant_role": "A friendly companion",
        "assistant_goal": "Have a natural, engaging conversation",
        "user_role": "A curious person"
    })


# Legacy functions for backward compatibility (deprecated)
def get_characters() -> Dict[str, Any]:
    """Deprecated: Use get_default_character() instead."""
    return {DEFAULT_CHARACTER_ID: get_default_character()}


def get_scripts() -> Dict[str, Any]:
    """Deprecated: Use get_default_script() instead."""
    return {DEFAULT_SCRIPT_ID: get_default_script()}


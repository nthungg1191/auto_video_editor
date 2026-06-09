"""Persist user settings to a JSON file next to the script."""

import json
import os
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent.parent / "settings.json"

DEFAULTS = {
    "bg_folder": "",
    "audio_folder": "",
    "srt_folder": "",
    "output_folder": "",
    "font_name": "Arial",
    "font_size": 40,
    "slow_min": 35.0,
    "slow_max": 45.0,
    "codec": "hevc_nvenc",
    "use_gpu": True,
    "subtitle_alignment": 2,
}


def load() -> dict:
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults so new keys always exist
            merged = {**DEFAULTS, **data}
            return merged
        except Exception:
            pass
    return dict(DEFAULTS)


def save(settings: dict):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Settings] Cannot save: {e}")
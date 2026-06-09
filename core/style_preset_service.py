"""
Style Preset Service — Phase 3.

Manages saving, loading, and applying subtitle style presets
to/from JSON files alongside the project.
"""

import json
from pathlib import Path
from typing import Optional

from core.subtitle_model import SubtitleStylePreset

PRESETS_DIR = Path(__file__).parent.parent / "presets"
PRESETS_FILE = PRESETS_DIR / "subtitle_presets.json"

DEFAULT_PRESETS = [
    SubtitleStylePreset(
        name="Mac dinh — Box den mo",
        font_name="Arial",
        font_size=40,
        font_color="#FFFFFF",
        stroke_color="#000000",
        stroke_width=2.0,
        stroke_enabled=True,
        bg_color="#000000",
        bg_opacity=0.6,
        bg_padding_x=12,
        bg_padding_y=4,
        bg_corner_radius=4,
        bg_enabled=True,
        alignment=2,
        margin_v=50,
        margin_l=20,
        margin_r=20,
    ),
    SubtitleStylePreset(
        name="Sang — Text dam",
        font_name="Arial",
        font_size=36,
        font_color="#FFFF00",
        stroke_color="#000000",
        stroke_width=1.5,
        stroke_enabled=True,
        bg_color="#000000",
        bg_opacity=0.8,
        bg_padding_x=4,
        bg_padding_y=4,
        bg_corner_radius=4,
        bg_enabled=True,
        alignment=2,
        margin_v=80,
        margin_l=20,
        margin_r=20,
    ),
    SubtitleStylePreset(
        name="To — Hieu ung kich thuoc lon",
        font_name="Arial",
        font_size=60,
        font_color="#FFFFFF",
        stroke_color="#000000",
        stroke_width=2.5,
        stroke_enabled=True,
        bg_color="#000000",
        bg_opacity=0.7,
        bg_padding_x=16,
        bg_padding_y=6,
        bg_corner_radius=6,
        bg_enabled=True,
        alignment=2,
        margin_v=60,
        margin_l=30,
        margin_r=30,
    ),
]


class StylePresetService:

    @staticmethod
    def ensure_presets_dir():
        PRESETS_DIR.mkdir(exist_ok=True)

    # -------------------------------------------------------------------------
    # Load / save
    # -------------------------------------------------------------------------

    @classmethod
    def load_all(cls) -> list[SubtitleStylePreset]:
        cls.ensure_presets_dir()
        if not PRESETS_FILE.exists():
            cls._write_default_presets()
            return list(DEFAULT_PRESETS)

        try:
            with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            presets = [SubtitleStylePreset.from_dict(p) for p in data]
            return presets
        except Exception:
            return list(DEFAULT_PRESETS)

    @classmethod
    def save_all(cls, presets: list[SubtitleStylePreset]):
        cls.ensure_presets_dir()
        data = [p.to_dict() for p in presets]
        with open(PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def add_preset(cls, preset: SubtitleStylePreset) -> list[SubtitleStylePreset]:
        presets = cls.load_all()
        presets.append(preset)
        cls.save_all(presets)
        return presets

    @classmethod
    def delete_preset(cls, name: str) -> list[SubtitleStylePreset]:
        presets = [p for p in cls.load_all() if p.name != name]
        cls.save_all(presets)
        return presets

    @classmethod
    def find_preset(cls, name: str) -> Optional[SubtitleStylePreset]:
        for p in cls.load_all():
            if p.name == name:
                return p
        return None

    # -------------------------------------------------------------------------
    # Export / import to JSON file (for sharing / project)
    # -------------------------------------------------------------------------

    @staticmethod
    def export_preset(preset: SubtitleStylePreset, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(preset.to_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def import_preset(path: str) -> SubtitleStylePreset:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return SubtitleStylePreset.from_dict(data)

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    @classmethod
    def _write_default_presets(cls):
        cls.ensure_presets_dir()
        data = [p.to_dict() for p in DEFAULT_PRESETS]
        with open(PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

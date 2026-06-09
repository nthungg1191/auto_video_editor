"""
Data models for subtitle editing.

SubtitleEntry  — a single subtitle cue (index, start, end, text).
SubtitleDocument — a collection of entries from one SRT file.
SubtitleStylePreset — a named style configuration saved as JSON.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SubtitleEntry:
    """A single subtitle entry from an SRT file."""
    index: int
    start_time: str  # "HH:MM:SS,mmm"
    end_time: str    # "HH:MM:SS,mmm"
    text: str

    def start_ms(self) -> int:
        return _srt_to_ms(self.start_time)

    def end_ms(self) -> int:
        return _srt_to_ms(self.end_time)

    def duration_ms(self) -> int:
        return self.end_ms() - self.start_ms()

    def set_start_ms(self, ms: int):
        self.start_time = _ms_to_srt(ms)

    def set_end_ms(self, ms: int):
        self.end_time = _ms_to_srt(ms)

    def shift_ms(self, delta_ms: int):
        """Shift both start and end by delta_ms milliseconds."""
        self.set_start_ms(max(0, self.start_ms() + delta_ms))
        self.set_end_ms(max(0, self.end_ms() + delta_ms))


@dataclass
class SubtitleDocument:
    """All subtitle entries from a single SRT file."""
    file_path: str
    entries: list[SubtitleEntry] = field(default_factory=list)
    dirty: bool = False

    @property
    def name(self) -> str:
        return Path(self.file_path).stem

    def save(self):
        from core.srt_service import SrtService
        SrtService.write(self.file_path, self.entries)
        self.dirty = False

    def reload(self):
        from core.srt_service import SrtService
        self.entries = SrtService.parse(self.file_path)
        self.dirty = False


@dataclass
class SubtitleStylePreset:
    """A named, reusable subtitle style configuration."""

    name: str
    font_name: str = "Arial"
    font_size: int = 40

    # ---- Fill ----
    font_color: str = "#FFFFFF"      # hex RGB

    # ---- Stroke / Outline ----
    stroke_color: str = "#000000"    # hex RGB
    stroke_width: float = 2.0        # pixels
    stroke_enabled: bool = True

    # ---- Background box ----
    bg_color: str = "#000000"        # hex RGB
    bg_opacity: float = 0.6          # 0.0 – 1.0
    bg_padding_x: int = 8            # horizontal inner padding
    bg_padding_y: int = 4            # vertical inner padding
    bg_corner_radius: int = 4        # pixels (rounded corners)
    bg_enabled: bool = True

    # ---- Shadow ----
    shadow_color: str = "#000000"    # hex RGB
    shadow_opacity: float = 0.8
    shadow_angle: float = 45.0       # degrees (clockwise from top)
    shadow_distance: float = 3.0     # pixels
    shadow_blur: float = 2.0        # pixels
    shadow_enabled: bool = False

    # ---- Layout ----
    alignment: int = 2               # SSA alignment code (2 = bottom-center)
    margin_v: int = 50
    margin_l: int = 20
    margin_r: int = 20

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "font_name": self.font_name,
            "font_size": self.font_size,
            "font_color": self.font_color,
            "stroke_color": self.stroke_color,
            "stroke_width": self.stroke_width,
            "stroke_enabled": self.stroke_enabled,
            "bg_color": self.bg_color,
            "bg_opacity": self.bg_opacity,
            "bg_padding_x": self.bg_padding_x,
            "bg_padding_y": self.bg_padding_y,
            "bg_corner_radius": self.bg_corner_radius,
            "bg_enabled": self.bg_enabled,
            "shadow_color": self.shadow_color,
            "shadow_opacity": self.shadow_opacity,
            "shadow_angle": self.shadow_angle,
            "shadow_distance": self.shadow_distance,
            "shadow_blur": self.shadow_blur,
            "shadow_enabled": self.shadow_enabled,
            "alignment": self.alignment,
            "margin_v": self.margin_v,
            "margin_l": self.margin_l,
            "margin_r": self.margin_r,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SubtitleStylePreset":
        return cls(
            name=data.get("name", "Unnamed"),
            font_name=data.get("font_name", "Arial"),
            font_size=data.get("font_size", 40),
            font_color=data.get("font_color", "#FFFFFF"),
            stroke_color=data.get("stroke_color", "#000000"),
            stroke_width=data.get("stroke_width", 2.0),
            stroke_enabled=data.get("stroke_enabled", True),
            bg_color=data.get("bg_color", "#000000"),
            bg_opacity=data.get("bg_opacity", 0.6),
            bg_padding_x=data.get("bg_padding_x", 8),
            bg_padding_y=data.get("bg_padding_y", 4),
            bg_corner_radius=data.get("bg_corner_radius", 4),
            bg_enabled=data.get("bg_enabled", True),
            shadow_color=data.get("shadow_color", "#000000"),
            shadow_opacity=data.get("shadow_opacity", 0.8),
            shadow_angle=data.get("shadow_angle", 45.0),
            shadow_distance=data.get("shadow_distance", 3.0),
            shadow_blur=data.get("shadow_blur", 2.0),
            shadow_enabled=data.get("shadow_enabled", False),
            alignment=data.get("alignment", 2),
            margin_v=data.get("margin_v", 50),
            margin_l=data.get("margin_l", 20),
            margin_r=data.get("margin_r", 20),
        )

    def to_ass_color(self, hex_color: str, alpha: float = 1.0) -> str:
        """Convert hex RGB + opacity to ASS color string &HAABBGGRR."""
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        a = int((1.0 - alpha) * 255)
        return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _srt_to_ms(timestamp: str) -> int:
    """Convert SRT timestamp 'HH:MM:SS,mmm' to milliseconds."""
    parts = timestamp.replace(",", ":").split(":")
    h, m, s, ms = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return (h * 3600 + m * 60 + s) * 1000 + ms


def _ms_to_srt(ms: int) -> str:
    """Convert milliseconds to SRT timestamp 'HH:MM:SS,mmm'."""
    ms = max(0, ms)
    total_s = ms // 1000
    ms = ms % 1000
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

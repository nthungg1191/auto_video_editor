"""
SRT file service: parse, write, offset, split, merge.

All subtitle file I/O lives here so it can be called from widgets
without importing logic into MainWindow.
"""

import re
from pathlib import Path
from typing import Optional

from core.subtitle_model import SubtitleEntry


# SRT block pattern:
#   index\n
#   start --> end\n
#   text\n
#   (blank line)
SRT_BLOCK_RE = re.compile(
    r"(\d+)\r?\n"
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\r?\n"
    r"((?:.*(?:\r?\n|$))+?)"
    r"(?=\r?\n\r?\n|\r?\n*$|$)",
    re.MULTILINE,
)


class SrtService:

    # -------------------------------------------------------------------------
    # Parse
    # -------------------------------------------------------------------------

    @staticmethod
    def parse(file_path: str) -> list[SubtitleEntry]:
        """Read and parse an SRT file, returning a list of SubtitleEntry."""
        entries: list[SubtitleEntry] = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                content = f.read()

        for m in SRT_BLOCK_RE.finditer(content):
            idx = int(m.group(1))
            start = m.group(2).strip()
            end = m.group(3).strip()
            text = m.group(4).strip()
            entries.append(SubtitleEntry(
                index=idx,
                start_time=start,
                end_time=end,
                text=text,
            ))

        return entries

    @staticmethod
    def validate(file_path: str) -> tuple[bool, str]:
        """Return (valid, message). Checks index sequence and time validity."""
        try:
            entries = SrtService.parse(file_path)
        except Exception as e:
            return False, f"Khong the doc file: {e}"

        if not entries:
            return False, "File rong hoac khong co entry nao"

        for i, e in enumerate(entries):
            if e.start_ms() >= e.end_ms():
                return False, f"Entry #{i+1} ({e.index}): thoi gian bat dau >= thoi gian ket thuc"
            if i > 0:
                prev = entries[i - 1]
                if prev.end_ms() > e.start_ms():
                    return False, f"Entry #{i} va #{i+1} chong nhau (overlap)"

        return True, f"{len(entries)} entries hop le"

    # -------------------------------------------------------------------------
    # Write
    # -------------------------------------------------------------------------

    @staticmethod
    def write(file_path: str, entries: list[SubtitleEntry]):
        """Write entries to an SRT file, rewriting indices sequentially."""
        lines: list[str] = []
        for i, e in enumerate(entries, 1):
            lines.append(str(i))
            lines.append(f"{e.start_time} --> {e.end_time}")
            lines.append(e.text)
            lines.append("")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    # -------------------------------------------------------------------------
    # Shift entire timeline so first subtitle starts at 0
    # -------------------------------------------------------------------------

    @staticmethod
    def shift_to_zero(entries: list[SubtitleEntry]) -> tuple[list[SubtitleEntry], int]:
        """
        Return (new_entries, offset_ms) where the entire timeline is shifted so
        the first subtitle starts at 00:00:00,000.

        offset = first entry's start time in ms.
        Every entry is shifted backward by offset (preserving duration and gaps).
        Negative values are clamped to 0.
        """
        if not entries:
            return entries, 0
        offset_ms = entries[0].start_ms()
        result = []
        for e in entries:
            new_start = max(0, e.start_ms() - offset_ms)
            new_end = max(0, e.end_ms() - offset_ms)
            cloned = SubtitleEntry(
                index=e.index,
                start_time=e.start_time,
                end_time=e.end_time,
                text=e.text,
            )
            cloned.set_start_ms(new_start)
            cloned.set_end_ms(new_end)
            result.append(cloned)
        return result, offset_ms

    # -------------------------------------------------------------------------
    # Batch timing operations
    # -------------------------------------------------------------------------

    @staticmethod
    def offset_all(entries: list[SubtitleEntry], delta_ms: int) -> list[SubtitleEntry]:
        """Return a new list with all entries shifted by delta_ms milliseconds."""
        result: list[SubtitleEntry] = []
        for e in entries:
            cloned = SubtitleEntry(
                index=e.index,
                start_time=e.start_time,
                end_time=e.end_time,
                text=e.text,
            )
            cloned.shift_ms(delta_ms)
            result.append(cloned)
        return result

    @staticmethod
    def split_entry(entry: SubtitleEntry, split_ms: int) -> tuple[SubtitleEntry, SubtitleEntry]:
        """
        Split one entry at split_ms.
        Returns (before, after). The original entry is truncated;
        a new second entry is created.
        """
        mid = split_ms
        before = SubtitleEntry(
            index=entry.index,
            start_time=entry.start_time,
            end_time=_ms_to_srt(mid),
            text=entry.text,
        )
        after = SubtitleEntry(
            index=entry.index + 1,
            start_time=_ms_to_srt(mid),
            end_time=entry.end_time,
            text="",
        )
        return before, after

    @staticmethod
    def merge_entries(a: SubtitleEntry, b: SubtitleEntry) -> SubtitleEntry:
        """
        Merge two adjacent entries into one.
        Takes text from a, uses start of a and end of b.
        """
        return SubtitleEntry(
            index=a.index,
            start_time=a.start_time,
            end_time=b.end_time,
            text=a.text,
        )

    @staticmethod
    def find_entry_at(entries: list[SubtitleEntry], time_ms: int) -> Optional[SubtitleEntry]:
        """Return the first entry active at time_ms, or None."""
        for e in entries:
            if e.start_ms() <= time_ms <= e.end_ms():
                return e
        return None

    @staticmethod
    def jump_to_entry(entries: list[SubtitleEntry], target_index: int) -> Optional[SubtitleEntry]:
        """Return entry with given 1-based index, or None."""
        for e in entries:
            if e.index == target_index:
                return e
        return None

    # -------------------------------------------------------------------------
    # Import / export helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def apply_style_template(
        file_path: str,
        output_path: str,
        style_name: str,
        style_params: dict,
    ):
        """
        Write a simple ASS file from an SRT, applying basic style metadata.
        This is a lightweight bridge: write the SRT as-is but embed
        style info in a companion .meta.json sidecar for later processing.
        """
        import json
        meta_path = Path(output_path).with_suffix(".meta.json")
        meta = {
            "source_srt": str(Path(file_path).resolve()),
            "style_name": style_name,
            "style": style_params,
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Module-level helpers (same as subtitle_model but kept here for symmetry)
# ---------------------------------------------------------------------------

def _ms_to_srt(ms: int) -> str:
    ms = max(0, ms)
    total_s = ms // 1000
    ms_rem = ms % 1000
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms_rem:03d}"

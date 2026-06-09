"""
Main window for Auto Video Editor.
Layout (3-panel horizontal):
  Left   — folder pickers + file pair table
  Middle — subtitle style controls + preview
  Right  — render settings + FFmpeg log + render controls
"""

import json
import os
import sys
from pathlib import Path

# Ensure project root is on the path whether this file is run directly
# (python ui/main_window.py) or imported from main.py
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFileDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QPlainTextEdit, QProgressBar, QSplitter, QCheckBox,
    QSizePolicy, QSlider, QMessageBox, QStatusBar,
    QFrame, QGridLayout, QAbstractItemView
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QFont, QIcon, QImage

from core.video_processor import RenderConfig, SubtitleStyle, FilePair, build_pairs, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS
from core.worker import RenderWorker
from core.subtitle_model import SubtitleStylePreset
from core.srt_service import SrtService
from core.style_preset_service import StylePresetService
from core.subtitle_model import SubtitleEntry
from ui.subtitle_preview_widget import SubtitlePreviewWidget, SubtitleStyleEditor
from utils import settings as cfg
from utils.gpu_detect import detect_gpu, detect_system_info, check_ffmpeg, check_ffprobe

EXPORT_PATH = Path(__file__).parent.parent / "selections.json"
DEBUG_LOG_PATH = Path(__file__).parent.parent / "debug_ui.log"
HARDCODED_AUDIO_DIR = r"D:\TBN 1\video goc"
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

FONTS_AVAILABLE = [
    "Arial", "Arial Bold", "Roboto", "Open Sans",
    "Montserrat", "Noto Sans", "Verdana", "Tahoma",
    "Georgia", "Times New Roman", "Courier New"
]

CODECS = [
    ("H.265 HEVC — GPU (NVENC)", "hevc_nvenc"),
    ("H.264 AVC  — GPU (NVENC)", "h264_nvenc"),
    ("H.265 HEVC — CPU (libx265)", "libx265"),
    ("H.264 AVC  — CPU (libx264)", "libx264"),
]

ALIGNMENTS = [
    ("Giữa màn hình (khuyến nghị)", 10),
    ("Dưới giữa (chuẩn phụ đề)", 2),
    ("Trên giữa", 6),
]


class FolderPicker(QWidget):
    """A label + line edit + browse button row."""

    def __init__(self, label: str, placeholder: str = "", parent=None):
        super().__init__(parent)
        self._mode = "folder"
        self._selected_files: list[str] = []
        self._file_filter = "All files (*.*)"
        self._dialog_title = "Chọn file"

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.lbl = QLabel(label)
        self.lbl.setFixedWidth(110)
        self.lbl.setStyleSheet("font-size: 13px;")

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setReadOnly(True)
        self.edit.setStyleSheet("font-size: 12px;")

        self.btn = QPushButton("Chọn…")
        self.btn.setFixedWidth(64)
        self.btn.setStyleSheet("font-size: 12px;")
        self.btn.clicked.connect(self._browse)

        lay.addWidget(self.lbl)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.btn)

    def set_mode(self, mode: str):
        self._mode = mode
        if mode == "files":
            self._selected_files = []

    def set_file_dialog(self, dialog_title: str, file_filter: str):
        self._dialog_title = dialog_title
        self._file_filter = file_filter

    def _browse(self):
        current = self.edit.text() or os.path.expanduser("~")
        if self._mode == "files":
            if self._selected_files:
                current = str(Path(self._selected_files[0]).parent)
            elif current and Path(current).exists() and Path(current).is_file():
                current = str(Path(current).parent)
            files, _ = QFileDialog.getOpenFileNames(
                self,
                self._dialog_title,
                current,
                self._file_filter
            )
            if files:
                self._selected_files = files
                if len(files) == 1:
                    self.edit.setText(Path(files[0]).name)
                else:
                    self.edit.setText(f"Đã chọn {len(files)} file")
                if hasattr(self, "_callback"):
                    self._callback(files)
            return

        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục", current)
        if folder:
            self.edit.setText(folder)
            if hasattr(self, "_callback"):
                self._callback(folder)

    def set_callback(self, fn):
        self._callback = fn

    def value(self) -> str:
        return self.edit.text()

    def set_value(self, v: str):
        self.edit.setText(v)

    def selected_files(self) -> list[str]:
        return list(self._selected_files)

    def set_selected_files(self, files: list[str]):
        self._selected_files = list(files)
        if not files:
            self.edit.clear()
        elif len(files) == 1:
            self.edit.setText(Path(files[0]).name)
        else:
            self.edit.setText(f"Đã chọn {len(files)} file")


class PairTable(QTableWidget):
    """Table showing matched audio↔SRT file pairs."""

    COLS = ["#", "Audio file", "SRT file", "Trạng thái"]

    def __init__(self, parent=None):
        super().__init__(0, len(self.COLS), parent)
        self.setHorizontalHeaderLabels(self.COLS)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 40)
        self.setColumnWidth(3, 100)
        self.setStyleSheet("font-size: 12px;")

    def load_pairs(self, pairs: list[FilePair]):
        self.setRowCount(0)
        for pair in pairs:
            row = self.rowCount()
            self.insertRow(row)
            self.setItem(row, 0, self._cell(pair.index, center=True))
            self.setItem(row, 1, self._cell(Path(pair.audio_path).name if pair.audio_path else "—"))
            self.setItem(row, 2, self._cell(Path(pair.srt_path).name if pair.srt_path else "—"))
            status_text = "✓ Khớp" if pair.matched else f"✗ {pair.error}"
            status_item = self._cell(status_text, center=True)
            if pair.matched:
                status_item.setForeground(QColor("#16a34a"))
            else:
                status_item.setForeground(QColor("#dc2626"))
            self.setItem(row, 3, status_item)

    @staticmethod
    def _cell(text: str, center: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if center:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_video_frame(video_path: str, timestamp: str | None = None) -> QImage | None:
    """
    Extract a single frame from a video file using ffmpeg.
    Returns a QImage, or None on failure.
    Uses the middle of the video by default (more representative than start).
    """
    import subprocess, tempfile, os
    if not os.path.exists(video_path):
        return None

    try:
        if timestamp is None:
            probe_result = subprocess.run(
                ["ffprobe", "-v", "error",
                 "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1",
                 video_path],
                capture_output=True, text=True, timeout=10,
            )
            try:
                duration = float(probe_result.stdout.strip())
                timestamp = max(1.0, duration / 2)
            except (ValueError, OSError):
                timestamp = 5.0

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            tmp_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 or not os.path.exists(tmp_path):
            return None

        img = QImage(tmp_path)
        os.unlink(tmp_path)
        return img if not img.isNull() else None
    except Exception:
        return None


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Auto Video Editor")
        self.setMinimumSize(1100, 720)
        self.resize(1280, 800)

        self._settings = cfg.load()
        self._pairs: list[FilePair] = []
        self._worker: RenderWorker | None = None
        self._sys_info = detect_system_info()
        self._presets: list[SubtitleStylePreset] = []
        self._active_preset: SubtitleStylePreset | None = None
        self._timing_undo: dict[str, list[SubtitleEntry]] = {}  # path → original entries

        self._build_ui()
        self._apply_saved_settings()
        self._check_deps()
        self._log_debug("MainWindow initialized")

    def _log_debug(self, message: str):
        line = f"[DEBUG] {message}"
        try:
            with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        if hasattr(self, "log_text"):
            self.log_text.appendPlainText(line)

    def _resolve_hardcoded_media_files(self) -> list[str]:
        source_dir = Path(HARDCODED_AUDIO_DIR)
        self._log_debug(f"Checking hardcoded source dir: {source_dir}")
        if not source_dir.exists():
            self._log_debug("Hardcoded source dir does not exist")
            return []
        if not source_dir.is_dir():
            self._log_debug("Hardcoded source path is not a directory")
            return []

        all_files = sorted([path for path in source_dir.iterdir() if path.is_file()], key=lambda path: path.name.lower())
        self._log_debug(f"Found {len(all_files)} total files in hardcoded dir")

        ext_counts: dict[str, int] = {}
        for path in all_files:
            ext = path.suffix.lower() or "<no_ext>"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
        for ext, count in sorted(ext_counts.items(), key=lambda item: (-item[1], item[0])):
            self._log_debug(f"Extension summary: {ext} -> {count}")

        media_files = [str(path) for path in all_files if path.suffix.lower() in MEDIA_EXTENSIONS]
        self._log_debug(f"Found {len(media_files)} supported media files in hardcoded dir")
        for path in media_files[:20]:
            self._log_debug(f"Media file: {path}")
        return media_files

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_lay = QVBoxLayout(central)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # --- Title bar ---
        title_bar = self._make_title_bar()
        root_lay.addWidget(title_bar)

        # --- 3-panel horizontal splitter ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        left   = self._build_left_panel()    # file selection
        middle = self._build_middle_panel()  # subtitle style + preview
        right  = self._build_right_panel()   # render + log + controls

        splitter.addWidget(left)
        splitter.addWidget(middle)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([420, 280, 420])

        root_lay.addWidget(splitter, 1)

        # Status bar
        self.statusBar().showMessage("Sẵn sàng")

    def _make_title_bar(self) -> QWidget:
        si = self._sys_info
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet("background: #1e1e2e; border-bottom: 1px solid #333;")

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        # App identity
        icon_lbl = QLabel("▶")
        icon_lbl.setStyleSheet("color: #60a5fa; font-size: 18px;")
        title_lbl = QLabel("Auto Video Editor ")
        title_lbl.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: 600;")
        lay.addWidget(icon_lbl)
        lay.addWidget(title_lbl)
        lay.addSpacing(16)

        title_lbl = QLabel("Author: G.Thịnh ")
        title_lbl.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: 600;")
        lay.addWidget(title_lbl)
        lay.addSpacing(16)
        
        # CPU badge
        self._cpu_lbl = QLabel(f"CPU: {si['cpu_name']}")
        self._cpu_lbl.setStyleSheet(
            "color: #93c5fd; font-size: 11px; "
            "background: #1e293b; border-radius: 4px; padding: 3px 8px; "
            "border: 1px solid #334155;"
        )
        lay.addWidget(self._cpu_lbl)

        # RAM badge
        self._ram_lbl = QLabel(f"RAM: {si['ram_free_gb']:.1f}/{si['ram_total_gb']:.1f} GB")
        self._ram_lbl.setStyleSheet(
            "color: #86efac; font-size: 11px; "
            "background: #1a2e1a; border-radius: 4px; padding: 3px 8px; "
            "border: 1px solid #22543d;"
        )
        lay.addWidget(self._ram_lbl)

        # GPU badge
        gpu_ok = si["gpu_available"]
        gpu_color = "#4ade80" if gpu_ok else "#f87171"
        gpu_bg = "#1a2e1a" if gpu_ok else "#2e1a1a"
        gpu_border = "#22543d" if gpu_ok else "#742a2a"
        self._gpu_lbl = QLabel(f"GPU: {si['gpu_name']}")
        if gpu_ok:
            self._gpu_lbl.setText(f"GPU: {si['gpu_name']}  VRAM: {si['vram_free_mb']}/{si['vram_total_mb']} MB")
        self._gpu_lbl.setStyleSheet(
            f"color: {gpu_color}; font-size: 11px; "
            f"background: {gpu_bg}; border-radius: 4px; padding: 3px 8px; "
            f"border: 1px solid {gpu_border};"
        )
        lay.addWidget(self._gpu_lbl)

        # Power badge (only if GPU available)
        self._pwr_lbl = None
        if gpu_ok and si["gpu_power_w"] != "—":
            self._pwr_lbl = QLabel(f"{si['gpu_power_w']}")
            self._pwr_lbl.setStyleSheet(
                "color: #fbbf24; font-size: 11px; "
                "background: #2e2500; border-radius: 4px; padding: 3px 8px; "
                "border: 1px solid #78350f;"
            )
            lay.addWidget(self._pwr_lbl)

        lay.addStretch()

        # Realtime refresh timer (every 3 s)
        from PyQt6.QtCore import QTimer
        self._sysinfo_timer = QTimer(self)
        self._sysinfo_timer.timeout.connect(self._update_sysinfo)
        self._sysinfo_timer.start(3000)

        return bar

    def _update_sysinfo(self):
        """Refresh system-info badges in the title bar."""
        si = detect_system_info()

        # CPU — name doesn't change, skip
        # RAM
        self._ram_lbl.setText(f"RAM: {si['ram_free_gb']:.1f}/{si['ram_total_gb']:.1f} GB")

        # VRAM
        if si["gpu_available"]:
            self._gpu_lbl.setText(
                f"GPU: {si['gpu_name']}  VRAM: {si['vram_free_mb']}/{si['vram_total_mb']} MB"
            )
            if self._pwr_lbl and si["gpu_power_w"] != "—":
                self._pwr_lbl.setText(si["gpu_power_w"])

    # ---- Left panel ----

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet("background: #fafafa;")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # Folder pickers group
        grp_folders = QGroupBox("📁  Thư mục")
        grp_folders.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        f_lay = QVBoxLayout(grp_folders)
        f_lay.setSpacing(6)

        self.pick_bg = FolderPicker("Video nền:", "Chọn file video nền")
        self.pick_audio = FolderPicker("Nguồn media:", "Chọn file video/audio nguồn")
        self.pick_srt = FolderPicker("Subtitle SRT:", "Chọn thư mục chứa file .srt")
        self.pick_output = FolderPicker("Output:", "Chọn thư mục xuất video")

        self.pick_bg.set_mode("files")
        self.pick_audio.set_mode("files")
        self.pick_srt.set_mode("files")
        self.pick_bg.set_file_dialog(
            "Chọn file video nền",
            "Video files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v);;All files (*.*)"
        )
        self.pick_srt.set_file_dialog(
            "Chọn file phụ đề",
            "Subtitle files (*.srt);;All files (*.*)"
        )
        self.pick_bg.btn.setText("Chọn file…")
        self.pick_audio.btn.setText("Chọn file…")
        self.pick_srt.btn.setText("Chọn file…")

        self.pick_bg.set_callback(self._on_file_selection_change)
        self.pick_audio.set_callback(self._on_file_selection_change)
        self.pick_srt.set_callback(self._on_file_selection_change)

        for w in [self.pick_bg, self.pick_audio, self.pick_srt, self.pick_output]:
            f_lay.addWidget(w)

        self.btn_refresh = QPushButton("🔄  Quét lại file")
        self.btn_refresh.clicked.connect(self._scan_pairs)
        self.btn_refresh.setStyleSheet("font-size: 12px;")
        f_lay.addWidget(self.btn_refresh)

        pair_hint = QLabel(
            "Chọn thủ công danh sách audio và SRT; tool sẽ ghép 2 danh sách theo đúng thứ tự bạn chọn."
        )
        pair_hint.setWordWrap(True)
        pair_hint.setStyleSheet("font-size: 11px; color: #6b7280;")
        f_lay.addWidget(pair_hint)

        lay.addWidget(grp_folders)

        # File pairs table
        grp_pairs = QGroupBox("📋  Danh sách file (audio ↔ SRT)")
        grp_pairs.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        p_lay = QVBoxLayout(grp_pairs)
        self.pair_table = PairTable()
        p_lay.addWidget(self.pair_table)

        self.lbl_pair_summary = QLabel("Chưa quét")
        self.lbl_pair_summary.setStyleSheet("font-size: 11px; color: #6b7280;")
        p_lay.addWidget(self.lbl_pair_summary)

        lay.addWidget(grp_pairs, 1)
        return panel

    # ---- Middle panel — Subtitle Style + Preview ----

    def _build_middle_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet("background: #fafafa;")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # --- Subtitle style editor (built-in preview) ---
        grp_style = QGroupBox("💬  Subtitle Style")
        grp_style.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        style_lay = QVBoxLayout(grp_style)
        self.style_panel = SubtitleStyleEditor()
        style_lay.addWidget(self.style_panel)
        lay.addWidget(grp_style)

        # --- Preset controls ---
        grp_preset = QGroupBox("Preset Style")
        grp_preset.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        pst_lay = QHBoxLayout(grp_preset)
        pst_lay.setSpacing(6)
        self.cmb_preset = QComboBox()
        self.cmb_preset.setStyleSheet("font-size: 12px;")
        self.cmb_preset.currentIndexChanged.connect(self._on_preset_changed)
        pst_lay.addWidget(self.cmb_preset, 1)
        self.btn_save_preset = QPushButton("Lưu preset")
        self.btn_save_preset.setFixedWidth(80)
        self.btn_save_preset.setStyleSheet("font-size: 11px;")
        self.btn_save_preset.clicked.connect(self._on_save_preset)
        pst_lay.addWidget(self.btn_save_preset)
        self.btn_apply_to_all = QPushButton("Áp toàn bộ")
        self.btn_apply_to_all.setFixedWidth(80)
        self.btn_apply_to_all.setStyleSheet("font-size: 11px;")
        self.btn_apply_to_all.clicked.connect(self._on_apply_style_to_all)
        pst_lay.addWidget(self.btn_apply_to_all)
        self.btn_refresh_frame = QPushButton("🔄 Frame")
        self.btn_refresh_frame.setFixedWidth(75)
        self.btn_refresh_frame.setStyleSheet("font-size: 11px;")
        self.btn_refresh_frame.setToolTip("Extract a frame from the first video as preview background")
        self.btn_refresh_frame.clicked.connect(self._on_refresh_preview_frame)
        pst_lay.addWidget(self.btn_refresh_frame)
        lay.addWidget(grp_preset)

        lay.addStretch()
        return panel

    # ---- Right panel — Render + Log + Controls ----

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # --- Render settings ---
        grp_render = QGroupBox("⚙️  Cài đặt Render")
        grp_render.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        r_lay = QGridLayout(grp_render)
        r_lay.setSpacing(8)

        r_lay.addWidget(QLabel("Codec xuất:"), 0, 0)
        self.cmb_codec = QComboBox()
        for label, _ in CODECS:
            self.cmb_codec.addItem(label)
        r_lay.addWidget(self.cmb_codec, 0, 1, 1, 3)

        r_lay.addWidget(QLabel("Tốc độ chậm min (%):"), 1, 0)
        self.spn_slow_min = QDoubleSpinBox()
        self.spn_slow_min.setRange(10, 80)
        self.spn_slow_min.setValue(35.0)
        self.spn_slow_min.setSingleStep(1.0)
        r_lay.addWidget(self.spn_slow_min, 1, 1)

        r_lay.addWidget(QLabel("Tốc độ chậm max (%):"), 1, 2)
        self.spn_slow_max = QDoubleSpinBox()
        self.spn_slow_max.setRange(10, 80)
        self.spn_slow_max.setValue(45.0)
        self.spn_slow_max.setSingleStep(1.0)
        r_lay.addWidget(self.spn_slow_max, 1, 3)

        slow_hint = QLabel(
            "ℹ️  Ví dụ: 40% = video nền chạy chậm 40% so với gốc (output dài bằng audio)"
        )
        slow_hint.setStyleSheet("font-size: 11px; color: #6b7280;")
        r_lay.addWidget(slow_hint, 2, 0, 1, 4)
        lay.addWidget(grp_render)

        # --- Timing Tools ---
        grp_timing = QGroupBox("⏱  Timing Tools")
        grp_timing.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        timing_lay = QHBoxLayout(grp_timing)
        timing_lay.setSpacing(6)

        self.btn_first_to_zero = QPushButton("⏮  Shift To 0s")
        self.btn_first_to_zero.setFixedWidth(130)
        self.btn_first_to_zero.setStyleSheet("font-size: 11px;")
        self.btn_first_to_zero.setToolTip(
            "Shift the entire subtitle timeline so the first subtitle starts at 0s."
        )
        self.btn_first_to_zero.clicked.connect(self._on_first_sub_to_zero)
        timing_lay.addWidget(self.btn_first_to_zero)

        self.btn_undo_timing = QPushButton("↩  Undo")
        self.btn_undo_timing.setFixedWidth(65)
        self.btn_undo_timing.setStyleSheet("font-size: 11px;")
        self.btn_undo_timing.setToolTip("Undo the last timing change.")
        self.btn_undo_timing.setEnabled(False)
        self.btn_undo_timing.clicked.connect(self._on_undo_timing)
        timing_lay.addWidget(self.btn_undo_timing)

        timing_lay.addStretch()
        lay.addWidget(grp_timing)

        # --- FFmpeg log ---
        grp_log = QGroupBox("📝  Log FFmpeg")
        grp_log.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        log_lay = QVBoxLayout(grp_log)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(500)
        self.log_text.setStyleSheet(
            "background: #111827; color: #d1fae5; font-family: monospace; font-size: 11px;"
        )
        log_lay.addWidget(self.log_text)
        self.btn_clear_log = QPushButton("Xóa log")
        self.btn_clear_log.setFixedWidth(80)
        self.btn_clear_log.setStyleSheet("font-size: 11px;")
        self.btn_clear_log.clicked.connect(self.log_text.clear)
        log_lay.addWidget(self.btn_clear_log, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addWidget(grp_log, 1)

        # --- Render controls ---
        grp_ctrl = QGroupBox("▶  Render")
        grp_ctrl.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        ctrl_lay = QVBoxLayout(grp_ctrl)
        ctrl_lay.setSpacing(8)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_render = QPushButton("▶  Bắt đầu Render")
        self.btn_render.setMinimumHeight(38)
        self.btn_render.setStyleSheet(
            "QPushButton { background: #2563eb; color: white; font-size: 13px; "
            "font-weight: 600; border-radius: 6px; border: none; }"
            "QPushButton:hover { background: #1d4ed8; }"
            "QPushButton:disabled { background: #93c5fd; }"
        )
        self.btn_render.clicked.connect(self._start_render)
        btn_row.addWidget(self.btn_render)

        self.btn_export = QPushButton("📤  Xuất JSON")
        self.btn_export.setMinimumHeight(38)
        self.btn_export.setMinimumWidth(100)
        self.btn_export.setStyleSheet(
            "QPushButton { background: #059669; color: white; font-size: 13px; "
            "font-weight: 600; border-radius: 6px; border: none; }"
            "QPushButton:hover { background: #047857; }"
        )
        self.btn_export.clicked.connect(self._export_json)
        btn_row.addWidget(self.btn_export)

        self.btn_pause = QPushButton("⏸  Tạm dừng")
        self.btn_pause.setMinimumHeight(38)
        self.btn_pause.setMinimumWidth(90)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet(
            "QPushButton { background: #f59e0b; color: white; font-size: 13px; "
            "border-radius: 6px; border: none; }"
            "QPushButton:hover { background: #d97706; }"
            "QPushButton:disabled { background: #fcd34d; }"
        )
        self.btn_pause.clicked.connect(self._toggle_pause_render)
        btn_row.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("⏹  Dừng")
        self.btn_stop.setMinimumHeight(38)
        self.btn_stop.setMinimumWidth(70)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "QPushButton { background: #dc2626; color: white; font-size: 13px; "
            "border-radius: 6px; border: none; }"
            "QPushButton:hover { background: #b91c1c; }"
            "QPushButton:disabled { background: #fca5a5; }"
        )
        self.btn_stop.clicked.connect(self._stop_render)
        btn_row.addWidget(self.btn_stop)

        ctrl_lay.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(24)
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #cbd5e1; border-radius: 4px; "
            "background: #e2e8f0; text-align: center; font-size: 12px; }"
            "QProgressBar::chunk { background: #2563eb; border-radius: 3px; }"
        )
        ctrl_lay.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Sẵn sàng")
        self.lbl_status.setStyleSheet("font-size: 12px; color: #64748b;")
        ctrl_lay.addWidget(self.lbl_status)

        lay.addWidget(grp_ctrl)
        return panel

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(56)
        bar.setStyleSheet(
            "background: #f1f5f9; border-top: 1px solid #e2e8f0;"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(12)

        self.btn_render = QPushButton("▶  Bắt đầu Render")
        self.btn_render.setFixedHeight(38)
        self.btn_render.setMinimumWidth(160)
        self.btn_render.setStyleSheet(
            "QPushButton { background: #2563eb; color: white; font-size: 14px; "
            "font-weight: 600; border-radius: 6px; border: none; }"
            "QPushButton:hover { background: #1d4ed8; }"
            "QPushButton:disabled { background: #93c5fd; }"
        )
        self.btn_render.clicked.connect(self._start_render)

        self.btn_export = QPushButton("📤  Xuất JSON")
        self.btn_export.setFixedHeight(38)
        self.btn_export.setMinimumWidth(100)
        self.btn_export.setStyleSheet(
            "QPushButton { background: #059669; color: white; font-size: 13px; "
            "font-weight: 600; border-radius: 6px; border: none; }"
            "QPushButton:hover { background: #047857; }"
        )
        self.btn_export.clicked.connect(self._export_json)

        self.btn_pause = QPushButton("⏸  Tạm dừng")
        self.btn_pause.setFixedHeight(38)
        self.btn_pause.setMinimumWidth(100)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet(
            "QPushButton { background: #f59e0b; color: white; font-size: 13px; "
            "border-radius: 6px; border: none; }"
            "QPushButton:hover { background: #d97706; }"
            "QPushButton:disabled { background: #fcd34d; }"
        )
        self.btn_pause.clicked.connect(self._toggle_pause_render)

        self.btn_stop = QPushButton("⏹  Dừng")
        self.btn_stop.setFixedHeight(38)
        self.btn_stop.setMinimumWidth(80)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "QPushButton { background: #dc2626; color: white; font-size: 13px; "
            "border-radius: 6px; border: none; }"
            "QPushButton:hover { background: #b91c1c; }"
            "QPushButton:disabled { background: #fca5a5; }"
        )
        self.btn_stop.clicked.connect(self._stop_render)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(28)
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #cbd5e1; border-radius: 4px; "
            "background: #e2e8f0; text-align: center; font-size: 12px; }"
            "QProgressBar::chunk { background: #2563eb; border-radius: 3px; }"
        )

        self.lbl_status = QLabel("Sẵn sàng")
        self.lbl_status.setStyleSheet("font-size: 12px; color: #64748b; min-width: 220px;")

        lay.addWidget(self.btn_render)
        lay.addWidget(self.btn_pause)
        lay.addWidget(self.btn_stop)
        lay.addWidget(self.btn_export)
        lay.addWidget(self.progress_bar, 1)
        lay.addWidget(self.lbl_status)
        return bar

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _apply_saved_settings(self):
        s = self._settings
        saved_bg_files = s.get("bg_files", [])
        if isinstance(saved_bg_files, list) and saved_bg_files:
            self.pick_bg.set_selected_files(saved_bg_files)
            self._log_debug(f"Restored {len(saved_bg_files)} saved background videos")
        else:
            self.pick_bg.set_value(s.get("bg_folder", ""))
        self.pick_output.set_value(s.get("output_folder", ""))

        hardcoded_media_files = self._resolve_hardcoded_media_files()
        if hardcoded_media_files:
            self.pick_audio.set_selected_files(hardcoded_media_files)
            self._log_debug(f"Applied hardcoded media path: {HARDCODED_AUDIO_DIR}")
        else:
            self._log_debug("No media files loaded from hardcoded path")

        saved_srt_files = s.get("srt_files", [])
        if isinstance(saved_srt_files, list) and saved_srt_files:
            self.pick_srt.set_selected_files(saved_srt_files)
            self._log_debug(f"Restored {len(saved_srt_files)} saved SRT files")

        # Load subtitle style from saved settings
        preset = SubtitleStylePreset(
            name="Restored",
            font_name=s.get("font_name", "Arial"),
            font_size=s.get("font_size", 40),
            font_color=s.get("font_color", "#FFFFFF"),
            stroke_color=s.get("stroke_color", "#000000"),
            stroke_width=s.get("stroke_width", 2.0),
            stroke_enabled=s.get("stroke_enabled", True),
            bg_color=s.get("bg_color", "#000000"),
            bg_opacity=s.get("bg_opacity", 0.6),
            bg_padding_x=s.get("bg_padding_x", s.get("outline_size", 12)),
            bg_padding_y=s.get("bg_padding_y", 4),
            bg_corner_radius=s.get("bg_corner_radius", 4),
            bg_enabled=s.get("bg_enabled", True),
            shadow_color=s.get("shadow_color", "#000000"),
            shadow_opacity=s.get("shadow_opacity", 0.8),
            shadow_angle=s.get("shadow_angle", 45.0),
            shadow_distance=s.get("shadow_distance", 3.0),
            shadow_blur=s.get("shadow_blur", 2.0),
            shadow_enabled=s.get("shadow_enabled", False),
            alignment=s.get("subtitle_alignment", 2),
            margin_v=s.get("margin_v", 50),
            margin_l=s.get("margin_l", 20),
            margin_r=s.get("margin_r", 20),
        )
        self.style_panel.load_from_style(preset)

        self.spn_slow_min.setValue(s.get("slow_min", 35.0))
        self.spn_slow_max.setValue(s.get("slow_max", 45.0))

        codec_val = s.get("codec", "hevc_nvenc")
        for i, (_, val) in enumerate(CODECS):
            if val == codec_val:
                self.cmb_codec.setCurrentIndex(i)
                break

        self._load_presets()

        # Auto-scan if files already set
        if self.pick_audio.selected_files() and self.pick_srt.selected_files():
            self._scan_pairs()

    def _auto_export_json(self):
        if not self._pairs:
            return
        data = {
            "folders": {
                "bg_folder": self.pick_bg.value(),
                "bg_files": self.pick_bg.selected_files(),
                "audio_files": self.pick_audio.selected_files(),
                "srt_files": self.pick_srt.selected_files(),
                "output_folder": self.pick_output.value(),
            },
            "subtitle": self.style_panel.get_style().to_dict(),
            "render": {
                "codec": CODECS[self.cmb_codec.currentIndex()][1],
                "slow_min": self.spn_slow_min.value(),
                "slow_max": self.spn_slow_max.value(),
            },
            "pairs": [
                {
                    "index": p.index,
                    "audio": p.audio_path,
                    "srt": p.srt_path,
                    "matched": p.matched,
                    "error": p.error,
                }
                for p in self._pairs
            ],
        }
        try:
            with open(EXPORT_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _save_settings(self):
        style = self.style_panel.get_style()
        cfg.save({
            "bg_folder": self.pick_bg.value(),
            "bg_files": self.pick_bg.selected_files(),
            "audio_files": self.pick_audio.selected_files(),
            "srt_files": self.pick_srt.selected_files(),
            "output_folder": self.pick_output.value(),
            "font_name": style.font_name,
            "font_size": style.font_size,
            "font_color": style.font_color,
            "stroke_color": style.stroke_color,
            "stroke_width": style.stroke_width,
            "stroke_enabled": style.stroke_enabled,
            "bg_color": style.bg_color,
            "bg_opacity": style.bg_opacity,
            "bg_padding_x": style.bg_padding_x,
            "bg_padding_y": style.bg_padding_y,
            "bg_corner_radius": style.bg_corner_radius,
            "bg_enabled": style.bg_enabled,
            "shadow_color": style.shadow_color,
            "shadow_opacity": style.shadow_opacity,
            "shadow_angle": style.shadow_angle,
            "shadow_distance": style.shadow_distance,
            "shadow_blur": style.shadow_blur,
            "shadow_enabled": style.shadow_enabled,
            "outline_size": style.bg_padding_x,  # legacy alias
            "margin_v": style.margin_v,
            "margin_l": style.margin_l,
            "margin_r": style.margin_r,
            "slow_min": self.spn_slow_min.value(),
            "slow_max": self.spn_slow_max.value(),
            "codec": CODECS[self.cmb_codec.currentIndex()][1],
            "use_gpu": True,
            "subtitle_alignment": style.alignment,
        })
        self._auto_export_json()

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất lựa chọn ra JSON", "selections.json",
            "JSON files (*.json)"
        )
        if not path:
            return

        matched_pairs = [
            {
                "index": p.index,
                "audio": p.audio_path,
                "srt": p.srt_path,
                "matched": p.matched,
                "error": p.error,
            }
            for p in self._pairs
        ]

        data = {
            "folders": {
                "bg_folder": self.pick_bg.value(),
                "bg_files": self.pick_bg.selected_files(),
                "audio_files": self.pick_audio.selected_files(),
                "srt_files": self.pick_srt.selected_files(),
                "output_folder": self.pick_output.value(),
            },
            "subtitle": self.style_panel.get_style().to_dict(),
            "render": {
                "codec": CODECS[self.cmb_codec.currentIndex()][1],
                "slow_min": self.spn_slow_min.value(),
                "slow_max": self.spn_slow_max.value(),
            },
            "pairs": matched_pairs,
        }

        try:
            import json
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.statusBar().showMessage(f"Đã xuất ra {path}", 5000)
            self._log(f"📤 Đã xuất lựa chọn ra {path}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi xuất JSON", str(e))

    # ------------------------------------------------------------------
    # Logic
    # ------------------------------------------------------------------

    def _check_deps(self):
        from utils.gpu_detect import check_ffmpeg, check_ffprobe
        issues = []
        if not check_ffmpeg():
            issues.append("• FFmpeg không tìm thấy — hãy cài FFmpeg và thêm vào PATH")
        if not check_ffprobe():
            issues.append("• FFprobe không tìm thấy — thường đi kèm FFmpeg")
        if issues:
            QMessageBox.warning(self, "Thiếu phụ thuộc", "\n".join(issues))

    def _on_file_selection_change(self, _value):
        self._log_debug(
            f"File selection changed | bg={len(self.pick_bg.selected_files())} | media={len(self.pick_audio.selected_files())} | srt={len(self.pick_srt.selected_files())}"
        )
        if self.pick_audio.selected_files() and self.pick_srt.selected_files():
            self._scan_pairs()

    def _scan_pairs(self):
        media_files = self.pick_audio.selected_files()
        srt_files = self.pick_srt.selected_files()
        self._log_debug(f"Scanning pairs | media_files={len(media_files)} | srt_files={len(srt_files)}")
        if not media_files or not srt_files:
            self._log_debug("Scan skipped because media or srt list is empty")
            return

        self.lbl_pair_summary.setText("Đang quét…")
        try:
            pairs = build_pairs(media_files, srt_files)
            self._log_debug(f"Built {len(pairs)} pairs successfully")
            self._on_pairs_ready(pairs)
        except Exception as e:
            self._log_debug(f"Pair scan failed: {e}")
            self.lbl_pair_summary.setText(f"Lỗi: {e}")

    def _on_pairs_ready(self, pairs: list[FilePair]):
        self._pairs = pairs
        self.pair_table.load_pairs(pairs)
        matched = sum(1 for p in pairs if p.matched)
        total = len(pairs)
        fuzzy_matched = sum(1 for p in pairs if p.matched and p.error.startswith("Ghép gần đúng"))
        summary = f"Tìm thấy {total} file  —  {matched} khớp ✓  —  {total - matched} thiếu cặp ✗"
        if fuzzy_matched:
            summary += f"  —  {fuzzy_matched} cặp ghép theo tên gần đúng"
        self._log_debug(f"Pair summary: {summary}")
        self.lbl_pair_summary.setText(summary)
        self._auto_export_json()

    # ------------------------------------------------------------------
    # Subtitle editor integration (Phase 1 + Phase 4)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Preset management (Phase 3)
    # ------------------------------------------------------------------

    def _load_presets(self):
        """Load style presets into the combo box."""
        self._presets = StylePresetService.load_all()
        self.cmb_preset.blockSignals(True)
        self.cmb_preset.clear()
        for p in self._presets:
            self.cmb_preset.addItem(p.name)
        self.cmb_preset.blockSignals(False)

    def _on_preset_changed(self, index: int):
        """Apply selected preset to the style panel."""
        if index < 0 or index >= len(self._presets):
            return
        preset = self._presets[index]
        self.style_panel.load_from_style(preset)
        self._active_preset = preset

    def _on_save_preset(self):
        """Save current style as a new preset."""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Luu Preset Style", "Ten preset moi:",
            text=self.style_panel.get_style().name
        )
        if not ok or not name.strip():
            return
        style = self.style_panel.get_style()
        preset = SubtitleStylePreset(
            name=name.strip(),
            font_name=style.font_name,
            font_size=style.font_size,
            font_color=style.font_color,
            stroke_color=style.stroke_color,
            stroke_width=style.stroke_width,
            stroke_enabled=style.stroke_enabled,
            bg_color=style.bg_color,
            bg_opacity=style.bg_opacity,
            bg_padding_x=style.bg_padding_x,
            bg_padding_y=style.bg_padding_y,
            bg_corner_radius=style.bg_corner_radius,
            bg_enabled=style.bg_enabled,
            shadow_color=style.shadow_color,
            shadow_opacity=style.shadow_opacity,
            shadow_angle=style.shadow_angle,
            shadow_distance=style.shadow_distance,
            shadow_blur=style.shadow_blur,
            shadow_enabled=style.shadow_enabled,
            alignment=style.alignment,
            margin_v=style.margin_v,
            margin_l=style.margin_l,
            margin_r=style.margin_r,
        )
        self._presets = StylePresetService.add_preset(preset)
        self.cmb_preset.addItem(name.strip())
        self.cmb_preset.setCurrentIndex(self.cmb_preset.count() - 1)

    def _on_apply_style_to_all(self):
        """Apply current style to all selected SRT files (batch apply)."""
        from PyQt6.QtWidgets import QMessageBox
        srt_files = self.pick_srt.selected_files()
        if not srt_files:
            QMessageBox.information(self, "Ap toan bo", "Chua co file SRT nao duoc chon.")
            return
        reply = QMessageBox.question(
            self, "Ap toan bo",
            f"Ap style hien tai cho {len(srt_files)} file SRT da chon?\n"
            "Chi style se duoc luu vao metadata, khong thay doi noi dung SRT.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        style = self.style_panel.get_style()
        for srt_file in srt_files:
            SrtService.apply_style_template(srt_file, srt_file, style.name, style.to_dict())
        QMessageBox.information(self, "Ap toan bo", f"Da ap style cho {len(srt_files)} file.")

    # ------------------------------------------------------------------
    # Render config
    # ------------------------------------------------------------------

    def _build_config(self) -> RenderConfig:
        codec_val = CODECS[self.cmb_codec.currentIndex()][1]
        preset = self.style_panel.get_style()
        style = SubtitleStyle.from_preset(preset)
        return RenderConfig(
            bg_folder=self.pick_bg.value(),
            bg_videos=self.pick_bg.selected_files(),
            audio_folder=self.pick_audio.value(),
            srt_folder=self.pick_srt.value(),
            output_folder=self.pick_output.value(),
            subtitle_style=style,
            slow_min=self.spn_slow_min.value(),
            slow_max=self.spn_slow_max.value(),
            codec=codec_val,
            use_gpu="nvenc" in codec_val,
        )

    def _validate(self) -> bool:
        errs = []
        if not self.pick_bg.selected_files():
            errs.append("• Chưa chọn file Video nền")
        if not self.pick_audio.selected_files():
            errs.append("• Chưa chọn file media nguồn")
        if not self.pick_srt.selected_files():
            errs.append("• Chưa chọn file Subtitle SRT")
        if not self.pick_output.value():
            errs.append("• Chưa chọn thư mục Output")
        if not self._pairs:
            errs.append("• Chưa có file nào được ghép (hãy quét lại)")
        matched = [p for p in self._pairs if p.matched]
        if not matched:
            errs.append("• Không có cặp file audio+SRT hợp lệ nào")
        if errs:
            QMessageBox.warning(self, "Chưa đủ thông tin", "\n".join(errs))
            return False
        return True

    def _start_render(self):
        if not self._validate():
            return

        self._save_settings()

        config = self._build_config()
        os.makedirs(config.output_folder, exist_ok=True)
        matched_pairs = [p for p in self._pairs if p.matched]

        self._worker = RenderWorker(matched_pairs, config, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.log_line.connect(self._on_log)
        self._worker.pair_done.connect(self._on_pair_done)
        self._worker.pair_error.connect(self._on_pair_error)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.stopped.connect(self._on_stopped)
        self._worker.paused.connect(self._on_paused)
        self._worker.resumed.connect(self._on_resumed)

        self.btn_render.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("⏸  Tạm dừng")
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self._log(f"Bắt đầu render {len(matched_pairs)} video...")
        self._log(f"Codec: {config.codec}  |  GPU: {config.use_gpu}")
        self._log("-" * 60)

        self._worker.start()

    def _toggle_pause_render(self):
        if not self._worker:
            return
        if self.btn_pause.text().startswith("⏸"):
            self._worker.pause()
        else:
            self._worker.resume()

    def _stop_render(self):
        if self._worker:
            self._worker.abort()
            self.btn_pause.setEnabled(False)
            self.btn_stop.setEnabled(False)
            self.lbl_status.setText("Đang dừng…")

    def _on_paused(self):
        self.btn_pause.setText("▶  Tiếp tục")
        self.lbl_status.setText("Đã tạm dừng")
        self._log("--- Render tạm dừng ---")

    def _on_resumed(self):
        self.btn_pause.setText("⏸  Tạm dừng")
        self.lbl_status.setText("Đang tiếp tục render…")
        self._log("--- Render tiếp tục ---")

    def _on_progress(self, pct: float, msg: str):
        self.progress_bar.setValue(int(pct))
        self.lbl_status.setText(msg)

    def _on_log(self, line: str):
        # Only show meaningful lines (filter out very verbose FFmpeg stats)
        if any(k in line for k in ["frame=", "fps=", "bitrate=", "speed="]):
            return  # skip per-frame stats spam; progress bar handles it
        self._log(line)

    def _log(self, text: str):
        self.log_text.appendPlainText(text)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_pair_done(self, index: str, output: str):
        self._log(f"✓ [{index}] Xong → {Path(output).name}")

    def _on_pair_error(self, index: str, error: str):
        self._log(f"✗ [{index}] Lỗi: {error}")

    def _on_all_done(self, success: int, errors: int):
        self.btn_render.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸  Tạm dừng")
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(100)
        msg = f"Hoàn thành! {success} video thành công"
        if errors:
            msg += f", {errors} lỗi"
        self.lbl_status.setText(msg)
        self._log("=" * 60)
        self._log(msg)
        QMessageBox.information(self, "Hoàn thành", msg)

    def _on_stopped(self):
        self.btn_render.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸  Tạm dừng")
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("Đã dừng")
        self._log("--- Render bị dừng bởi người dùng ---")

    def _on_refresh_preview_frame(self):
        """Extract a frame from the first selected video and set it as preview background."""
        video_files = self.pick_bg.selected_files()
        if not video_files:
            self.style_panel.set_frame(None)
            return
        frame = _extract_video_frame(video_files[0])
        self.style_panel.set_frame(frame)

    def _on_first_sub_to_zero(self):
        """Shift the entire subtitle timeline so the first subtitle starts at 0s."""
        srt_files = self.pick_srt.selected_files()
        if not srt_files:
            QMessageBox.information(self, "Shift To 0s", "Chưa có file SRT nào được chọn.")
            return

        reply = QMessageBox.question(
            self, "Shift To 0s",
            f"Shift toàn bộ timeline của {len(srt_files)} file SRT về 0s?\n"
            "Thời gian bắt đầu đầu tiên sẽ được trừ đi khỏi mọi subtitle.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        changed = 0
        total_offset_ms = 0
        errors = []
        for path in srt_files:
            try:
                entries = SrtService.parse(path)
                if not entries:
                    errors.append(f"{Path(path).name}: file rỗng")
                    continue
                self._timing_undo[path] = entries[:]
                new_entries, offset_ms = SrtService.shift_to_zero(entries)
                SrtService.write(path, new_entries)
                changed += 1
                total_offset_ms = offset_ms  # same for all files in the set
            except Exception as e:
                errors.append(f"{Path(path).name}: {e}")

        if changed:
            self.btn_undo_timing.setEnabled(True)
            offset_s = total_offset_ms / 1000.0
            QMessageBox.information(
                self, "Shift To 0s",
                f"Shifted subtitle timeline by -{offset_s:.3f} seconds.\n"
                f"Đã xử lý {changed} file."
            )
            self._scan_pairs()
            if srt_files:
                self.style_panel.reload_srt_entries(srt_files[0])
        elif errors:
            QMessageBox.warning(self, "Shift To 0s", f"Lỗi: {', '.join(errors)}")
        self._log(f"[Timing] Shift to 0s: {changed} file, offset=-{total_offset_ms}ms")

    def _on_undo_timing(self):
        """Restore SRT files to their state before the last timing change."""
        if not self._timing_undo:
            return
        reply = QMessageBox.question(
            self, "Undo", f"Hoàn tác {len(self._timing_undo)} file về trạng thái trước đó?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        restored = 0
        errors = []
        for path, entries in self._timing_undo.items():
            try:
                SrtService.write(path, entries)
                restored += 1
            except Exception as e:
                errors.append(f"{Path(path).name}: {e}")

        self._timing_undo.clear()
        self.btn_undo_timing.setEnabled(False)

        msg = f"Đã khôi phục {restored} file."
        if errors:
            msg += f"\nLỗi: {', '.join(errors)}"
        QMessageBox.information(self, "Undo", msg)
        self._log(f"[Timing] Undo: {restored} file khôi phục")

    def closeEvent(self, event):
        self._save_settings()
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(3000)
        event.accept()
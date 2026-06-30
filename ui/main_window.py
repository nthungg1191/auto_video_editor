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
    QFrame, QGridLayout, QAbstractItemView, QTabWidget
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QRunnable, QThreadPool, QObject
from PyQt6.QtGui import QColor, QFont, QIcon, QImage

from core.video_processor import RenderConfig, SubtitleStyle, FilePair, build_pairs, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS
from core.worker import RenderWorker
from core.subtitle_model import SubtitleStylePreset
from core.srt_service import SrtService
from core.style_preset_service import StylePresetService
from core.subtitle_model import SubtitleEntry
from ui.subtitle_preview_widget import SubtitlePreviewWidget, SubtitleStyleEditor, LiveFramePreview
from ui.video_layer_config import VideoLayerConfigWidget
from ui.video_layout_preview import VideoLayoutPreview
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



class ImageLayerControl(QWidget):
    changed = pyqtSignal()

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.init_ui()

    def init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # Row 1: Kích hoạt + File logo
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        
        self.chk_enabled = QCheckBox("Kích hoạt Layer")
        self.chk_enabled.setStyleSheet("font-size: 11px; font-weight: bold;")
        self.chk_enabled.stateChanged.connect(self._on_changed)
        row1.addWidget(self.chk_enabled)

        self.pick_logo = FolderPicker("File logo:", "Chọn ảnh logo (.png, .jpg)")
        self.pick_logo.set_mode("files")
        self.pick_logo.set_file_dialog(
            "Chọn file ảnh logo",
            "Image files (*.png *.jpg *.jpeg *.bmp);;All files (*.*)"
        )
        self.pick_logo.btn.setText("Chọn…")
        self.pick_logo.lbl.setFixedWidth(50)
        self.pick_logo.set_callback(self._on_file_changed)
        row1.addWidget(self.pick_logo, 1)
        lay.addLayout(row1)

        # Row 2: Vị trí
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        pos_lbl = QLabel("Vị trí:")
        pos_lbl.setStyleSheet("font-size: 11px;")
        pos_lbl.setFixedWidth(50)
        row2.addWidget(pos_lbl)

        self.cmb_logo_pos = QComboBox()
        self.cmb_logo_pos.addItems([
            "Góc dưới - Phải (Bottom-Right)",
            "Góc dưới - Trái (Bottom-Left)",
            "Góc trên - Phải (Top-Right)",
            "Góc trên - Trái (Top-Left)",
            "Ở giữa - Trên (Top-Center)"
        ])
        self.cmb_logo_pos.setStyleSheet("font-size: 11px;")
        self.cmb_logo_pos.currentIndexChanged.connect(self._on_changed)
        row2.addWidget(self.cmb_logo_pos, 1)
        lay.addLayout(row2)

        # Row 3: Cỡ (Size) & Độ mờ (Opacity)
        row3 = QHBoxLayout()
        row3.setSpacing(10)

        sz_lbl = QLabel("Cỡ (px):")
        sz_lbl.setStyleSheet("font-size: 11px;")
        row3.addWidget(sz_lbl)

        self.spn_logo_size = QSpinBox()
        self.spn_logo_size.setRange(20, 500)
        self.spn_logo_size.setValue(100)
        self.spn_logo_size.setSingleStep(10)
        self.spn_logo_size.setStyleSheet("font-size: 11px;")
        self.spn_logo_size.valueChanged.connect(self._on_changed)
        row3.addWidget(self.spn_logo_size, 1)

        op_lbl = QLabel("Độ mờ (%):")
        op_lbl.setStyleSheet("font-size: 11px;")
        row3.addWidget(op_lbl)

        self.spn_logo_opacity = QSpinBox()
        self.spn_logo_opacity.setRange(10, 100)
        self.spn_logo_opacity.setValue(90)
        self.spn_logo_opacity.setSingleStep(5)
        self.spn_logo_opacity.setStyleSheet("font-size: 11px;")
        self.spn_logo_opacity.valueChanged.connect(self._on_changed)
        row3.addWidget(self.spn_logo_opacity, 1)
        lay.addLayout(row3)

        # Row 4: Margins (Top, Bottom, Left, Right)
        margin_grp = QGroupBox("Cân chỉnh khoảng lề (Margin - px)")
        margin_grp.setStyleSheet("QGroupBox { font-size: 10px; font-weight: bold; }")
        margin_lay = QHBoxLayout(margin_grp)
        margin_lay.setContentsMargins(6, 6, 6, 6)
        margin_lay.setSpacing(6)

        # Top
        t_lay = QHBoxLayout()
        t_lbl = QLabel("Trên:")
        t_lbl.setStyleSheet("font-size: 10px; color: #6b7280;")
        self.spn_margin_t = QSpinBox()
        self.spn_margin_t.setRange(0, 300)
        self.spn_margin_t.setValue(20)
        self.spn_margin_t.setStyleSheet("font-size: 10px;")
        self.spn_margin_t.valueChanged.connect(self._on_changed)
        t_lay.addWidget(t_lbl)
        t_lay.addWidget(self.spn_margin_t)
        margin_lay.addLayout(t_lay)

        # Bottom
        b_lay = QHBoxLayout()
        b_lbl = QLabel("Dưới:")
        b_lbl.setStyleSheet("font-size: 10px; color: #6b7280;")
        self.spn_margin_b = QSpinBox()
        self.spn_margin_b.setRange(0, 300)
        self.spn_margin_b.setValue(20)
        self.spn_margin_b.setStyleSheet("font-size: 10px;")
        self.spn_margin_b.valueChanged.connect(self._on_changed)
        b_lay.addWidget(b_lbl)
        b_lay.addWidget(self.spn_margin_b)
        margin_lay.addLayout(b_lay)

        # Left
        l_lay_margin = QHBoxLayout()
        l_lbl = QLabel("Trái:")
        l_lbl.setStyleSheet("font-size: 10px; color: #6b7280;")
        self.spn_margin_l = QSpinBox()
        self.spn_margin_l.setRange(0, 500)
        self.spn_margin_l.setValue(20)
        self.spn_margin_l.setStyleSheet("font-size: 10px;")
        self.spn_margin_l.valueChanged.connect(self._on_changed)
        l_lay_margin.addWidget(l_lbl)
        l_lay_margin.addWidget(self.spn_margin_l)
        margin_lay.addLayout(l_lay_margin)

        # Right
        r_lay_margin = QHBoxLayout()
        r_lbl = QLabel("Phải:")
        r_lbl.setStyleSheet("font-size: 10px; color: #6b7280;")
        self.spn_margin_r = QSpinBox()
        self.spn_margin_r.setRange(0, 500)
        self.spn_margin_r.setValue(20)
        self.spn_margin_r.setStyleSheet("font-size: 10px;")
        self.spn_margin_r.valueChanged.connect(self._on_changed)
        r_lay_margin.addWidget(r_lbl)
        r_lay_margin.addWidget(self.spn_margin_r)
        margin_lay.addLayout(r_lay_margin)

        lay.addSpacing(5)
        lay.addWidget(margin_grp)

    def _on_file_changed(self, files):
        self._on_changed()

    def _on_changed(self):
        self.changed.emit()

    def get_config(self) -> ImageLayerConfig:
        from core.video_processor import ImageLayerConfig
        files = self.pick_logo.selected_files()
        path = files[0] if files else ""
        return ImageLayerConfig(
            enabled=self.chk_enabled.isChecked(),
            path=path,
            position=self.cmb_logo_pos.currentIndex(),
            size=self.spn_logo_size.value(),
            opacity=self.spn_logo_opacity.value() / 100.0,
            margin_t=self.spn_margin_t.value(),
            margin_b=self.spn_margin_b.value(),
            margin_l=self.spn_margin_l.value(),
            margin_r=self.spn_margin_r.value()
        )


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
            self.setItem(row, 0, self._cell(pair.index, center=True, checkable=pair.matched))
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
    def _cell(text: str, center: bool = False, checkable: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if center:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if checkable:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
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


class FrameExtractSignals(QObject):
    loaded = pyqtSignal(str, QImage)  # path, image

class FrameExtractTask(QRunnable):
    def __init__(self, video_path: str):
        super().__init__()
        self.video_path = video_path
        self.signals = FrameExtractSignals()

    def run(self):
        img = _extract_video_frame(self.video_path)
        if img and not img.isNull():
            self.signals.loaded.emit(self.video_path, img)


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
        self.logo_layers: list[ImageLayerControl] = []
        self.frame_pool = QThreadPool()
        self.frame_pool.setMaxThreadCount(2)
        self.running_extractions = set()

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

        # --- Main Mode Tab Selector Bar ---
        mode_bar = QWidget()
        mode_bar.setFixedHeight(36)
        mode_bar.setStyleSheet("background: #e2e8f0; border-bottom: 1px solid #cbd5e1;")
        mode_lay = QHBoxLayout(mode_bar)
        mode_lay.setContentsMargins(0, 0, 0, 0)
        mode_lay.setSpacing(0)

        self.btn_tab_sub = QPushButton("✍️ Edit Sub (Biên tập phụ đề)")
        self.btn_tab_sub.setCheckable(True)
        self.btn_tab_sub.setChecked(True)
        self.btn_tab_sub.setFixedHeight(36)
        self.btn_tab_sub.setStyleSheet(
            "QPushButton { background: #ffffff; color: #2563eb; font-weight: bold; border: none; border-bottom: 2px solid #2563eb; font-size: 12px; }"
            "QPushButton:hover { background: #f8fafc; }"
        )
        self.btn_tab_sub.clicked.connect(self._on_mode_sub_clicked)

        self.btn_tab_video = QPushButton("🎬 Edit Video (Biên tập Video)")
        self.btn_tab_video.setCheckable(True)
        self.btn_tab_video.setChecked(False)
        self.btn_tab_video.setFixedHeight(36)
        self.btn_tab_video.setStyleSheet(
            "QPushButton { background: #f1f5f9; color: #475569; font-weight: bold; border: none; font-size: 12px; }"
            "QPushButton:hover { background: #e2e8f0; }"
        )
        self.btn_tab_video.clicked.connect(self._on_mode_video_clicked)

        mode_lay.addWidget(self.btn_tab_sub, 1)
        mode_lay.addWidget(self.btn_tab_video, 1)
        root_lay.addWidget(mode_bar)

        # --- 3-panel horizontal splitter ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        left   = self._build_left_panel()    # file selection
        middle = self._build_middle_panel()  # subtitle style + preview
        right  = self._build_right_panel()   # render + log + controls

        splitter.addWidget(left)
        splitter.addWidget(middle)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 11)
        splitter.setStretchFactor(1, 23)
        splitter.setStretchFactor(2, 8)
        splitter.setSizes([330, 670, 240])

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

        title_lbl = QLabel("Author: Thịnh.G ")
        title_lbl.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: 600;")
        lay.addWidget(title_lbl)
        lay.addSpacing(16)
        
        # CPU load badge
        self._cpu_load_lbl = QLabel(f"CPU: {si['cpu_load_pct']}%")
        self._cpu_load_lbl.setStyleSheet(
            "color: #fde68a; font-size: 11px; "
            "background: #2e2500; border-radius: 4px; padding: 3px 8px; "
            "border: 1px solid #78350f;"
        )
        lay.addWidget(self._cpu_load_lbl)


        # RAM usage badge
        self._ram_pct_lbl = QLabel(f"RAM: {si['ram_used_pct']}%")
        self._ram_pct_lbl.setStyleSheet(
            "color: #fca5a5; font-size: 11px; "
            "background: #2e1a1a; border-radius: 4px; padding: 3px 8px; "
            "border: 1px solid #742a2a;"
        )
        lay.addWidget(self._ram_pct_lbl)

        # GPU badge
        gpu_ok = si["gpu_available"]
        gpu_color = "#4ade80" if gpu_ok else "#f87171"
        gpu_bg = "#1a2e1a" if gpu_ok else "#2e1a1a"
        gpu_border = "#22543d" if gpu_ok else "#742a2a"
        self._gpu_lbl = QLabel(f"GPU: {si['gpu_name']}")
        if gpu_ok:
            vram_used = si['vram_total_mb'] - si['vram_free_mb']
            self._gpu_lbl.setText(f"GPU: {si['gpu_name']}  VRAM: {vram_used}/{si['vram_total_mb']} MB")
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

        # CPU load
        self._cpu_load_lbl.setText(f"CPU: {si['cpu_load_pct']}%")

        # RAM usage
        self._ram_pct_lbl.setText(f"RAM: {si['ram_used_pct']}%")

        # VRAM
        if si["gpu_available"]:
            vram_used = si['vram_total_mb'] - si['vram_free_mb']
            self._gpu_lbl.setText(
                f"GPU: {si['gpu_name']}  VRAM: {vram_used}/{si['vram_total_mb']} MB"
            )
            if self._pwr_lbl and si["gpu_power_w"] != "—":
                self._pwr_lbl.setText(si["gpu_power_w"])

    # ---- Left panel ----

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet("background: #fafafa;")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 1. Edit Sub Container
        self.left_sub_container = QWidget()
        sub_lay = QVBoxLayout(self.left_sub_container)
        sub_lay.setContentsMargins(12, 12, 12, 12)
        sub_lay.setSpacing(10)

        # Folder pickers group
        grp_folders = QGroupBox("📁  Thư mục (Biên tập phụ đề)")
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

        sub_lay.addWidget(grp_folders)

        # File pairs table
        grp_pairs = QGroupBox("📋  Danh sách file (audio ↔ SRT)")
        grp_pairs.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        p_lay = QVBoxLayout(grp_pairs)
        self.pair_table = PairTable()
        self.pair_table.itemSelectionChanged.connect(self._on_pair_selection_changed)
        self.pair_table.itemChanged.connect(self._on_table_item_changed)
        p_lay.addWidget(self.pair_table)

        pair_btn_lay = QHBoxLayout()
        self.btn_pair_select_all = QPushButton("Chọn tất cả")
        self.btn_pair_select_all.setStyleSheet("font-size: 10px; padding: 2px 8px;")
        self.btn_pair_select_all.clicked.connect(self._pair_select_all)
        self.btn_pair_deselect_all = QPushButton("Bỏ chọn tất cả")
        self.btn_pair_deselect_all.setStyleSheet("font-size: 10px; padding: 2px 8px;")
        self.btn_pair_deselect_all.clicked.connect(self._pair_deselect_all)
        pair_btn_lay.addWidget(self.btn_pair_select_all)
        pair_btn_lay.addWidget(self.btn_pair_deselect_all)
        pair_btn_lay.addStretch(1)
        
        self.lbl_pair_summary = QLabel("Chưa quét")
        self.lbl_pair_summary.setStyleSheet("font-size: 11px; color: #6b7280;")
        pair_btn_lay.addWidget(self.lbl_pair_summary)
        p_lay.addLayout(pair_btn_lay)

        sub_lay.addWidget(grp_pairs, 1)
        lay.addWidget(self.left_sub_container)

        # 2. Edit Video Container
        self.left_video_container = QWidget()
        vid_lay = QVBoxLayout(self.left_video_container)
        vid_lay.setContentsMargins(12, 12, 12, 12)
        vid_lay.setSpacing(10)

        # Video pickers group
        grp_vid_folders = QGroupBox("📁  Thư mục (Biên tập video)")
        grp_vid_folders.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        fv_lay = QVBoxLayout(grp_vid_folders)
        fv_lay.setSpacing(6)

        self.pick_vid_src = FolderPicker("Video nguồn:", "Chọn thư mục video nguồn")
        self.pick_vid_bg = FolderPicker("Video nền:", "Chọn file video nền (tùy chọn)")
        self.pick_vid_output = FolderPicker("Output:", "Chọn thư mục xuất video")

        self.pick_vid_bg.set_mode("files")
        self.pick_vid_bg.set_file_dialog(
            "Chọn file video nền",
            "Video files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v);;All files (*.*)"
        )
        self.pick_vid_bg.btn.setText("Chọn file…")
        
        self.pick_vid_src.set_callback(self._on_video_selection_change)
        self.pick_vid_bg.set_callback(self._on_video_selection_change)

        for w in [self.pick_vid_src, self.pick_vid_bg, self.pick_vid_output]:
            fv_lay.addWidget(w)

        self.btn_vid_refresh = QPushButton("🔄  Quét lại thư mục")
        self.btn_vid_refresh.clicked.connect(self._scan_video_batch)
        self.btn_vid_refresh.setStyleSheet("font-size: 12px;")
        fv_lay.addWidget(self.btn_vid_refresh)

        vid_lay.addWidget(grp_vid_folders)

        # Video Batch Table
        grp_vids = QGroupBox("📋  Danh sách Video cần Scale hàng loạt")
        grp_vids.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        pv_lay = QVBoxLayout(grp_vids)
        
        self.vid_batch_table = QTableWidget(0, 4)
        self.vid_batch_table.setHorizontalHeaderLabels(["#", "Tên video nguồn", "Độ phân giải", "Trạng thái"])
        self.vid_batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vid_batch_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.vid_batch_table.setAlternatingRowColors(True)
        self.vid_batch_table.verticalHeader().setVisible(False)
        hdr = self.vid_batch_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.vid_batch_table.setColumnWidth(0, 40)
        self.vid_batch_table.setColumnWidth(3, 100)
        self.vid_batch_table.setStyleSheet("font-size: 12px;")
        self.vid_batch_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.vid_batch_table.itemSelectionChanged.connect(self._on_video_batch_selection_changed)
        self.vid_batch_table.itemChanged.connect(self._on_table_item_changed)
        pv_lay.addWidget(self.vid_batch_table)

        vid_btn_lay = QHBoxLayout()
        self.btn_vid_select_all = QPushButton("Chọn tất cả")
        self.btn_vid_select_all.setStyleSheet("font-size: 10px; padding: 2px 8px;")
        self.btn_vid_select_all.clicked.connect(self._vid_select_all)
        self.btn_vid_deselect_all = QPushButton("Bỏ chọn tất cả")
        self.btn_vid_deselect_all.setStyleSheet("font-size: 10px; padding: 2px 8px;")
        self.btn_vid_deselect_all.clicked.connect(self._vid_deselect_all)
        vid_btn_lay.addWidget(self.btn_vid_select_all)
        vid_btn_lay.addWidget(self.btn_vid_deselect_all)
        vid_btn_lay.addStretch(1)

        self.lbl_vid_summary = QLabel("Chưa quét")
        self.lbl_vid_summary.setStyleSheet("font-size: 11px; color: #6b7280;")
        vid_btn_lay.addWidget(self.lbl_vid_summary)
        pv_lay.addLayout(vid_btn_lay)

        vid_lay.addWidget(grp_vids, 1)
        lay.addWidget(self.left_video_container)
        self.left_video_container.setVisible(False)

        return panel

    # ---- Middle panel — Subtitle Style + Preview ----

    def _build_middle_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet("background: #fafafa;")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 1. Edit Sub Container
        self.middle_sub_container = QWidget()
        sub_lay = QVBoxLayout(self.middle_sub_container)
        sub_lay.setContentsMargins(10, 10, 10, 10)
        sub_lay.setSpacing(10)

        self.main_tab_widget = QTabWidget()
        self.main_tab_widget.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #cbd5e1; border-radius: 4px; background: white; }"
            "QTabBar::tab { font-size: 11px; font-weight: 600; padding: 6px 16px; background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; min-width: 120px; }"
            "QTabBar::tab:selected { background: white; color: #2563eb; border-bottom: 2px solid #2563eb; }"
        )

        # Tab 1: Subtitle Style
        tab_subtitle = QWidget()
        tab_subtitle_lay = QVBoxLayout(tab_subtitle)
        tab_subtitle_lay.setContentsMargins(6, 6, 6, 6)
        tab_subtitle_lay.setSpacing(6)

        self.style_panel = SubtitleStyleEditor()
        self.style_panel.hide_preset_bar()
        self.style_panel._preview.setVisible(True)
        self.style_panel.style_changed.connect(self._on_style_changed)

        preset_bar = QWidget()
        preset_bar.setFixedHeight(32)
        preset_bar.setStyleSheet(
            "background: #1e1e2e; border-radius: 4px; border: 1px solid #2e3347;"
        )
        pst_lay = QHBoxLayout(preset_bar)
        pst_lay.setContentsMargins(8, 0, 8, 0)
        pst_lay.setSpacing(6)

        title = QLabel("Presets")
        title.setStyleSheet("color: #f8fafc; font-size: 11px; font-weight: 600;")
        pst_lay.addWidget(title)
        pst_lay.addSpacing(4)

        self.cmb_preset = QComboBox()
        self.cmb_preset.setStyleSheet(
            "QComboBox { background: #2e3347; color: #f8fafc; border: 1px solid #2e3347; "
            "border-radius: 4px; padding: 0px 8px; font-size: 11px; height: 26px; }"
            "QComboBox::drop-down { border: none; width: 18px; }"
            "QComboBox::down-arrow { image: none; border-left: 3px solid transparent; "
            "border-right: 3px solid transparent; border-top: 4px #9ca3af; }"
        )
        self.cmb_preset.currentIndexChanged.connect(self._on_preset_changed)
        pst_lay.addWidget(self.cmb_preset, 1)

        for icon, tip, handler in [
            ("💾", "Save preset", self._on_save_preset),
            ("🗑", "Delete preset", self._on_delete_preset_inline),
            ("↺", "Reset defaults", self._on_reset_defaults_inline),
        ]:
            btn = QPushButton(icon)
            btn.setFixedSize(28, 22)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "QPushButton { background: #2e3347; color: #f8fafc; border: 1px solid #2e3347; "
                "border-radius: 4px; font-size: 12px; padding: 0; }"
                "QPushButton:hover { background: #5b8def; border-color: #5b8def; }"
            )
            btn.clicked.connect(handler)
            pst_lay.addWidget(btn)

        tab_subtitle_lay.addWidget(preset_bar)
        tab_subtitle_lay.addWidget(self.style_panel._ctrl)
        self.main_tab_widget.addTab(tab_subtitle, "💬 Subtitle Style")

        # Tab 2: Image Layers
        tab_layers = QWidget()
        tab_layers_lay = QVBoxLayout(tab_layers)
        tab_layers_lay.setContentsMargins(6, 6, 6, 6)
        tab_layers_lay.setSpacing(6)

        self.layer_tab_widget = QTabWidget()
        self.layer_tab_widget.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #cbd5e1; border-radius: 4px; background: #f8fafc; }"
            "QTabBar::tab { font-size: 10px; font-weight: bold; padding: 4px 10px; background: #e2e8f0; color: #475569; border: 1px solid #cbd5e1; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; }"
            "QTabBar::tab:selected { background: #f8fafc; color: #2563eb; border-bottom: 2px solid #2563eb; }"
        )

        self.logo_layers = []
        for i in range(1, 6):
            ctrl = ImageLayerControl(i)
            ctrl.changed.connect(self._on_logo_settings_changed)
            self.logo_layers.append(ctrl)
            self.layer_tab_widget.addTab(ctrl, f"Layer {i}")

        tab_layers_lay.addWidget(self.layer_tab_widget)
        self.main_tab_widget.addTab(tab_layers, "🖼️ Image Layers")
        sub_lay.addWidget(self.main_tab_widget)

        # Preview Group
        grp_preview = QGroupBox("🖼  Preview")
        grp_preview.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        preview_lay = QVBoxLayout(grp_preview)
        preview_lay.setSpacing(6)

        self.preview_widget = self.style_panel._preview
        self.preview_widget.setMinimumHeight(180)
        self.preview_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.preview_widget.clicked.connect(self._on_refresh_preview_frame)
        self.preview_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_widget.setToolTip("Click vào đây để tải/làm mới khung hình xem trước từ video")
        preview_lay.addWidget(self.preview_widget)

        preview_ctrl = QHBoxLayout()
        preview_ctrl.setSpacing(6)
        preview_ctrl.addStretch()
        self.btn_refresh_frame = QPushButton("🔄  Load frame from video")
        self.btn_refresh_frame.setStyleSheet("font-size: 12px;")
        self.btn_refresh_frame.setToolTip("Extract a frame from the first video as preview background")
        self.btn_refresh_frame.clicked.connect(self._on_refresh_preview_frame)
        preview_ctrl.addWidget(self.btn_refresh_frame)
        preview_lay.addLayout(preview_ctrl)

        sub_lay.addWidget(grp_preview, 1)
        self.style_panel.hide_preset_bar()
        self.preview_widget.set_style(self.style_panel.get_style())
        lay.addWidget(self.middle_sub_container)

        # 2. Edit Video Container
        self.middle_video_container = QWidget()
        vid_lay = QVBoxLayout(self.middle_video_container)
        vid_lay.setContentsMargins(10, 10, 10, 10)
        vid_lay.setSpacing(10)

        # Tab Widget for 5 Video Layers
        self.video_tab_widget = QTabWidget()
        self.video_tab_widget.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #cbd5e1; border-radius: 4px; background: white; }"
            "QTabBar::tab { font-size: 11px; font-weight: 600; padding: 6px 16px; background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; min-width: 100px; }"
            "QTabBar::tab:selected { background: white; color: #2563eb; border-bottom: 2px solid #2563eb; }"
        )

        self.video_layer_widgets = []
        for i in range(1, 6):
            widget = VideoLayerConfigWidget(i)
            widget.changed.connect(self._on_video_layer_changed)
            self.video_layer_widgets.append(widget)
            self.video_tab_widget.addTab(widget, f"Video Layer {i}")

        vid_lay.addWidget(self.video_tab_widget)

        # Video Layout Preview Box
        grp_vid_preview = QGroupBox("🖼  Preview (Kéo/Thả/Scale & Cắt khung trực tiếp)")
        grp_vid_preview.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        vid_preview_lay = QVBoxLayout(grp_vid_preview)
        vid_preview_lay.setSpacing(6)

        self.video_layout_preview = VideoLayoutPreview()
        self.video_layout_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.video_layout_preview.layerSelected.connect(self._on_preview_layer_selected)
        self.video_layout_preview.layerMoved.connect(self._on_preview_layer_moved)
        self.video_layout_preview.layerResized.connect(self._on_preview_layer_resized)
        self.video_layout_preview.layerCropped.connect(self._on_preview_layer_cropped)
        vid_preview_lay.addWidget(self.video_layout_preview)

        # Video Preview controls
        vid_preview_ctrl = QHBoxLayout()
        vid_preview_ctrl.setSpacing(6)
        vid_preview_ctrl.addStretch()
        
        self.btn_vid_crop_mode = QPushButton("✂  Bật Crop Mode")
        self.btn_vid_crop_mode.setCheckable(True)
        self.btn_vid_crop_mode.setStyleSheet(
            "QPushButton { background: #1e293b; color: #f59e0b; border: 1px solid #f59e0b; "
            "padding: 4px 12px; border-radius: 4px; font-size: 11px; font-weight: bold; }"
            "QPushButton:checked { background: #f59e0b; color: #000000; }"
        )
        self.btn_vid_crop_mode.clicked.connect(self._toggle_video_crop_mode)
        vid_preview_ctrl.addWidget(self.btn_vid_crop_mode)
        vid_preview_lay.addLayout(vid_preview_ctrl)

        vid_lay.addWidget(grp_vid_preview, 1)
        lay.addWidget(self.middle_video_container)
        self.middle_video_container.setVisible(False)

        return panel

    def _on_style_changed(self, style: SubtitleStylePreset):
        """Sync style changes from style_panel to preview_widget."""
        if hasattr(self, "preview_widget"):
            self.preview_widget.set_style(style)
        self._active_preset = None  # mark as modified (not from preset)

    def _on_logo_changed(self, files):
        self._on_logo_settings_changed()

    def _on_logo_settings_changed(self):
        if not hasattr(self, "preview_widget") or not hasattr(self, "logo_layers") or not self.logo_layers:
            return
        
        configs = []
        for idx, ctrl in enumerate(self.logo_layers):
            cfg_obj = ctrl.get_config()
            configs.append(cfg_obj)
            
            # Update tab text with active dot indicator
            status = " (•)" if cfg_obj.enabled and cfg_obj.path else ""
            self.layer_tab_widget.setTabText(idx, f"Layer {idx+1}{status}")
            
        self.preview_widget.set_logo_layers(configs)
        self._save_settings()

    # ---- Right panel — Render + Log + Controls ----

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMaximumWidth(240)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # --- Render settings ---
        grp_render = QGroupBox("⚙️  Cài đặt Render")
        grp_render.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        r_lay = QVBoxLayout(grp_render)
        r_lay.setSpacing(6)
        r_lay.setContentsMargins(10, 10, 10, 10)

        codec_lbl = QLabel("Codec xuất:")
        codec_lbl.setStyleSheet("font-size: 11px;")
        r_lay.addWidget(codec_lbl)

        self.cmb_codec = QComboBox()
        for label, _ in CODECS:
            self.cmb_codec.addItem(label)
        self.cmb_codec.setStyleSheet("font-size: 11px;")
        r_lay.addWidget(self.cmb_codec)

        speed_lbl = QLabel("Tốc độ chậm của video nền:")
        speed_lbl.setStyleSheet("font-size: 11px;")
        r_lay.addWidget(speed_lbl)

        speed_row = QHBoxLayout()
        speed_row.setSpacing(6)

        min_lbl = QLabel("Min:")
        min_lbl.setStyleSheet("font-size: 11px;")
        speed_row.addWidget(min_lbl)

        self.spn_slow_min = QDoubleSpinBox()
        self.spn_slow_min.setRange(10, 80)
        self.spn_slow_min.setValue(35.0)
        self.spn_slow_min.setSingleStep(1.0)
        self.spn_slow_min.setStyleSheet("font-size: 11px;")
        speed_row.addWidget(self.spn_slow_min, 1)

        max_lbl = QLabel("Max:")
        max_lbl.setStyleSheet("font-size: 11px;")
        speed_row.addWidget(max_lbl)

        self.spn_slow_max = QDoubleSpinBox()
        self.spn_slow_max.setRange(10, 80)
        self.spn_slow_max.setValue(45.0)
        self.spn_slow_max.setSingleStep(1.0)
        self.spn_slow_max.setStyleSheet("font-size: 11px;")
        speed_row.addWidget(self.spn_slow_max, 1)

        r_lay.addLayout(speed_row)

        slow_hint = QLabel(
            "ℹ️  Ví dụ: 40% = video nền chạy chậm 40% so với gốc"
        )
        slow_hint.setWordWrap(True)
        slow_hint.setStyleSheet("font-size: 10px; color: #6b7280;")
        r_lay.addWidget(slow_hint)
        lay.addWidget(grp_render)



        # --- Timing Tools ---
        grp_timing = QGroupBox("⏱  Timing Tools")
        grp_timing.setStyleSheet("QGroupBox { font-size: 13px; font-weight: 600; }")
        timing_lay = QHBoxLayout(grp_timing)
        timing_lay.setSpacing(6)

        self.btn_first_to_zero = QPushButton("⏮  Shift To 0s")
        self.btn_first_to_zero.setFixedWidth(115)
        self.btn_first_to_zero.setStyleSheet("font-size: 11px;")
        self.btn_first_to_zero.setToolTip(
            "Shift the entire subtitle timeline so the first subtitle starts at 0s."
        )
        self.btn_first_to_zero.clicked.connect(self._on_first_sub_to_zero)
        timing_lay.addWidget(self.btn_first_to_zero)

        self.btn_undo_timing = QPushButton("↩  Undo")
        self.btn_undo_timing.setFixedWidth(55)
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

        self.btn_render = QPushButton("▶  Bắt đầu Render")
        self.btn_render.setMinimumHeight(38)
        self.btn_render.setStyleSheet(
            "QPushButton { background: #2563eb; color: white; font-size: 13px; "
            "font-weight: 600; border-radius: 6px; border: none; }"
            "QPushButton:hover { background: #1d4ed8; }"
            "QPushButton:disabled { background: #93c5fd; }"
        )
        self.btn_render.clicked.connect(self._start_render)
        ctrl_lay.addWidget(self.btn_render)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_export = QPushButton("📤  Xuất JSON")
        self.btn_export.setMinimumHeight(32)
        self.btn_export.setStyleSheet(
            "QPushButton { background: #059669; color: white; font-size: 11px; "
            "font-weight: 600; border-radius: 5px; border: none; }"
            "QPushButton:hover { background: #047857; }"
        )
        self.btn_export.clicked.connect(self._export_json)
        btn_row.addWidget(self.btn_export, 1)

        self.btn_pause = QPushButton("⏸  Tạm dừng")
        self.btn_pause.setMinimumHeight(32)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setStyleSheet(
            "QPushButton { background: #f59e0b; color: white; font-size: 11px; "
            "border-radius: 5px; border: none; }"
            "QPushButton:hover { background: #d97706; }"
            "QPushButton:disabled { background: #fcd34d; }"
        )
        self.btn_pause.clicked.connect(self._toggle_pause_render)
        btn_row.addWidget(self.btn_pause, 1)

        self.btn_stop = QPushButton("⏹  Dừng")
        self.btn_stop.setMinimumHeight(32)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "QPushButton { background: #dc2626; color: white; font-size: 11px; "
            "border-radius: 5px; border: none; }"
            "QPushButton:hover { background: #b91c1c; }"
            "QPushButton:disabled { background: #fca5a5; }"
        )
        self.btn_stop.clicked.connect(self._stop_render)
        btn_row.addWidget(self.btn_stop, 1)

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

        # Restore Edit Video Folder paths
        self.pick_vid_src.set_value(s.get("vid_src_folder", ""))
        self.pick_vid_bg.set_value(s.get("vid_bg_folder", ""))
        self.pick_vid_output.set_value(s.get("vid_output_folder", ""))

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

        # Restore logo settings (3 layers)
        for idx, ctrl in enumerate(self.logo_layers):
            layer_num = idx + 1
            ctrl.chk_enabled.setChecked(s.get(f"logo_enabled_{layer_num}", False))
            
            logo_path = s.get(f"logo_path_{layer_num}", "")
            if logo_path:
                ctrl.pick_logo.set_selected_files([logo_path])
                ctrl.pick_logo.edit.setText(Path(logo_path).name)
            else:
                ctrl.pick_logo.set_selected_files([])
                ctrl.pick_logo.edit.clear()
                
            ctrl.cmb_logo_pos.setCurrentIndex(s.get(f"logo_position_{layer_num}", 0))
            ctrl.spn_logo_size.setValue(s.get(f"logo_size_{layer_num}", 100))
            ctrl.spn_logo_opacity.setValue(s.get(f"logo_opacity_{layer_num}", 90))
            ctrl.spn_margin_t.setValue(s.get(f"logo_margin_t_{layer_num}", 20))
            ctrl.spn_margin_b.setValue(s.get(f"logo_margin_b_{layer_num}", 20))
            ctrl.spn_margin_l.setValue(s.get(f"logo_margin_l_{layer_num}", 20))
            ctrl.spn_margin_r.setValue(s.get(f"logo_margin_r_{layer_num}", 20))
            
        self._on_logo_settings_changed()

        # Restore Edit Video layers (5 layers)
        for idx, widget in enumerate(self.video_layer_widgets):
            layer_num = idx + 1
            widget.chk_enabled.setChecked(s.get(f"vlayer_enabled_{layer_num}", layer_num in (1, 2, 3)))
            
            src_type = s.get(f"vlayer_source_type_{layer_num}", 0 if layer_num == 1 else 1 if layer_num == 2 else 2)
            widget.cmb_source_type.setCurrentIndex(src_type)
            
            path_val = s.get(f"vlayer_path_{layer_num}", "logo.png" if layer_num == 3 else "")
            widget.edit_path.setText(path_val)
            
            widget.cmb_pos.setCurrentIndex(s.get(f"vlayer_position_{layer_num}", 0 if layer_num in (1, 2) else 1)) # Combo 0 is Center, 1 is BR
            widget.spn_size.setValue(s.get(f"vlayer_size_{layer_num}", 100 if layer_num == 1 else 40 if layer_num == 2 else 15))
            widget.spn_opacity.setValue(s.get(f"vlayer_opacity_{layer_num}", 90 if layer_num == 1 else 100))
            
            widget.spn_margin_t.setValue(s.get(f"vlayer_margin_t_{layer_num}", 0 if layer_num == 1 else 20))
            widget.spn_margin_b.setValue(s.get(f"vlayer_margin_b_{layer_num}", 0 if layer_num == 1 else 20))
            widget.spn_margin_l.setValue(s.get(f"vlayer_margin_l_{layer_num}", 0 if layer_num == 1 else 20))
            widget.spn_margin_r.setValue(s.get(f"vlayer_margin_r_{layer_num}", 0 if layer_num == 1 else 20))
            
            widget.spn_crop_t.setValue(s.get(f"vlayer_crop_t_{layer_num}", 0))
            widget.spn_crop_b.setValue(s.get(f"vlayer_crop_b_{layer_num}", 0))
            widget.spn_crop_l.setValue(s.get(f"vlayer_crop_l_{layer_num}", 0))
            widget.spn_crop_r.setValue(s.get(f"vlayer_crop_r_{layer_num}", 0))

        self._on_video_layer_changed()

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
        settings_dict = {
            "bg_folder": self.pick_bg.value(),
            "bg_files": self.pick_bg.selected_files(),
            "audio_files": self.pick_audio.selected_files(),
            "srt_files": self.pick_srt.selected_files(),
            "output_folder": self.pick_output.value(),
            "vid_src_folder": self.pick_vid_src.value(),
            "vid_bg_folder": self.pick_vid_bg.value(),
            "vid_output_folder": self.pick_vid_output.value(),
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
        }

        # Save 3 layers logo settings
        for idx, ctrl in enumerate(self.logo_layers):
            layer_num = idx + 1
            cfg_obj = ctrl.get_config()
            settings_dict[f"logo_enabled_{layer_num}"] = cfg_obj.enabled
            settings_dict[f"logo_path_{layer_num}"] = cfg_obj.path
            settings_dict[f"logo_position_{layer_num}"] = cfg_obj.position
            settings_dict[f"logo_size_{layer_num}"] = cfg_obj.size
            settings_dict[f"logo_opacity_{layer_num}"] = int(cfg_obj.opacity * 100)
            settings_dict[f"logo_margin_t_{layer_num}"] = cfg_obj.margin_t
            settings_dict[f"logo_margin_b_{layer_num}"] = cfg_obj.margin_b
            settings_dict[f"logo_margin_l_{layer_num}"] = cfg_obj.margin_l
            settings_dict[f"logo_margin_r_{layer_num}"] = cfg_obj.margin_r

        # Save Edit Video layers (5 layers)
        for idx, widget in enumerate(self.video_layer_widgets):
            layer_num = idx + 1
            cfg_obj = widget.get_config()
            settings_dict[f"vlayer_enabled_{layer_num}"] = cfg_obj.enabled
            settings_dict[f"vlayer_source_type_{layer_num}"] = widget.cmb_source_type.currentIndex()
            settings_dict[f"vlayer_path_{layer_num}"] = widget.edit_path.text()
            settings_dict[f"vlayer_position_{layer_num}"] = widget.cmb_pos.currentIndex()
            settings_dict[f"vlayer_size_{layer_num}"] = cfg_obj.size
            settings_dict[f"vlayer_opacity_{layer_num}"] = int(cfg_obj.opacity * 100)
            settings_dict[f"vlayer_margin_t_{layer_num}"] = cfg_obj.margin_t
            settings_dict[f"vlayer_margin_b_{layer_num}"] = cfg_obj.margin_b
            settings_dict[f"vlayer_margin_l_{layer_num}"] = cfg_obj.margin_l
            settings_dict[f"vlayer_margin_r_{layer_num}"] = cfg_obj.margin_r
            settings_dict[f"vlayer_crop_t_{layer_num}"] = cfg_obj.crop_t
            settings_dict[f"vlayer_crop_b_{layer_num}"] = cfg_obj.crop_b
            settings_dict[f"vlayer_crop_l_{layer_num}"] = cfg_obj.crop_l
            settings_dict[f"vlayer_crop_r_{layer_num}"] = cfg_obj.crop_r

        # Legacy fallback
        if self.logo_layers:
            layer1 = self.logo_layers[0].get_config()
            settings_dict["logo_path"] = layer1.path
            settings_dict["logo_files"] = [layer1.path] if layer1.path else []
            settings_dict["logo_position"] = layer1.position
            settings_dict["logo_size"] = layer1.size
            settings_dict["logo_opacity"] = int(layer1.opacity * 100)

        cfg.save(settings_dict)
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

        # Automatically select the first row to trigger the preview
        if total > 0:
            self.pair_table.selectRow(0)

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
        if hasattr(self.style_panel, "_cmb_preset"):
            self.style_panel._cmb_preset.setCurrentText(preset.name)
        self._active_preset = preset

    def _on_delete_preset_inline(self):
        """Delete current preset from both editor and main preset list."""
        name = self.style_panel._cmb_preset.currentText()
        if not name:
            return
        if name in self.style_panel.PRESETS_BUILTIN:
            QMessageBox.information(
                self, "Xóa preset",
                "Preset mặc định không thể xóa."
            )
            return
        self.style_panel._delete_preset()
        idx = self.cmb_preset.findText(name)
        if idx >= 0:
            self.cmb_preset.removeItem(idx)

    def _on_reset_defaults_inline(self):
        """Reset current preset back to built-in default."""
        self.style_panel._reset_defaults()
        self.cmb_preset.setCurrentText("Classic")
        if hasattr(self.style_panel, "_on_changed"):
            self.style_panel._on_changed()

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
        
        if self.btn_tab_video.isChecked():
            # Edit Video mode configurations
            configs = []
            for ctrl in self.video_layer_widgets:
                configs.append(ctrl.get_config())
                
            return RenderConfig(
                bg_folder="",
                bg_videos=self.pick_vid_bg.selected_files(),
                audio_folder="",
                srt_folder="",
                output_folder=self.pick_vid_output.value(),
                subtitle_style=SubtitleStyle(font_size=0, stroke_enabled=False, bg_enabled=False),
                slow_min=self.spn_slow_min.value(),
                slow_max=self.spn_slow_max.value(),
                codec=codec_val,
                use_gpu="nvenc" in codec_val,
                logo_path=None,
                layers=configs
            )
        else:
            preset = self.style_panel.get_style()
            style = SubtitleStyle.from_preset(preset)
            
            configs = []
            for ctrl in self.logo_layers:
                configs.append(ctrl.get_config())
                
            layer1 = configs[0] if configs else None
            
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
                logo_path=layer1.path if (layer1 and layer1.enabled) else None,
                logo_position=layer1.position if layer1 else 0,
                logo_size=layer1.size if layer1 else 100,
                logo_opacity=layer1.opacity if layer1 else 0.8,
                layers=configs
            )

    def _validate(self) -> bool:
        errs = []
        if self.btn_tab_video.isChecked():
            # Validate Edit Video mode
            if not self.pick_vid_src.value():
                errs.append("• Chưa chọn thư mục video nguồn để scale")
            if not self.pick_vid_output.value():
                errs.append("• Chưa chọn thư mục Output")
            if not self._pairs:
                errs.append("• Chưa có video nào trong danh sách (hãy quét lại)")
        else:
            # Validate Edit Sub mode
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
        # Filter matching pairs based on active tab and checked rows
        matched_pairs = []
        table = self.vid_batch_table if self.btn_tab_video.isChecked() else self.pair_table
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                if row < len(self._pairs):
                    p = self._pairs[row]
                    if p.matched:
                        matched_pairs.append(p)

        if not matched_pairs:
            QMessageBox.warning(self, "Cảnh báo", "Bạn chưa chọn bất kỳ video nào để render!")
            return

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
        if not hasattr(self, "preview_widget"):
            return
        if not video_files:
            self.preview_widget.set_frame(None)
            return
        frame = _extract_video_frame(video_files[0])
        self.preview_widget.set_frame(frame)

    def _on_pair_selection_changed(self):
        """Update preview background and subtitle text when a pair is selected in the table."""
        selected_ranges = self.pair_table.selectedRanges()
        if not selected_ranges:
            return
        row = selected_ranges[0].topRow()
        if row < 0 or row >= len(self._pairs):
            return

        pair = self._pairs[row]
        if not pair.matched:
            return

        # 1. Load SRT file to preview
        if pair.srt_path and os.path.exists(pair.srt_path):
            self.style_panel.reload_srt(pair.srt_path)

        # 2. Extract a frame from the first background video as preview
        self._on_refresh_preview_frame()

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
                if hasattr(self, "preview_widget"):
                    self.preview_widget.reload_srt_entries(srt_files[0])
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

    # ------------------------------------------------------------------
    # Edit Video Interactive Event Slots
    # ------------------------------------------------------------------

    def _on_mode_sub_clicked(self):
        self.btn_tab_sub.setChecked(True)
        self.btn_tab_sub.setStyleSheet(
            "QPushButton { background: #ffffff; color: #2563eb; font-weight: bold; border: none; border-bottom: 2px solid #2563eb; font-size: 12px; }"
        )
        self.btn_tab_video.setChecked(False)
        self.btn_tab_video.setStyleSheet(
            "QPushButton { background: #f1f5f9; color: #475569; font-weight: bold; border: none; font-size: 12px; }"
        )
        
        self.left_sub_container.setVisible(True)
        self.left_video_container.setVisible(False)
        self.middle_sub_container.setVisible(True)
        self.middle_video_container.setVisible(False)
        
        self._scan_pairs()

    def _on_mode_video_clicked(self):
        self.btn_tab_sub.setChecked(False)
        self.btn_tab_sub.setStyleSheet(
            "QPushButton { background: #f1f5f9; color: #475569; font-weight: bold; border: none; font-size: 12px; }"
        )
        self.btn_tab_video.setChecked(True)
        self.btn_tab_video.setStyleSheet(
            "QPushButton { background: #ffffff; color: #2563eb; font-weight: bold; border: none; border-bottom: 2px solid #2563eb; font-size: 12px; }"
        )
        
        self.left_sub_container.setVisible(False)
        self.left_video_container.setVisible(True)
        self.middle_sub_container.setVisible(False)
        self.middle_video_container.setVisible(True)
        
        self._on_video_layer_changed()
        self._scan_video_batch()

    def _on_video_selection_change(self, _val):
        self._scan_video_batch()

    def _scan_video_batch(self):
        src_files = self.pick_vid_src.selected_files()
        if not src_files and self.pick_vid_src.value():
            folder_path = self.pick_vid_src.value()
            if os.path.isdir(folder_path):
                import glob
                extensions = ["*.mp4", "*.mkv", "*.mov", "*.avi", "*.webm", "*.m4v"]
                src_files = []
                for ext in extensions:
                    src_files.extend(glob.glob(os.path.join(folder_path, ext)))
                    src_files.extend(glob.glob(os.path.join(folder_path, ext.upper())))
                src_files = sorted(list(set(src_files)))

        self._pairs = []
        self.vid_batch_table.setRowCount(0)
        
        if not src_files:
            self.lbl_vid_summary.setText("Tìm thấy 0 video")
            return

        for idx, file_path in enumerate(src_files):
            row = self.vid_batch_table.rowCount()
            self.vid_batch_table.insertRow(row)
            
            item_idx = QTableWidgetItem(str(idx + 1))
            item_idx.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_idx.setFlags(item_idx.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item_idx.setCheckState(Qt.CheckState.Checked)
            self.vid_batch_table.setItem(row, 0, item_idx)
            
            self.vid_batch_table.setItem(row, 1, QTableWidgetItem(os.path.basename(file_path)))
            self.vid_batch_table.setItem(row, 2, QTableWidgetItem("1280x720 (16:9)"))
            
            item_status = QTableWidgetItem("Sẵn sàng")
            item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_status.setForeground(QColor("#2563eb"))
            self.vid_batch_table.setItem(row, 3, item_status)

            self._pairs.append(FilePair(
                index=str(idx + 1),
                audio_path=file_path,
                srt_path="",
                matched=True
            ))

        self.lbl_vid_summary.setText(f"Tìm thấy {len(src_files)} video — {len(src_files)} sẵn sàng")
        if src_files:
            self.vid_batch_table.selectRow(0)

    def _on_video_batch_selection_changed(self):
        self._update_video_preview_frames()

    def _on_video_layer_changed(self):
        """Build layer configs and pass them to VideoLayoutPreview."""
        if not hasattr(self, "video_layout_preview") or not hasattr(self, "video_layer_widgets"):
            return
        
        configs = {}
        for idx, widget in enumerate(self.video_layer_widgets):
            layer_num = idx + 1
            configs[layer_num] = widget.get_config()
            status = " (•)" if configs[layer_num].enabled else ""
            self.video_tab_widget.setTabText(idx, f"Layer {layer_num}{status}")

        self.video_layout_preview.set_configs(configs)
        self._update_video_preview_frames()
        self._save_settings()

    def _update_video_preview_frames(self):
        if not hasattr(self, "video_layout_preview") or not hasattr(self, "video_layer_widgets"):
            return

        if not hasattr(self, "_video_frame_cache"):
            self._video_frame_cache = {}

        def get_cached_frame(path):
            if not path or not os.path.exists(path):
                return None
            if path in self._video_frame_cache:
                return self._video_frame_cache[path]
            
            lower_path = path.lower()
            if any(lower_path.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".bmp", ".webp"]):
                img = QImage(path)
                if not img.isNull():
                    self._video_frame_cache[path] = img
                    return img
            
            # Asynchronous extraction for videos to prevent UI freezing
            if path in self.running_extractions:
                return None
            
            self.running_extractions.add(path)
            task = FrameExtractTask(path)
            task.signals.loaded.connect(self._on_frame_loaded)
            self.frame_pool.start(task)
            return None

        # 1. Update background frame
        bg_files = self.pick_vid_bg.selected_files()
        bg_img = None
        if bg_files:
            bg_img = get_cached_frame(bg_files[0])
        self.video_layout_preview.set_bg_image(bg_img)

        # 2. Update each of the 5 layers
        for idx, widget in enumerate(self.video_layer_widgets):
            layer_num = idx + 1
            cfg_obj = widget.get_config()
            
            layer_img = None
            if cfg_obj.enabled:
                src_idx = widget.cmb_source_type.currentIndex()
                if src_idx == 0:  # Video nền (Background video)
                    bg_files = self.pick_vid_bg.selected_files()
                    if bg_files:
                        layer_img = get_cached_frame(bg_files[0])
                elif src_idx == 1:  # Theo danh sách chạy (Video nguồn)
                    selected_ranges = self.vid_batch_table.selectedRanges()
                    if selected_ranges:
                        row = selected_ranges[0].topRow()
                        if 0 <= row < len(self._pairs):
                            batch_video_path = self._pairs[row].audio_path
                            layer_img = get_cached_frame(batch_video_path)
                else:  # File tĩnh (Static file)
                    static_path = widget.edit_path.text().strip()
                    if static_path:
                        layer_img = get_cached_frame(static_path)
            
            self.video_layout_preview.set_layer_image(layer_num, layer_img)

    def _on_frame_loaded(self, path: str, image: QImage):
        if path in self.running_extractions:
            self.running_extractions.remove(path)
        if image and not image.isNull():
            self._video_frame_cache[path] = image
            self._update_video_preview_frames()

    def _on_preview_layer_selected(self, index: int):
        if 1 <= index <= 5:
            self.video_tab_widget.setCurrentIndex(index - 1)

    def _on_preview_layer_moved(self, index: int, t: int, b: int, l: int, r: int):
        widget = self.video_layer_widgets[index - 1]
        widget.spn_margin_t.blockSignals(True)
        widget.spn_margin_t.setValue(t)
        widget.spn_margin_t.blockSignals(False)

        widget.spn_margin_b.blockSignals(True)
        widget.spn_margin_b.setValue(b)
        widget.spn_margin_b.blockSignals(False)

        widget.spn_margin_l.blockSignals(True)
        widget.spn_margin_l.setValue(l)
        widget.spn_margin_l.blockSignals(False)

        widget.spn_margin_r.blockSignals(True)
        widget.spn_margin_r.setValue(r)
        widget.spn_margin_r.blockSignals(False)

        self._on_video_layer_changed()

    def _on_preview_layer_resized(self, index: int, scale_pct: int):
        widget = self.video_layer_widgets[index - 1]
        widget.spn_size.blockSignals(True)
        widget.spn_size.setValue(scale_pct)
        widget.spn_size.blockSignals(False)

        self._on_video_layer_changed()

    def _on_preview_layer_cropped(self, index: int, t: int, b: int, l: int, r: int):
        widget = self.video_layer_widgets[index - 1]
        widget.spn_crop_t.blockSignals(True)
        widget.spn_crop_t.setValue(t)
        widget.spn_crop_t.blockSignals(False)

        widget.spn_crop_b.blockSignals(True)
        widget.spn_crop_b.setValue(b)
        widget.spn_crop_b.blockSignals(False)

        widget.spn_crop_l.blockSignals(True)
        widget.spn_crop_l.setValue(l)
        widget.spn_crop_l.blockSignals(False)

        widget.spn_crop_r.blockSignals(True)
        widget.spn_crop_r.setValue(r)
        widget.spn_crop_r.blockSignals(False)

        self._on_video_layer_changed()

    def _toggle_video_crop_mode(self, enabled: bool):
        self.video_layout_preview.set_crop_mode(enabled)
        if enabled:
            self.btn_vid_crop_mode.setText("✓  Đang Crop (Tắt)")
        else:
            self.btn_vid_crop_mode.setText("✂  Bật Crop Mode")

    def _pair_select_all(self):
        for row in range(self.pair_table.rowCount()):
            item = self.pair_table.item(row, 0)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Checked)

    def _pair_deselect_all(self):
        for row in range(self.pair_table.rowCount()):
            item = self.pair_table.item(row, 0)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _vid_select_all(self):
        for row in range(self.vid_batch_table.rowCount()):
            item = self.vid_batch_table.item(row, 0)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Checked)

    def _vid_deselect_all(self):
        for row in range(self.vid_batch_table.rowCount()):
            item = self.vid_batch_table.item(row, 0)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _on_table_item_changed(self, item):
        if item.column() != 0:
            return
        table = self.sender()
        if not table:
            return
        table.blockSignals(True)
        try:
            selected_ranges = table.selectedRanges()
            if selected_ranges:
                state = item.checkState()
                clicked_row = item.row()
                
                # Check if clicked row is part of the selected ranges
                in_selection = False
                for r in selected_ranges:
                    if r.topRow() <= clicked_row <= r.bottomRow():
                        in_selection = True
                        break
                        
                if in_selection:
                    for r in selected_ranges:
                        for row in range(r.topRow(), r.bottomRow() + 1):
                            idx_item = table.item(row, 0)
                            if idx_item and idx_item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                                idx_item.setCheckState(state)
        finally:
            table.blockSignals(False)

    def closeEvent(self, event):
        self._save_settings()
        self.frame_pool.clear()
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(3000)
        event.accept()
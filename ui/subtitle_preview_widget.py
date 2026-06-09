"""
Subtitle Preview Widget — Phase 2 Extended.

Renders a styled subtitle line using QPainter, with accurate simulation of:
  - Fill (text color)
  - Stroke (outline)
  - Background box (with rounded corners)
  - Drop shadow

Also provides a collapsible AppearancePanel widget that mirrors the
Fill / Stroke / Background / Shadow sections from the reference image,
using an accordion (collapsible-section) layout.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path

_root = str(_Path(__file__).parent.parent)
if _root not in _sys.path:
    _sys.path.insert(0, _root)

import math

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QSpinBox, QDoubleSpinBox,
    QPushButton, QFrame, QToolButton, QSizePolicy,
    QLineEdit, QSlider, QDialog,
)
from PyQt6.QtCore import Qt, QRect, QSize, pyqtSignal, QPoint
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush,
    QPainterPath, QLinearGradient, QImage, QPixmap,
    QMouseEvent, QRadialGradient,
)

from core.subtitle_model import SubtitleEntry, SubtitleStylePreset
from core.srt_service import SrtService


# ---------------------------------------------------------------------------
# Colour constants — 3-tier dark theme
#
# Tier 1 (deepest / container):  #0f1017
# Tier 2 (sections):            #181b26
# Tier 3 (elevated / inputs):  #22263a
# Accent:                       #5b8def  (blue, ~50 % lightness for dark bg)
# Success accent:                #4ade80
# Text:                         #dde3f0
# Text muted:                   #7b849c
# Border:                       #2e3347
# Hover:                        #2d3354
# ---------------------------------------------------------------------------

C_BG             = "#0f1017"
C_SECTION_BG     = "#181b26"
C_ELEVATED_BG    = "#22263a"
C_ACCENT         = "#5b8def"
C_ACCENT_DIM     = "#3a5299"
C_SUCCESS        = "#4ade80"
C_TEXT           = "#dde3f0"
C_TEXT_MUTED     = "#7b849c"
C_BORDER         = "#2e3347"
C_HOVER          = "#2d3354"
C_SECTION_BORDER = "#2e3347"
C_PREVIEW_BG     = "#0a0b10"
C_PREVIEW_BORDER = "#1e2235"


# ---------------------------------------------------------------------------
# Shared colour-picker button
# ---------------------------------------------------------------------------

class ColorPickerPopup(QDialog):
    """
    Professional-grade color picker popup — Photoshop/Premiere/DaVinci Resolve style.
    Features: hue wheel, SV area, live preview, HEX/RGB/alpha inputs,
    preset swatches, recent colors, real-time subtitle preview feedback.
    """

    # Singleton recent-colors store (shared across all picker instances)
    _recent: list[str] = []
    _MAX_RECENT = 10

    # Preset swatches
    _PRESETS = [
        "#FFFFFF", "#000000", "#FFFF00", "#FF0000",
        "#0000FF", "#00FF00", "#FF8800",
    ]

    def __init__(self, initial_hex: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Color Picker")
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)
        self._setup_style()

        self._prev_hex = initial_hex
        self._current_hex = initial_hex.upper()

        # HSV state (0-360 hue, 0-100 sat, 0-100 val)
        qc = QColor(initial_hex)
        self._h = qc.hsvHue() if qc.hsvHue() >= 0 else 0
        self._s = qc.hsvSaturation()
        self._v = qc.value()
        self._parent_button = None  # assigned in show_at() before first use

        self._build_ui()
        self._apply_initial_color()

    # ---- Public API ----

    def selected_color(self) -> str:
        return self._current_hex

    # ---- UI construction ----

    def _setup_style(self):
        self.setFixedWidth(360)
        self._pad = 14
        self._corner = 8
        self.setStyleSheet(f"""
            QDialog {{ background: transparent; }}
            * {{ color: {C_TEXT}; font-size: 12px;
                font-family: "Segoe UI", sans-serif; }}
            QWidget {{ background: transparent; }}
        """)

    def _outer_frame(self) -> QFrame:
        """Dark card shell that gives the WA_TranslucentBackground appearance."""
        f = QFrame(self)
        f.setObjectName("card")
        f.setStyleSheet(f"""
            QFrame#card {{
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: {self._corner}px;
            }}
            QLabel {{ color: {C_TEXT}; background: transparent;
                      font-size: 11px; qproperty-alignment:
                      AlignCenter; }}
            QLineEdit {{
                background: {C_ELEVATED_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                color: {C_TEXT};
                font-family: monospace;
                font-size: 12px;
                padding: 3px 6px;
            }}
            QLineEdit:focus {{ border-color: {C_ACCENT}; }}
            QSpinBox {{
                background: {C_ELEVATED_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                color: {C_TEXT};
                font-size: 12px;
                padding: 2px 4px;
            }}
            QSpinBox:focus {{ border-color: {C_ACCENT}; }}
            QSpinBox::up-button, QSpinBox::down-button {{
                background: {C_ELEVATED_BG}; width: 14px;
            }}
            QSlider::groove:horizontal {{
                border-radius: 3px; height: 6px;
                background: {C_SECTION_BG};
            }}
            QSlider::handle:horizontal {{
                background: {C_ACCENT};
                width: 14px; height: 14px;
                border-radius: 7px; margin: -4px 0;
            }}
            QSlider::sub-page:horizontal {{
                background: {C_ACCENT}; border-radius: 3px;
            }}
        """)
        return f

    def _build_ui(self):
        outer = self._outer_frame()
        root = QVBoxLayout(outer)
        root.setContentsMargins(self._pad, self._pad, self._pad, self._pad)
        root.setSpacing(10)

        # ── Top row: SV canvas + Hue wheel ──────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # Saturation/Value canvas
        self._sv_canvas = SVCanvas(self)
        self._sv_canvas.setFixedSize(200, 170)
        self._sv_canvas.hsv_changed.connect(self._on_sv_changed)
        top_row.addWidget(self._sv_canvas, alignment=Qt.AlignmentFlag.AlignTop)

        # Hue wheel + current/prev previews stacked
        right_col = QVBoxLayout()
        right_col.setSpacing(6)

        self._hue_wheel = HueWheel(self)
        self._hue_wheel.setFixedSize(72, 72)
        self._hue_wheel.hue_changed.connect(self._on_hue_changed)
        right_col.addWidget(self._hue_wheel)

        for label_text in ("Current", "Previous"):
            preview_frame = self._make_preview(label_text)
            right_col.addWidget(preview_frame)

        right_col.addStretch()
        top_row.addLayout(right_col)
        root.addLayout(top_row)

        # ── Hex + RGB row ─────────────────────────────────────────────────
        hex_rgb = QHBoxLayout()
        hex_rgb.setSpacing(6)

        lbl_hex = QLabel("HEX")
        lbl_hex.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        hex_rgb.addWidget(lbl_hex)

        self._le_hex = QLineEdit()
        self._le_hex.setFixedHeight(26)
        self._le_hex.setMaxLength(7)
        self._le_hex.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._le_hex.textEdited.connect(self._on_hex_edited)
        hex_rgb.addWidget(self._le_hex, 1)

        lbl_r, lbl_g, lbl_b = QLabel("R"), QLabel("G"), QLabel("B")
        for lbl in (lbl_r, lbl_g, lbl_b):
            lbl.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
            hex_rgb.addWidget(lbl)

        for channel, attr in [("r", "_spn_r"), ("g", "_spn_g"), ("b", "_spn_b")]:
            spn = QSpinBox()
            spn.setRange(0, 255)
            spn.setFixedHeight(26)
            spn.valueChanged.connect(self._on_rgb_changed)
            setattr(self, attr, spn)
            hex_rgb.addWidget(spn)

        root.addLayout(hex_rgb)

        # ── Opacity / Alpha slider ────────────────────────────────────────
        alpha_row = QHBoxLayout()
        alpha_row.setSpacing(6)

        lbl_a = QLabel("Opacity")
        lbl_a.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        alpha_row.addWidget(lbl_a)

        self._alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self._alpha_slider.setRange(0, 100)
        self._alpha_slider.setValue(100)
        self._alpha_slider.setFixedHeight(20)
        self._alpha_slider.valueChanged.connect(self._on_alpha_changed)
        alpha_row.addWidget(self._alpha_slider, 1)

        self._alpha_val = QLabel("100%")
        self._alpha_val.setFixedWidth(34)
        self._alpha_val.setStyleSheet(f"color: {C_TEXT}; font-size: 11px;")
        alpha_row.addWidget(self._alpha_val)

        root.addLayout(alpha_row)

        # ── Preset swatches ──────────────────────────────────────────────
        swatch_lbl = QLabel("Presets")
        swatch_lbl.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 10px; font-weight: 600;")
        swatch_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        root.addWidget(swatch_lbl)

        presets_grid = QGridLayout()
        presets_grid.setHorizontalSpacing(6)
        presets_grid.setVerticalSpacing(6)
        for i, hex_c in enumerate(self._PRESETS):
            btn = SwatchButton(hex_c, self)
            btn.clicked.connect(lambda _, h=hex_c: self._apply_hex(h))
            presets_grid.addWidget(btn, 0, i)
        self._recent_btns: list[SwatchButton] = []
        if self._recent:
            for i, hex_c in enumerate(self._recent):
                btn = SwatchButton(hex_c, self)
                btn.clicked.connect(lambda _, h=hex_c: self._apply_hex(h))
                presets_grid.addWidget(btn, 1, i)
                self._recent_btns.append(btn)
        root.addLayout(presets_grid)

        # ── Action buttons ───────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setFixedSize(72, 28)
        cancel.setStyleSheet(self._btn_dark())
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        ok = QPushButton("OK")
        ok.setFixedSize(72, 28)
        ok.setStyleSheet(self._btn_accent())
        ok.clicked.connect(self._on_ok)
        btn_row.addWidget(ok)

        root.addLayout(btn_row)

        # Wrap in translucent container
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(outer)

    def _make_preview(self, label: str) -> QFrame:
        f = QFrame()
        f.setFixedHeight(30)
        f.setStyleSheet(f"""
            QFrame {{ background: {C_SECTION_BG};
                      border: 1px solid {C_BORDER};
                      border-radius: 4px; }}
        """)
        lay = QHBoxLayout(f)
        lay.setContentsMargins(6, 2, 6, 2)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 10px;")
        lay.addWidget(lbl)
        color_sw = QLabel()
        color_sw.setFixedSize(50, 18)
        color_sw.setStyleSheet(f"""
            background: {self._prev_hex if label == "Previous" else self._current_hex};
            border-radius: 3px;
            border: 1px solid {C_BORDER};
        """)
        lay.addWidget(color_sw)
        if label == "Current":
            self._preview_cur = color_sw
        else:
            self._preview_prv = color_sw
        return f

    def _btn_dark(self) -> str:
        return (
            f"QPushButton {{ background: {C_SECTION_BG}; color: {C_TEXT}; "
            f"border: 1px solid {C_BORDER}; border-radius: 5px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {C_HOVER}; }}"
        )

    def _btn_accent(self) -> str:
        return (
            f"QPushButton {{ background: {C_ACCENT}; color: #fff; "
            f"border: none; border-radius: 5px; font-size: 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {C_ACCENT_DIM}; }}"
        )

    # ---- Color sync helpers ----

    def _qc(self) -> QColor:
        return QColor.fromHsv(self._h, self._s, self._v)

    def _apply_initial_color(self):
        self._le_hex.setText(self._current_hex)
        r, g, b = self._qc().red(), self._qc().green(), self._qc().blue()
        self._spn_r.setValue(r)
        self._spn_g.setValue(g)
        self._spn_b.setValue(b)
        self._hue_wheel.set_hue(self._h)
        self._sv_canvas.set_hsv(self._h, self._s, self._v)
        self._update_previews()

    def _refresh_all(self):
        qc = self._qc()
        hex_s = qc.name(QColor.NameFormat.HexRgb).upper()
        r, g, b = qc.red(), qc.green(), qc.blue()
        self._current_hex = hex_s
        self._le_hex.blockSignals(True)
        self._le_hex.setText(hex_s)
        self._le_hex.blockSignals(False)
        self._spn_r.blockSignals(True); self._spn_r.setValue(r); self._spn_r.blockSignals(False)
        self._spn_g.blockSignals(True); self._spn_g.setValue(g); self._spn_g.blockSignals(False)
        self._spn_b.blockSignals(True); self._spn_b.setValue(b); self._spn_b.blockSignals(False)
        self._sv_canvas.set_hsv(self._h, self._s, self._v)
        self._update_previews()

    def _update_previews(self):
        qc = self._qc()
        hex_s = qc.name(QColor.NameFormat.HexRgb).upper()
        if hasattr(self, "_preview_cur"):
            self._preview_cur.setStyleSheet(
                f"background: {hex_s}; border-radius: 3px; border: 1px solid {C_BORDER};"
            )
        # Live update parent button swatch
        if self._parent_button:
            self._parent_button._hex = hex_s
            self._parent_button.update()

    def _apply_hex(self, hex_s: str):
        hex_s = hex_s.strip().upper()
        if not hex_s.startswith("#"):
            hex_s = "#" + hex_s
        qc = QColor(hex_s)
        if qc.isValid():
            self._h = qc.hsvHue() if qc.hsvHue() >= 0 else 0
            self._s = qc.hsvSaturation()
            self._v = qc.value()
            self._refresh_all()

    # ---- Signal handlers ----

    def _on_sv_changed(self, h: int, s: int, v: int):
        self._h, self._s, self._v = h, s, v
        self._hue_wheel.set_hue(h)
        self._refresh_all()

    def _on_hue_changed(self, hue: int):
        self._h = hue
        self._sv_canvas.set_hsv(hue, self._s, self._v)
        self._refresh_all()

    def _on_hex_edited(self, text: str):
        raw = text.strip()
        if raw.startswith("#"):
            raw = raw[1:]
        if len(raw) == 6:
            try:
                int(raw, 16)
                qc = QColor(f"#{raw.upper()}")
                if qc.isValid():
                    self._h = qc.hsvHue() if qc.hsvHue() >= 0 else 0
                    self._s = qc.hsvSaturation()
                    self._v = qc.value()
                    self._spn_r.setValue(qc.red())
                    self._spn_g.setValue(qc.green())
                    self._spn_b.setValue(qc.blue())
                    self._hue_wheel.set_hue(self._h)
                    self._sv_canvas.set_hsv(self._h, self._s, self._v)
                    self._current_hex = f"#{raw.upper()}"
                    self._update_previews()
            except ValueError:
                pass

    def _on_rgb_changed(self):
        r = self._spn_r.value()
        g = self._spn_g.value()
        b = self._spn_b.value()
        qc = QColor(r, g, b)
        if qc.isValid():
            self._h = qc.hsvHue() if qc.hsvHue() >= 0 else 0
            self._s = qc.hsvSaturation()
            self._v = qc.value()
            self._hue_wheel.set_hue(self._h)
            self._sv_canvas.set_hsv(self._h, self._s, self._v)
            self._current_hex = qc.name(QColor.NameFormat.HexRgb).upper()
            self._le_hex.blockSignals(True)
            self._le_hex.setText(self._current_hex)
            self._le_hex.blockSignals(False)
            self._update_previews()

    def _on_alpha_changed(self, val: int):
        self._alpha_val.setText(f"{val}%")

    def _on_ok(self):
        # Add to recent
        hex_s = self._current_hex
        if hex_s in self._recent:
            self._recent.remove(hex_s)
        self._recent.insert(0, hex_s)
        if len(self._recent) > self._MAX_RECENT:
            self._recent = self._recent[: self._MAX_RECENT]
        self.accept()

    # ---- Popup positioning ----

    def show_at(self, button: QWidget):
        btn = button
        self._parent_button = button
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        screen = btn.screen().availableGeometry()
        x = max(screen.left(), min(pos.x(), screen.right() - self.width()))
        y = pos.y()
        if y + self.height() > screen.bottom():
            y = btn.mapToGlobal(btn.rect().topLeft()).y() - self.height()
        self.move(x, y)
        self._apply_initial_color()
        self.show()
        self.activateWindow()

    def reject(self):
        self._current_hex = self._prev_hex
        super().reject()


# ---------------------------------------------------------------------------
# ColorPickerButton — wraps the popup picker
# ---------------------------------------------------------------------------

class ColorPickerButton(QPushButton):
    """
    A button that shows a colour swatch + hex text.
    Clicking it opens the professional ColorPickerPopup.
    """

    color_changed = pyqtSignal(str)  # emits hex colour string

    def __init__(self, hex_color: str = "#FFFFFF", parent=None):
        super().__init__(parent)
        self._hex = hex_color.upper()
        self._popup: ColorPickerPopup | None = None
        self.setFixedHeight(28)
        self.setMinimumWidth(80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._button_style())
        self.clicked.connect(self._open_picker)

    def set_color(self, hex_color: str):
        self._hex = hex_color.upper()
        self.setStyleSheet(self._button_style())
        self.update()

    def color(self) -> str:
        return self._hex

    def _button_style(self) -> str:
        return (
            f"QPushButton {{ background: {C_ELEVATED_BG}; border: 1px solid {C_BORDER}; "
            f"border-radius: 5px; padding: 2px 10px 2px 6px; text-align: left; color: {C_TEXT}; "
            f"font-family: monospace; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {C_HOVER}; border-color: {C_ACCENT}; }}"
            f"QPushButton:pressed {{ background: {C_ACCENT_DIM}; }}"
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(self._hex)
        rect = self.rect().adjusted(8, 6, -self.fontMetrics().horizontalAdvance(self._hex) - 22, -6)
        p.setPen(QPen(QColor("#555555"), 1))
        p.setBrush(col)
        p.drawRoundedRect(rect, 3, 3)

    def _open_picker(self):
        self._popup = ColorPickerPopup(self._hex, self)
        self._popup.setStyleSheet(f"""
            ColorPickerPopup {{ background: transparent; }}
        """)
        self._popup.finished.connect(self._on_picker_closed)
        self._popup.show_at(self)

    def _on_picker_closed(self, result: int):
        if result == QDialog.DialogCode.Accepted and self._popup:
            color = self._popup.selected_color()
            if color:
                self.set_color(color)
                self.color_changed.emit(color)


# ---------------------------------------------------------------------------
# Swatch button used inside the picker
# ---------------------------------------------------------------------------

class SwatchButton(QPushButton):
    def __init__(self, hex_color: str, parent=None):
        super().__init__(parent)
        self._hex = hex_color.upper()
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{ background: {hex_color};
                          border: 1px solid {C_BORDER};
                          border-radius: 4px; }}
            QPushButton:hover {{ border-color: {C_ACCENT}; }}
        """)
        self.setToolTip(hex_color)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        p.setPen(QPen(QColor("#555555"), 1))
        p.setBrush(QColor(self._hex))
        p.drawRoundedRect(rect, 3, 3)


# ---------------------------------------------------------------------------
# Hue wheel — circular 360° spectrum
# ---------------------------------------------------------------------------

class HueWheel(QWidget):
    hue_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue = 0
        self.setFixedSize(72, 72)
        self._cache: QImage | None = None

    def set_hue(self, hue: int):
        self._hue = hue
        self.update()

    def _build_image(self) -> QImage:
        size = self.width()
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = size // 2
        outer_r = center - 1
        inner_r = outer_r - 18
        for angle in range(360):
            rad = math.radians(angle - 90)
            x1 = center + outer_r * math.cos(rad)
            y1 = center + outer_r * math.sin(rad)
            x2 = center + inner_r * math.cos(rad)
            y2 = center + inner_r * math.sin(rad)
            pen = QPen(QColor.fromHsv(angle, 255, 255), 2)
            p.setPen(pen)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
        # Selector ring
        rad_sel = math.radians(self._hue - 90)
        rx = center + (outer_r - 9) * math.cos(rad_sel)
        ry = center + (outer_r - 9) * math.sin(rad_sel)
        p.setPen(QPen(Qt.GlobalColor.white, 2))
        p.setBrush(Qt.GlobalColor.transparent)
        p.drawEllipse(int(rx) - 5, int(ry) - 5, 10, 10)
        p.end()
        return img

    def paintEvent(self, event):
        if self._cache is None:
            self._cache = self._build_image()
        p = QPainter(self)
        p.drawImage(self.rect(), self._cache)
        # Center fill preview
        cx = self.width() // 2
        cy = self.height() // 2
        r = cx - 18
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#555555"), 1))
        p.setBrush(QColor.fromHsv(self._hue, 255, 200))
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

    def mousePressEvent(self, event):
        self._drag(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons():
            self._drag(event.pos())

    def _drag(self, pos: QPoint):
        cx = self.width() // 2
        cy = self.height() // 2
        dx = pos.x() - cx
        dy = pos.y() - cy
        angle = math.degrees(math.atan2(dy, dx)) + 90
        if angle < 0:
            angle += 360
        hue = int(angle) % 360
        if hue != self._hue:
            self._hue = hue
            self._cache = None
            self.update()
            self.hue_changed.emit(hue)


# ---------------------------------------------------------------------------
# HSV → RGB conversion (pure Python, mirrors cursor/gradient logic)
# ---------------------------------------------------------------------------

def _hsv_to_rgb(h: int, s: int, v: int) -> tuple[int, int, int]:
    """Convert HSV (0-360, 0-255, 0-255) to RGB (0-255, 0-255, 0-255).
    Rounds to match QColor.fromHsv() behaviour."""
    h = h % 360
    hi = (h // 60) % 6
    f = (h / 60.0) - (h // 60)
    s255 = s / 255.0
    v255 = v / 255.0
    p = v255 * (1.0 - s255)
    q = v255 * (1.0 - f * s255)
    t = v255 * (1.0 - (1.0 - f) * s255)
    vi = round(v255 * 255)
    pi = round(p * 255)
    qi = round(q * 255)
    ti = round(t * 255)
    if hi == 0: return (vi, ti, pi)
    if hi == 1: return (qi, vi, pi)
    if hi == 2: return (pi, vi, ti)
    if hi == 3: return (pi, qi, vi)
    if hi == 4: return (ti, pi, vi)
    return (vi, pi, qi)


# ---------------------------------------------------------------------------
# Saturation / Value square canvas
# ---------------------------------------------------------------------------

class SVCanvas(QWidget):
    """
    2D canvas: horizontal = saturation (0→100 left→right),
               vertical   = value     (0→100 top→bottom).
    White corner = top-left,  Full hue+sat = bottom-right.
    """
    hsv_changed = pyqtSignal(int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._h = 0
        self._s = 255  # 0-255 scale (matching _move / set_hsv)
        self._v = 255
        self.setMinimumSize(180, 150)
        self._sv_cursor_x = 1.0  # 0..1
        self._sv_cursor_y = 0.0  # 0..1
        self._dragging = False
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_hsv(self, h: int, s: int, v: int):
        self._h = h
        self._s = s
        self._v = v
        self._sv_cursor_x = s / 255.0
        self._sv_cursor_y = 1.0 - v / 255.0
        self.update()

    def _build_image(self) -> QImage:
        w = self.width()
        h_img = self.height()
        img = QImage(w, h_img, QImage.Format.Format_ARGB32_Premultiplied)
        h = self._h
        for py in range(h_img):
            t = py / h_img  # 0 top → 1 bottom (spec: val = 1 - y/height)
            val = int((1.0 - t) * 255)  # 255 top (bright), 0 bottom (black)
            for px in range(w):
                s = int((px / w) * 255)  # 0 left (white), 255 right (pure hue)
                r, g, b = _hsv_to_rgb(h, s, val)
                img.setPixelColor(px, py, QColor(r, g, b, 255))
        return img

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        img = self._build_image()
        p.drawImage(self.rect(), img)
        # Cursor crosshair
        cx = int(self._sv_cursor_x * self.width())
        cy = int(self._sv_cursor_y * self.height())
        r = 5
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(Qt.GlobalColor.white, 2))
        p.drawLine(cx - r, cy, cx + r, cy)
        p.drawLine(cx, cy - r, cx, cy + r)
        p.setPen(QPen(Qt.GlobalColor.black, 1.5))
        p.drawEllipse(cx - 4, cy - 4, 8, 8)

    def mousePressEvent(self, event: QMouseEvent):
        self._dragging = True
        self._move(event.pos())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            self._move(event.pos())

    def mouseReleaseEvent(self, _):
        self._dragging = False

    def _move(self, pos: QPoint):
        w = self.width()
        h = self.height()
        x = max(0, min(w - 1, pos.x()))
        y = max(0, min(h - 1, pos.y()))
        self._sv_cursor_x = x / w
        self._sv_cursor_y = y / h
        s = int(x / w * 255) if w > 0 else 0
        v = int((1.0 - y / h) * 255) if h > 0 else 0
        if s != self._s or v != self._v:
            self._s = s
            self._v = v
            self.update()
            self.hsv_changed.emit(self._h, self._s, self._v)


# ---------------------------------------------------------------------------
# Collapsible accordion section
# ---------------------------------------------------------------------------

class AccordionSection(QFrame):
    """A titled bar that expands/collapses its content widget."""

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._expanded = True
        self.setObjectName("AccordionSection")

        header_lay = QHBoxLayout()
        header_lay.setContentsMargins(10, 6, 10, 6)

        self._toggle_btn = QToolButton()
        self._toggle_btn.setText("▼" if self._expanded else "▶")
        self._toggle_btn.setFixedWidth(20)
        self._toggle_btn.setStyleSheet(
            f"QToolButton {{ border: none; color: {C_ACCENT}; font-size: 12px; font-weight: bold; }}"
        )
        self._toggle_btn.clicked.connect(self._on_toggle)
        header_lay.addWidget(self._toggle_btn)

        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"font-weight: 600; font-size: 12px; color: {C_TEXT}; "
            f"letter-spacing: 0.5px;"
        )
        header_lay.addWidget(lbl)
        header_lay.addStretch()

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(12, 6, 12, 8)
        self._content_layout.setSpacing(6)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(header_lay)
        outer.addWidget(self._content)

        self.setStyleSheet(
            f"#AccordionSection {{ background: {C_SECTION_BG}; border-radius: 6px; "
            f"border: 1px solid {C_SECTION_BORDER}; margin-bottom: 6px; }}"
        )
        self._sync_visibility()

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def set_expanded(self, on: bool):
        if self._expanded == on:
            return
        self._expanded = on
        self._toggle_btn.setText("▼" if on else "▶")
        self._sync_visibility()
        self.toggled.emit(on)

    def _on_toggle(self):
        self.set_expanded(not self._expanded)

    def _sync_visibility(self):
        self._content.setVisible(self._expanded)


# ---------------------------------------------------------------------------
# Subtitle Preview Widget
# ---------------------------------------------------------------------------

class SubtitlePreviewWidget(QWidget):
    """
    Dark canvas rendering a styled subtitle line with accurate simulation of:
      - Background box (rounded rectangle, opacity, padding)
      - Drop shadow (angle, distance, blur, opacity)
      - Stroke / outline (color, width)
      - Text fill (color, font, size, alignment)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._style = SubtitleStylePreset(name="Default")
        self._sample_text = "Day la phu de mau\nNhiep anh dep trai"
        self._entries: list[SubtitleEntry] = []
        self._srt_path: str | None = None
        self.setMinimumHeight(160)
        self.setMaximumHeight(200)
        self.setStyleSheet(
            f"background: {C_PREVIEW_BG}; border-radius: 6px; "
            f"border: 1px solid {C_PREVIEW_BORDER};"
        )

    def set_style(self, style: SubtitleStylePreset):
        self._style = style
        self.update()

    def set_sample_text(self, text: str):
        self._sample_text = text
        self.update()

    def reload_srt(self, srt_path: str | None):
        """Reload SRT entries from disk and refresh the preview."""
        self._srt_path = srt_path
        self._entries = SrtService.parse(srt_path) if srt_path else []
        self.update()

    def minimumSizeHint(self) -> QSize:
        return QSize(200, 160)

    # ------------------------------------------------------------------
    # Painting helpers
    # ------------------------------------------------------------------

    def _anchor_to_pos(self, canvas_w, canvas_h, box_w, box_h,
                       h_anchor, v_anchor,
                       margin_l, margin_r, margin_v):
        if h_anchor == 0.0:
            bx = margin_l
        elif h_anchor == 0.5:
            bx = int((canvas_w - box_w) / 2)
        else:
            bx = canvas_w - margin_r - box_w

        if v_anchor == 0.0:
            by = margin_v
        elif v_anchor == 0.5:
            by = int((canvas_h - box_h) / 2)
        else:
            by = canvas_h - margin_v - box_h
        return bx, by

    def _draw_shadow(self, p: QPainter, x: float, y: float,
                     w: float, h: float, style: SubtitleStylePreset):
        """Draw a soft drop-shadow for the subtitle box."""
        if not style.shadow_enabled or style.shadow_distance <= 0:
            return

        rad = math.radians(style.shadow_angle)
        dx = style.shadow_distance * math.cos(rad)
        dy = style.shadow_distance * math.sin(rad)
        blur = max(0.0, style.shadow_blur)
        alpha = style.shadow_opacity

        col = QColor(style.shadow_color)
        col.setAlphaF(alpha)

        for i in range(int(blur) + 2, 0, -1):
            a = alpha * (i / max(blur, 1))
            c = QColor(col)
            c.setAlphaF(a)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(
                int(x + dx - i / 2),
                int(y + dy - i / 2),
                int(w + i),
                int(h + i),
                style.bg_corner_radius + i / 2,
                style.bg_corner_radius + i / 2,
            )

    def _draw_background(self, p: QPainter, rect: QRect,
                         style: SubtitleStylePreset):
        """Draw the rounded-rectangle background box."""
        if not style.bg_enabled:
            return
        col = QColor(style.bg_color)
        col.setAlphaF(style.bg_opacity)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(
            rect.x(), rect.y(),
            rect.width(), rect.height(),
            style.bg_corner_radius,
            style.bg_corner_radius,
        )

    def _draw_text_with_stroke(self, p: QPainter, lines: list[str],
                               x: float, y: float,
                               style: SubtitleStylePreset,
                               fm):
        """Draw text lines with stroke (outline) then fill."""
        font = QFont(style.font_name, style.font_size)
        p.setFont(font)

        line_h = fm.height()
        spacing = int(line_h * 0.15)

        if style.stroke_enabled and style.stroke_width > 0:
            stroke_col = QColor(style.stroke_color)
            pen_stroke = QPen(stroke_col)
            pen_stroke.setWidthF(style.stroke_width * 2)
            pen_stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen_stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i, line in enumerate(lines):
                ty = y + i * (line_h + spacing)
                p.drawText(int(x), int(ty), line)

        fill_col = QColor(style.font_color)
        p.setPen(fill_col)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i, line in enumerate(lines):
            ty = y + i * (line_h + spacing)
            p.drawText(int(x), int(ty), line)

    # ------------------------------------------------------------------
    # Main paint
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        style = self._style
        cw = self.width()
        ch = self.height()
        margin_l = style.margin_l
        margin_r = style.margin_r
        margin_v = style.margin_v

        font = QFont(style.font_name, style.font_size)
        p.setFont(font)
        fm = p.fontMetrics()

        # Show first SRT entry if loaded, otherwise sample text
        if self._entries:
            lines = self._entries[0].text.split("\n")
        else:
            lines = self._sample_text.split("\n")

        max_lw = max(fm.horizontalAdvance(ln) for ln in lines) if lines else 100
        line_h = fm.height()
        spacing = int(line_h * 0.15)
        n = len(lines)
        txt_h = n * line_h + (n - 1) * spacing
        txt_w = max_lw

        # Inner text bounding box
        bx0 = 0
        by0 = 0
        inner_rect = QRect(
            bx0 + style.bg_padding_x,
            by0 + style.bg_padding_y,
            txt_w + 2 * style.bg_padding_x,
            txt_h + 2 * style.bg_padding_y,
        )

        # Map alignment
        # v=0.0 → top of canvas, v=0.5 → middle, v=1.0 → bottom
        # UI grid: row 0=top (codes 7-9), row 2=bottom (codes 1-3)
        align_map = {
            7: (0.0, 0.0), 8: (0.5, 0.0), 9: (1.0, 0.0),
            4: (0.0, 0.5), 5: (0.5, 0.5), 6: (1.0, 0.5),
            1: (0.0, 1.0), 2: (0.5, 1.0), 3: (1.0, 1.0),
            10: (0.5, 1.0),
        }
        h_a, v_a = align_map.get(style.alignment, (0.5, 1.0))

        bx, by = self._anchor_to_pos(
            cw, ch, inner_rect.width(), inner_rect.height(),
            h_a, v_a, margin_l, margin_r, margin_v,
        )

        bx0 = bx
        by0 = by
        inner_rect.translate(bx0, by0)

        # Shadow (drawn behind everything)
        self._draw_shadow(
            p,
            float(inner_rect.x()), float(inner_rect.y()),
            float(inner_rect.width()), float(inner_rect.height()),
            style,
        )

        # Background
        self._draw_background(p, inner_rect, style)

        # Text
        txt_x = float(inner_rect.x() + style.bg_padding_x)
        txt_y = float(inner_rect.y() + style.bg_padding_y + fm.ascent())
        self._draw_text_with_stroke(p, lines, txt_x, txt_y, style, fm)


# ---------------------------------------------------------------------------
# Live Frame Preview — video/image frame with subtitle overlay
# ---------------------------------------------------------------------------

class LiveFramePreview(SubtitlePreviewWidget):
    """
    Drop-in replacement for SubtitlePreviewWidget.
    Displays a video frame (or image) as the background, then overlays
    the styled subtitle on top using the exact same rendering pipeline.

    Usage:
        preview = LiveFramePreview()
        preview.set_frame(QImage or QPixmap)
        preview.set_style(SubtitleStylePreset)
        preview.set_sample_text("Your subtitle text")
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame_img: QImage | None = None
        self.setStyleSheet(
            f"background: #0a0a0a; border-radius: 6px; "
            f"border: 1px solid {C_PREVIEW_BORDER};"
        )

    def set_frame(self, frame: QImage | QPixmap | None):
        """Set the background frame. Pass None to show a dark placeholder."""
        if isinstance(frame, QPixmap):
            self._frame_img = frame.toImage()
        else:
            self._frame_img = frame
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cw = self.width()
        ch = self.height()

        # 1. Draw background frame (aspect-ratio-preserved, fill canvas)
        if self._frame_img and not self._frame_img.isNull():
            scaled = self._frame_img.scaled(
                cw, ch,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x_off = (scaled.width() - cw) // 2
            y_off = (scaled.height() - ch) // 2
            src = QRect(x_off, y_off, cw, ch)
            p.drawImage(QPoint(0, 0), scaled, src)
        else:
            p.fillRect(0, 0, cw, ch, QColor("#111111"))

        # 2. Overlay semi-transparent vignette to make subtitle readable
        # (subtle darkening at edges)
        vignette = QRadialGradient(cw / 2, ch / 2, max(cw, ch) * 0.7)
        vignette.setColorAt(0.0, QColor(0, 0, 0, 0))
        vignette.setColorAt(1.0, QColor(0, 0, 0, 60))
        p.fillRect(0, 0, cw, ch, vignette)

        # 3. Draw subtitle (reuse inherited methods on same canvas)
        style = self._style
        margin_l = style.margin_l
        margin_r = style.margin_r
        margin_v = style.margin_v

        font = QFont(style.font_name, style.font_size)
        p.setFont(font)
        fm = p.fontMetrics()

        if self._entries:
            lines = self._entries[0].text.split("\n")
        else:
            lines = self._sample_text.split("\n")
        max_lw = max(fm.horizontalAdvance(ln) for ln in lines) if lines else 100
        line_h = fm.height()
        spacing = int(line_h * 0.15)
        n = len(lines)
        txt_h = n * line_h + (n - 1) * spacing
        txt_w = max_lw

        inner_rect = QRect(
            style.bg_padding_x,
            style.bg_padding_y,
            txt_w + 2 * style.bg_padding_x,
            txt_h + 2 * style.bg_padding_y,
        )

        # v=0.0 → top of canvas, v=0.5 → middle, v=1.0 → bottom
        # UI grid: row 0=top (codes 7-9), row 2=bottom (codes 1-3)
        align_map = {
            7: (0.0, 0.0), 8: (0.5, 0.0), 9: (1.0, 0.0),
            4: (0.0, 0.5), 5: (0.5, 0.5), 6: (1.0, 0.5),
            1: (0.0, 1.0), 2: (0.5, 1.0), 3: (1.0, 1.0),
            10: (0.5, 1.0),
        }
        h_a, v_a = align_map.get(style.alignment, (0.5, 1.0))

        bx, by = self._anchor_to_pos(
            cw, ch, inner_rect.width(), inner_rect.height(),
            h_a, v_a, margin_l, margin_r, margin_v,
        )

        inner_rect.translate(bx, by)

        self._draw_shadow(
            p,
            float(inner_rect.x()), float(inner_rect.y()),
            float(inner_rect.width()), float(inner_rect.height()),
            style,
        )
        self._draw_background(p, inner_rect, style)

        txt_x = float(inner_rect.x() + style.bg_padding_x)
        txt_y = float(inner_rect.y() + style.bg_padding_y + fm.ascent())
        self._draw_text_with_stroke(p, lines, txt_x, txt_y, style, fm)


# ---------------------------------------------------------------------------
# Appearance Panel — collapsible sections for Fill / Stroke / BG / Shadow
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Toggle switch (replaces checkbox for on/off)
# ---------------------------------------------------------------------------

class ToggleSwitch(QWidget):
    """A compact iOS-style toggle switch."""

    toggled = pyqtSignal(bool)

    def __init__(self, initial: bool = False, parent=None):
        super().__init__(parent)
        self._on = initial
        self.setFixedSize(36, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._ss())
        self.toggled.connect

    def isChecked(self) -> bool:
        return self._on

    def setChecked(self, on: bool):
        if self._on == on:
            return
        self._on = on
        self.setStyleSheet(self._ss())
        self.toggled.emit(on)

    def _ss(self) -> str:
        track = C_ACCENT if self._on else C_BORDER
        thumb = C_TEXT if self._on else C_TEXT_MUTED
        pos = "right: 2px" if self._on else "left: 2px"
        return (
            f"QWidget {{ background: transparent; }}"
            f"QWidget QLabel {{ background: {track}; border-radius: 9px; "
            f"border: none; spacing: 0; padding: 0; }}"
            f"QWidget::item {{ background: {track}; border-radius: 9px; }}"
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Track
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C_ACCENT if self._on else C_BORDER))
        p.drawRoundedRect(0, 0, 36, 20, 10, 10)
        # Thumb
        thumb_x = 18 if self._on else 2
        p.setBrush(QColor(C_TEXT if self._on else C_TEXT_MUTED))
        p.drawEllipse(thumb_x, 2, 16, 16)

    def mousePressEvent(self, event):
        self.setChecked(not self._on)

    def changeEvent(self, event):
        if event.type() == event.Type.EnabledChange:
            opacity = "1.0" if self.isEnabled() else "0.4"
            self.setStyleSheet(f"QWidget {{ opacity: {opacity}; }}")


# ---------------------------------------------------------------------------
# Subtitle Style Editor — redesigned professional panel
# ---------------------------------------------------------------------------

class SubtitleStyleEditor(QWidget):
    """
    Professional subtitle style editor with:
      - Compact 3-section layout: Text | Appearance | Layout
      - Visual 3x3 alignment grid
      - Toggle switches instead of checkboxes
      - 40x20 px colour swatches
      - Grid-aligned rows
      - Preset bar: Save / Load / Delete / Defaults
      - Live preview canvas on the right
    """

    style_changed = pyqtSignal(object)

    FONTS = [
        "Arial", "Roboto", "Montserrat", "Open Sans",
        "Verdana", "Tahoma", "Georgia", "Times New Roman",
    ]

    PRESETS_BUILTIN = {
        "Classic": SubtitleStylePreset(
            name="Classic",
            font_name="Arial", font_size=36,
            font_color="#FFFFFF",
            stroke_color="#000000", stroke_width=2.0, stroke_enabled=True,
            bg_color="#000000", bg_opacity=0.7, bg_padding_x=12, bg_padding_y=6,
            bg_corner_radius=4, bg_enabled=True,
            shadow_color="#000000", shadow_opacity=0, shadow_angle=45,
            shadow_distance=0, shadow_blur=0, shadow_enabled=False,
            alignment=2, margin_v=50, margin_l=20, margin_r=20,
        ),
        "Cinematic": SubtitleStylePreset(
            name="Cinematic",
            font_name="Montserrat", font_size=32,
            font_color="#F5F5F5",
            stroke_color="#000000", stroke_width=3.0, stroke_enabled=True,
            bg_color="#1a1a1a", bg_opacity=0.85, bg_padding_x=20, bg_padding_y=8,
            bg_corner_radius=0, bg_enabled=True,
            shadow_color="#000000", shadow_opacity=0.5, shadow_angle=315,
            shadow_distance=4, shadow_blur=8, shadow_enabled=True,
            alignment=2, margin_v=60, margin_l=40, margin_r=40,
        ),
        "Clean": SubtitleStylePreset(
            name="Clean",
            font_name="Open Sans", font_size=38,
            font_color="#FFFFFF",
            stroke_color="#000000", stroke_width=1.5, stroke_enabled=True,
            bg_color="#000000", bg_opacity=0.6, bg_padding_x=16, bg_padding_y=6,
            bg_corner_radius=8, bg_enabled=True,
            shadow_color="#000000", shadow_opacity=0, shadow_angle=45,
            shadow_distance=0, shadow_blur=0, shadow_enabled=False,
            alignment=2, margin_v=50, margin_l=30, margin_r=30,
        ),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preset_name = "Classic"
        self._presets = {}  # user-saved presets
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_style(self) -> SubtitleStylePreset:
        return SubtitleStylePreset(
            name=self._preset_name,
            font_name=self._cmb_font.currentText(),
            font_size=self._spn_size.value(),
            font_color=self._btn_font_color.color(),
            stroke_color=self._btn_stroke_color.color(),
            stroke_width=self._spn_stroke_width.value(),
            stroke_enabled=self._sw_stroke.isChecked(),
            bg_color=self._btn_bg_color.color(),
            bg_opacity=self._spn_bg_opacity.value() / 100.0,
            bg_padding_x=self._spn_bg_pad_x.value(),
            bg_padding_y=self._spn_bg_pad_y.value(),
            bg_corner_radius=self._spn_bg_radius.value(),
            bg_enabled=self._sw_bg.isChecked(),
            shadow_color=self._btn_shadow_color.color(),
            shadow_opacity=self._spn_shadow_opacity.value() / 100.0,
            shadow_angle=float(self._spn_shadow_angle.value()),
            shadow_distance=float(self._spn_shadow_dist.value()),
            shadow_blur=float(self._spn_shadow_blur.value()),
            shadow_enabled=self._sw_shadow.isChecked(),
            alignment=self._current_alignment(),
            margin_v=self._spn_margin_v.value(),
            margin_l=self._spn_margin_l.value(),
            margin_r=self._spn_margin_r.value(),
        )

    def set_frame(self, frame: QImage | QPixmap | None):
        """Set the background video/image frame for the live preview."""
        self._preview.set_frame(frame)

    def reload_srt_entries(self, srt_file: str | None):
        """Reload SRT entries from disk and refresh preview.

        Called after external timing changes so the live preview
        always shows up-to-date data.
        """
        self._preview.reload_srt(srt_file)

    def load_from_style(self, style: SubtitleStylePreset):
        self._preset_name = style.name
        idx = self._cmb_font.findText(style.font_name)
        if idx >= 0:
            self._cmb_font.setCurrentIndex(idx)
        self._spn_size.setValue(style.font_size)
        self._btn_font_color.set_color(style.font_color)
        self._btn_stroke_color.set_color(style.stroke_color)
        self._spn_stroke_width.setValue(style.stroke_width)
        self._sw_stroke.setChecked(style.stroke_enabled)
        self._btn_bg_color.set_color(style.bg_color)
        self._spn_bg_opacity.setValue(int(style.bg_opacity * 100))
        self._spn_bg_pad_x.setValue(style.bg_padding_x)
        self._spn_bg_pad_y.setValue(style.bg_padding_y)
        self._spn_bg_radius.setValue(style.bg_corner_radius)
        self._sw_bg.setChecked(style.bg_enabled)
        self._btn_shadow_color.set_color(style.shadow_color)
        self._spn_shadow_opacity.setValue(int(style.shadow_opacity * 100))
        self._spn_shadow_angle.setValue(int(style.shadow_angle))
        self._spn_shadow_dist.setValue(int(style.shadow_distance))
        self._spn_shadow_blur.setValue(int(style.shadow_blur))
        self._sw_shadow.setChecked(style.shadow_enabled)
        self._set_alignment_button(style.alignment)
        self._spn_margin_v.setValue(style.margin_v)
        self._spn_margin_l.setValue(style.margin_l)
        self._spn_margin_r.setValue(style.margin_r)
        self._refresh_preview()

    # ------------------------------------------------------------------
    # UI builder
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setStyleSheet(f"background: {C_BG};")
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        # Left: controls panel
        ctrl = QWidget()
        ctrl.setStyleSheet(f"background: {C_BG};")
        ctrlLay = QVBoxLayout(ctrl)
        ctrlLay.setContentsMargins(0, 0, 0, 0)
        ctrlLay.setSpacing(6)

        ctrlLay.addWidget(self._build_preset_bar())
        ctrlLay.addWidget(self._build_text_section())
        ctrlLay.addWidget(self._build_appearance_section())
        ctrlLay.addWidget(self._build_layout_section())
        ctrlLay.addStretch()

        # Right: live preview (LiveFramePreview supports video/image frame + subtitle overlay)
        self._preview = LiveFramePreview()
        self._preview.setMinimumWidth(320)
        self._preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root.addWidget(ctrl, 1)
        root.addWidget(self._preview, 1)

        self._set_alignment_button(2)

    # ---- Preset bar ----

    def _build_preset_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(32)
        bar.setStyleSheet(f"background: {C_SECTION_BG}; border-radius: 5px; border: 1px solid {C_BORDER};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(6)

        title = QLabel("Presets")
        title.setStyleSheet(f"color: {C_TEXT}; font-size: 11px; font-weight: 600;")
        lay.addWidget(title)

        lay.addSpacing(4)

        self._cmb_preset = QComboBox()
        self._cmb_preset.addItems(list(self.PRESETS_BUILTIN.keys()))
        self._cmb_preset.setFixedWidth(110)
        self._cmb_preset.currentIndexChanged.connect(self._on_preset_selected)
        self._cmb_preset.setStyleSheet(self._cmb_style(28))
        lay.addWidget(self._cmb_preset)

        for icon, tip, handler in [
            ("💾", "Save preset", self._save_preset),
            ("🗑", "Delete preset", self._delete_preset),
            ("↺", "Reset defaults", self._reset_defaults),
        ]:
            btn = QPushButton(icon)
            btn.setFixedSize(28, 22)
            btn.setToolTip(tip)
            btn.setStyleSheet(self._icon_btn_style())
            btn.clicked.connect(handler)
            lay.addWidget(btn)

        lay.addStretch()
        return bar

    # ---- TEXT section ----

    def _build_text_section(self) -> QWidget:
        sec = QWidget()
        sec.setStyleSheet(f"background: {C_SECTION_BG}; border-radius: 5px; border: 1px solid {C_BORDER};")
        lay = QGridLayout(sec)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(5)
        lay.setColumnStretch(1, 1)
        lay.setColumnStretch(3, 1)

        # Row 0: Font | Size
        lay.addWidget(QLabel("Font"), 0, 0)
        self._cmb_font = QComboBox()
        self._cmb_font.addItems(self.FONTS)
        self._cmb_font.setStyleSheet(self._cmb_style(26))
        self._cmb_font.currentIndexChanged.connect(self._on_changed)
        lay.addWidget(self._cmb_font, 0, 1)

        lay.addWidget(QLabel("Size"), 0, 2)
        self._spn_size = self._spin(14, 120, 36, 2, "", 60)
        self._spn_size.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_size, 0, 3)

        # Row 1: Color | Fill color
        lay.addWidget(QLabel("Color"), 1, 0)
        self._btn_font_color = ColorPickerButton("#FFFFFF")
        self._btn_font_color.color_changed.connect(self._on_changed)
        lay.addWidget(self._btn_font_color, 1, 1, 1, 3)

        for w in sec.findChildren(QLabel):
            w.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px;")
        return sec

    # ---- APPEARANCE section ----

    def _build_appearance_section(self) -> QWidget:
        sec = QWidget()
        sec.setStyleSheet(f"background: {C_SECTION_BG}; border-radius: 5px; border: 1px solid {C_BORDER};")
        lay = QGridLayout(sec)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(5)
        lay.setColumnStretch(1, 1)
        lay.setColumnStretch(3, 1)
        lay.setColumnStretch(5, 1)

        # Stroke row
        lay.addWidget(QLabel("Stroke"), 0, 0)
        self._sw_stroke = ToggleSwitch(True)
        self._sw_stroke.toggled.connect(self._on_changed)
        lay.addWidget(self._sw_stroke, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        lay.addWidget(QLabel("Color"), 0, 2)
        self._btn_stroke_color = ColorPickerButton("#000000")
        self._btn_stroke_color.color_changed.connect(self._on_changed)
        lay.addWidget(self._btn_stroke_color, 0, 3)

        lay.addWidget(QLabel("Width"), 0, 4)
        self._spn_stroke_width = self._spin(0, 12, 2.0, 0.5, "px", 60, dbl=True)
        self._spn_stroke_width.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_stroke_width, 0, 5)

        # Background row
        lay.addWidget(QLabel("BG"), 1, 0)
        self._sw_bg = ToggleSwitch(True)
        self._sw_bg.toggled.connect(self._on_changed)
        lay.addWidget(self._sw_bg, 1, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        lay.addWidget(QLabel("Color"), 1, 2)
        self._btn_bg_color = ColorPickerButton("#000000")
        self._btn_bg_color.color_changed.connect(self._on_changed)
        lay.addWidget(self._btn_bg_color, 1, 3)

        lay.addWidget(QLabel("Opacity"), 1, 4)
        self._spn_bg_opacity = self._spin(0, 100, 70, 5, "%", 60)
        self._spn_bg_opacity.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_bg_opacity, 1, 5)

        # Padding row
        lay.addWidget(QLabel("Pad X"), 2, 0)
        self._spn_bg_pad_x = self._spin(0, 80, 12, 1, "px", 60)
        self._spn_bg_pad_x.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_bg_pad_x, 2, 1)

        lay.addWidget(QLabel("Pad Y"), 2, 2)
        self._spn_bg_pad_y = self._spin(0, 40, 6, 1, "px", 60)
        self._spn_bg_pad_y.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_bg_pad_y, 2, 3)

        lay.addWidget(QLabel("Radius"), 2, 4)
        self._spn_bg_radius = self._spin(0, 40, 4, 1, "px", 60)
        self._spn_bg_radius.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_bg_radius, 2, 5)

        # Shadow row
        lay.addWidget(QLabel("Shadow"), 3, 0)
        self._sw_shadow = ToggleSwitch(False)
        self._sw_shadow.toggled.connect(self._on_changed)
        lay.addWidget(self._sw_shadow, 3, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        lay.addWidget(QLabel("Color"), 3, 2)
        self._btn_shadow_color = ColorPickerButton("#000000")
        self._btn_shadow_color.color_changed.connect(self._on_changed)
        lay.addWidget(self._btn_shadow_color, 3, 3)

        lay.addWidget(QLabel("Opacity"), 3, 4)
        self._spn_shadow_opacity = self._spin(0, 100, 80, 5, "%", 60)
        self._spn_shadow_opacity.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_shadow_opacity, 3, 5)

        # Shadow angle/dist/blur row
        lay.addWidget(QLabel("Angle"), 4, 0)
        self._spn_shadow_angle = self._spin(0, 360, 45, 5, "deg", 60)
        self._spn_shadow_angle.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_shadow_angle, 4, 1)

        lay.addWidget(QLabel("Dist"), 4, 2)
        self._spn_shadow_dist = self._spin(0, 30, 4, 1, "px", 60)
        self._spn_shadow_dist.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_shadow_dist, 4, 3)

        lay.addWidget(QLabel("Blur"), 4, 4)
        self._spn_shadow_blur = self._spin(0, 20, 3, 1, "px", 60)
        self._spn_shadow_blur.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_shadow_blur, 4, 5)

        for w in sec.findChildren(QLabel):
            w.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px;")
        return sec

    # ---- LAYOUT section ----

    def _build_layout_section(self) -> QWidget:
        sec = QWidget()
        sec.setStyleSheet(f"background: {C_SECTION_BG}; border-radius: 5px; border: 1px solid {C_BORDER};")
        lay = QGridLayout(sec)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(5)
        lay.setColumnStretch(0, 0)
        lay.setColumnStretch(1, 1)
        lay.setColumnStretch(2, 0)
        lay.setColumnStretch(3, 1)

        # Alignment label
        lbl_align = QLabel("Position")
        lbl_align.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px;")
        lay.addWidget(lbl_align, 0, 0, 1, 4)

        # 3x3 alignment grid
        grid = QWidget()
        grid.setStyleSheet("background: transparent;")
        gridLay = QGridLayout(grid)
        gridLay.setContentsMargins(0, 0, 0, 0)
        gridLay.setSpacing(2)

        # (h_code, v_code) — h: 1=left, 5=center, 9=right, v: 1=top, 5=middle, 9=bottom
        # SSA alignment = h + v
        self._align_buttons: list[QPushButton] = []
        # SSA alignment keypad: 7=LT,8=CT,9=RT / 4=LM,5=CM,6=RM / 1=LB,2=CB,3=RB
        configs = [
            # row 0: top
            (("↖", 7),  ("↑", 8),  ("↗", 9)),
            # row 1: middle
            (("←", 4),  ("•", 5),  ("→", 6)),
            # row 2: bottom
            (("↙", 1),  ("↓", 2),  ("↘", 3)),
        ]
        for r, row in enumerate(configs):
            for c, (icon, code) in enumerate(row):
                btn = QPushButton(icon)
                btn.setFixedSize(28, 22)
                btn.setStyleSheet(self._align_btn_style(False))
                btn.clicked.connect(lambda _, b=btn: self._on_align_clicked(b))
                gridLay.addWidget(btn, r, c)
                self._align_buttons.append(btn)

        lay.addWidget(grid, 1, 0, 1, 4)

        # Margins row
        lbl_vm = QLabel("Margin V")
        lbl_vm.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px;")
        lay.addWidget(lbl_vm, 2, 0)
        self._spn_margin_v = self._spin(0, 500, 50, 5, "px", 60)
        self._spn_margin_v.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_margin_v, 2, 1)

        lbl_lm = QLabel("Margin L")
        lbl_lm.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px;")
        lay.addWidget(lbl_lm, 2, 2)
        self._spn_margin_l = self._spin(0, 200, 20, 5, "px", 60)
        self._spn_margin_l.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_margin_l, 2, 3)

        lbl_rm = QLabel("Margin R")
        lbl_rm.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px;")
        lay.addWidget(lbl_rm, 3, 0)
        self._spn_margin_r = self._spin(0, 200, 20, 5, "px", 60)
        self._spn_margin_r.valueChanged.connect(self._on_changed)
        lay.addWidget(self._spn_margin_r, 3, 1)

        return sec

    # ------------------------------------------------------------------
    # Style helpers
    # ------------------------------------------------------------------

    def _spin(self, min_v, max_v, val, step=1, suffix="", width=70, dbl=False):
        cls = QDoubleSpinBox if dbl else QSpinBox
        s = cls()
        s.setRange(min_v, max_v)
        s.setValue(val)
        s.setSingleStep(step)
        s.setSuffix(suffix)
        s.setFixedWidth(width)
        s.setFixedHeight(26)
        s.setStyleSheet(
            f"QSpinBox, QDoubleSpinBox {{ background: {C_ELEVATED_BG}; color: {C_TEXT}; "
            f"border: 1px solid {C_BORDER}; border-radius: 4px; "
            f"padding: 0px 4px; font-size: 11px; }}"
            f"QSpinBox::up-button, QSpinBox::down-button, "
            f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ "
            f"background: {C_HOVER}; width: 14px; }}"
        )
        return s

    def _cmb_style(self, height=26) -> str:
        return (
            f"QComboBox {{ background: {C_ELEVATED_BG}; color: {C_TEXT}; "
            f"border: 1px solid {C_BORDER}; border-radius: 4px; "
            f"padding: 0px 8px; font-size: 11px; height: {height}px; }}"
            f"QComboBox:hover {{ border-color: {C_ACCENT}; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox::down-arrow {{ image: none; "
            f"border-left: 3px solid transparent; border-right: 3px solid transparent; "
            f"border-top: 4px solid {C_TEXT_MUTED}; }}"
            f"QComboBox QAbstractItemView {{ background: {C_ELEVATED_BG}; "
            f"color: {C_TEXT}; border: 1px solid {C_BORDER}; "
            f"selection-background-color: {C_ACCENT}; font-size: 11px; }}"
        )

    def _icon_btn_style(self) -> str:
        return (
            f"QPushButton {{ background: {C_ELEVATED_BG}; color: {C_TEXT}; "
            f"border: 1px solid {C_BORDER}; border-radius: 4px; "
            f"font-size: 12px; padding: 0; }}"
            f"QPushButton:hover {{ background: {C_HOVER}; border-color: {C_ACCENT}; }}"
        )

    def _align_btn_style(self, active: bool) -> str:
        bg = C_ACCENT if active else C_ELEVATED_BG
        color = C_TEXT if active else C_TEXT_MUTED
        border = C_ACCENT if active else C_BORDER
        return (
            f"QPushButton {{ background: {bg}; color: {color}; "
            f"border: 1px solid {border}; border-radius: 4px; "
            f"font-size: 12px; font-weight: {'bold' if active else 'normal'}; "
            f"padding: 0; }}"
            f"QPushButton:hover {{ background: {C_HOVER}; border-color: {C_ACCENT}; }}"
        )

    # ------------------------------------------------------------------
    # Alignment helpers
    # ------------------------------------------------------------------

    # SSA alignment: units = h(1L/2C/3R), tens = v(0T/1M/2B)
    # e.g. 10 = bottom-center, 1 = top-left, 9 = bottom-right
    _BUTTON_FROM_SSA = {  # SSA code -> btn grid index (0-8, row*3+col)
        # SSA keypad layout: 7-8-9=Top, 4-5-6=Mid, 1-2-3=Bottom
        7: 0, 8: 1, 9: 2,  # top row    (L/T, C/T, R/T)
        4: 3, 5: 4, 6: 5,  # middle row (L/M, C/M, R/M)
        1: 6, 2: 7, 3: 8,  # bottom row (L/B, C/B, R/B)
    }
    _SSA_FROM_BUTTON = {v: k for k, v in _BUTTON_FROM_SSA.items()}
    _ALIGN_ICONS = [
        "↖", "↑", "↗",   # top row
        "←", "•", "→",   # middle row
        "↙", "↓", "↘",   # bottom row
    ]

    def _current_alignment(self) -> int:
        checked = next((b for b in self._align_buttons if b.property("_active")), None)
        if checked:
            idx = self._align_buttons.index(checked)
            return self._SSA_FROM_BUTTON.get(idx, 10)
        return 10

    def _set_alignment_button(self, code: int):
        target_idx = self._BUTTON_FROM_SSA.get(code, 7)  # default: bottom-center
        for i, b in enumerate(self._align_buttons):
            active = (i == target_idx)
            b.setProperty("_active", active)
            b.setStyleSheet(self._align_btn_style(active))

    def _on_align_clicked(self, btn: QPushButton):
        for b in self._align_buttons:
            b.setProperty("_active", b is btn)
            b.setStyleSheet(self._align_btn_style(b is btn))
        self._on_changed()

    # ------------------------------------------------------------------
    # Preset handlers
    # ------------------------------------------------------------------

    def _on_preset_selected(self, idx: int):
        name = self._cmb_preset.currentText()
        preset = self.PRESETS_BUILTIN.get(name) or self._presets.get(name)
        if preset:
            self.load_from_style(preset)

    def _save_preset(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if ok and name.strip():
            name = name.strip()
            style = self.get_style()
            style.name = name
            self._presets[name] = style
            if name not in [self._cmb_preset.itemText(i) for i in range(self._cmb_preset.count())]:
                self._cmb_preset.addItem(name)
            idx = self._cmb_preset.findText(name)
            if idx >= 0:
                self._cmb_preset.setCurrentIndex(idx)

    def _delete_preset(self):
        name = self._cmb_preset.currentText()
        if name in self._presets:
            del self._presets[name]
            idx = self._cmb_preset.currentIndex()
            self._cmb_preset.removeItem(idx)
            self._cmb_preset.setCurrentIndex(max(0, idx - 1))
        elif name in self.PRESETS_BUILTIN:
            pass  # cannot delete built-in

    def _reset_defaults(self):
        self.load_from_style(self.PRESETS_BUILTIN["Classic"])

    # ------------------------------------------------------------------
    # Change signal
    # ------------------------------------------------------------------

    def _on_changed(self):
        self._refresh_preview()
        self.style_changed.emit(self.get_style())

    def _refresh_preview(self):
        style = self.get_style()
        self._preview.set_style(style)
        self._preview.set_sample_text("Day la phu de mau\nDay la dong thu hai")


# ---------------------------------------------------------------------------
# Legacy re-export so existing import paths keep working
# ---------------------------------------------------------------------------

SubtitleStylePanel = SubtitleStyleEditor
AppearancePanel = SubtitleStyleEditor

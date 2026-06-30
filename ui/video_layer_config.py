"""
Widget for configuring a single video layer (1 of 5) in the Edit Video tab.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QComboBox, QSpinBox, QCheckBox, QPushButton,
    QGroupBox, QFrame, QLineEdit
)
from PyQt6.QtCore import pyqtSignal
from pathlib import Path
import os

from core.video_processor import ImageLayerConfig

class VideoLayerConfigWidget(QWidget):
    changed = pyqtSignal()

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self._init_ui()

    def _init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # Row 1: Active switch & Source Picker
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        
        self.chk_enabled = QCheckBox("Kích hoạt Layer")
        self.chk_enabled.setStyleSheet("font-size: 11px; font-weight: bold;")
        self.chk_enabled.stateChanged.connect(self._on_changed)
        row1.addWidget(self.chk_enabled)

        # Source type selector (Background, Batch or static file)
        self.cmb_source_type = QComboBox()
        self.cmb_source_type.addItems([
            "Video nền (Background video)",
            "Theo danh sách chạy (Video nguồn)",
            "File cố định (Static file...)"
        ])
        self.cmb_source_type.setStyleSheet("font-size: 11px;")
        self.cmb_source_type.currentIndexChanged.connect(self._on_source_type_changed)
        row1.addWidget(self.cmb_source_type)
        lay.addLayout(row1)

        # Static file selector row (visible only if Static file is selected)
        self.static_file_frame = QFrame()
        self.static_file_frame.setFrameShape(QFrame.Shape.NoFrame)
        static_lay = QHBoxLayout(self.static_file_frame)
        static_lay.setContentsMargins(0, 0, 0, 0)
        static_lay.setSpacing(6)

        self.lbl_path = QLabel("Đường dẫn:")
        self.lbl_path.setStyleSheet("font-size: 11px;")
        self.lbl_path.setFixedWidth(60)
        static_lay.addWidget(self.lbl_path)

        self.edit_path = QLineEdit()
        self.edit_path.setReadOnly(True)
        self.edit_path.setPlaceholderText("Chọn file video/ảnh...")
        self.edit_path.setStyleSheet("font-size: 11px;")
        static_lay.addWidget(self.edit_path, 1)

        self.btn_browse = QPushButton("Chọn…")
        self.btn_browse.setFixedWidth(55)
        self.btn_browse.setStyleSheet("font-size: 11px;")
        self.btn_browse.clicked.connect(self._browse_static_file)
        static_lay.addWidget(self.btn_browse)

        lay.addWidget(self.static_file_frame)
        self.static_file_frame.setVisible(False) # Default is Batch file

        # Row 2: Vị trí neo (Alignment)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        pos_lbl = QLabel("Vị trí đè:")
        pos_lbl.setStyleSheet("font-size: 11px;")
        pos_lbl.setFixedWidth(60)
        row2.addWidget(pos_lbl)

        self.cmb_pos = QComboBox()
        self.cmb_pos.addItems([
            "Ở giữa (Center)",
            "Góc dưới - Phải (Bottom-Right)",
            "Góc dưới - Trái (Bottom-Left)",
            "Góc trên - Phải (Top-Right)",
            "Góc trên - Trái (Top-Left)"
        ])
        self.cmb_pos.setStyleSheet("font-size: 11px;")
        self.cmb_pos.currentIndexChanged.connect(self._on_pos_changed)
        row2.addWidget(self.cmb_pos, 1)
        lay.addLayout(row2)

        # Row 3: Cỡ (Scale %) & Bo góc (Radius px)
        row3 = QHBoxLayout()
        row3.setSpacing(10)

        sz_lbl = QLabel("Cỡ (%):")
        sz_lbl.setStyleSheet("font-size: 11px;")
        row3.addWidget(sz_lbl)

        self.spn_size = QSpinBox()
        self.spn_size.setRange(10, 100)
        self.spn_size.setValue(30 if self.index == 1 else 15)
        self.spn_size.setStyleSheet("font-size: 11px;")
        self.spn_size.valueChanged.connect(self._on_changed)
        row3.addWidget(self.spn_size, 1)

        op_lbl = QLabel("Độ mờ (%):")
        op_lbl.setStyleSheet("font-size: 11px;")
        row3.addWidget(op_lbl)

        self.spn_opacity = QSpinBox()
        self.spn_opacity.setRange(10, 100)
        self.spn_opacity.setValue(100)
        self.spn_opacity.setSingleStep(5)
        self.spn_opacity.setStyleSheet("font-size: 11px;")
        self.spn_opacity.valueChanged.connect(self._on_changed)
        row3.addWidget(self.spn_opacity, 1)
        lay.addLayout(row3)

        # Row 4: Margins Group
        margin_grp = QGroupBox("Căn chỉnh khoảng lề (Margin - px)")
        margin_grp.setStyleSheet("QGroupBox { font-size: 10px; font-weight: bold; }")
        margin_lay = QGridLayout(margin_grp)
        margin_lay.setContentsMargins(6, 6, 6, 6)
        margin_lay.setSpacing(6)

        # Top
        margin_lay.addWidget(QLabel("Trên:"), 0, 0)
        self.spn_margin_t = QSpinBox()
        self.spn_margin_t.setRange(0, 1000)
        self.spn_margin_t.setValue(60 if self.index == 1 else 145)
        self.spn_margin_t.valueChanged.connect(self._on_changed)
        margin_lay.addWidget(self.spn_margin_t, 0, 1)

        # Bottom
        margin_lay.addWidget(QLabel("Dưới:"), 0, 2)
        self.spn_margin_b = QSpinBox()
        self.spn_margin_b.setRange(0, 1000)
        self.spn_margin_b.setValue(60 if self.index == 1 else 20)
        self.spn_margin_b.valueChanged.connect(self._on_changed)
        margin_lay.addWidget(self.spn_margin_b, 0, 3)

        # Left
        margin_lay.addWidget(QLabel("Trái:"), 1, 0)
        self.spn_margin_l = QSpinBox()
        self.spn_margin_l.setRange(0, 1000)
        self.spn_margin_l.setValue(140 if self.index == 1 else 320)
        self.spn_margin_l.valueChanged.connect(self._on_changed)
        margin_lay.addWidget(self.spn_margin_l, 1, 1)

        # Right
        margin_lay.addWidget(QLabel("Phải:"), 1, 2)
        self.spn_margin_r = QSpinBox()
        self.spn_margin_r.setRange(0, 1000)
        self.spn_margin_r.setValue(140 if self.index == 1 else 20)
        self.spn_margin_r.valueChanged.connect(self._on_changed)
        margin_lay.addWidget(self.spn_margin_r, 1, 3)

        lay.addWidget(margin_grp)

        # Row 5: Crop Group
        crop_grp = QGroupBox("Cắt cúp khung hình (Crop - px)")
        crop_grp.setStyleSheet("QGroupBox { font-size: 10px; font-weight: bold; }")
        crop_lay = QGridLayout(crop_grp)
        crop_lay.setContentsMargins(6, 6, 6, 6)
        crop_lay.setSpacing(6)

        # Crop Top
        crop_lay.addWidget(QLabel("Cắt Trên:"), 0, 0)
        self.spn_crop_t = QSpinBox()
        self.spn_crop_t.setRange(0, 500)
        self.spn_crop_t.setValue(0)
        self.spn_crop_t.valueChanged.connect(self._on_changed)
        crop_lay.addWidget(self.spn_crop_t, 0, 1)

        # Crop Bottom
        crop_lay.addWidget(QLabel("Cắt Dưới:"), 0, 2)
        self.spn_crop_b = QSpinBox()
        self.spn_crop_b.setRange(0, 500)
        self.spn_crop_b.setValue(0)
        self.spn_crop_b.valueChanged.connect(self._on_changed)
        crop_lay.addWidget(self.spn_crop_b, 0, 3)

        # Crop Left
        crop_lay.addWidget(QLabel("Cắt Trái:"), 1, 0)
        self.spn_crop_l = QSpinBox()
        self.spn_crop_l.setRange(0, 500)
        self.spn_crop_l.setValue(0)
        self.spn_crop_l.valueChanged.connect(self._on_changed)
        crop_lay.addWidget(self.spn_crop_l, 1, 1)

        # Crop Right
        crop_lay.addWidget(QLabel("Cắt Phải:"), 1, 2)
        self.spn_crop_r = QSpinBox()
        self.spn_crop_r.setRange(0, 500)
        self.spn_crop_r.setValue(0)
        self.spn_crop_r.valueChanged.connect(self._on_changed)
        crop_lay.addWidget(self.spn_crop_r, 1, 3)

        lay.addWidget(crop_grp)

        # Default states: Layer 1 and 2 are active on wireframe demo
        if self.index in (1, 2):
            self.chk_enabled.setChecked(True)
        else:
            self.chk_enabled.setChecked(False)

        # Initialize mock values for Layer 2
        if self.index == 2:
            self.cmb_source_type.setCurrentIndex(1) # Static file
            self.edit_path.setText("logo.png")
            self.cmb_pos.setCurrentIndex(1) # Bottom-Right

    def _on_source_type_changed(self, idx: int):
        self.static_file_frame.setVisible(idx == 2)
        self._on_changed()

    def _browse_static_file(self):
        from PyQt6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file video/ảnh phủ đè",
            "",
            "Media files (*.png *.jpg *.jpeg *.bmp *.mp4 *.mov *.avi *.mkv);;All files (*.*)"
        )
        if file_path:
            self.edit_path.setText(file_path)
            self._on_changed()

    def _on_changed(self):
        self.changed.emit()

    def get_config(self) -> ImageLayerConfig:
        """Returns the configuration parsed from widgets."""
        idx = self.cmb_source_type.currentIndex()
        if idx == 0:
            path_val = "Video nền"
        elif idx == 1:
            path_val = "Theo danh sách chạy"
        else:
            path_val = self.edit_path.text()
            
        # Mapping index to ImageLayerConfig position:
        # Combo positions: 0: Center, 1: BR, 2: BL, 3: TR, 4: TL
        # Config positions: 0: BR, 1: BL, 2: TR, 3: TL, 4: TC (Center)
        combo_to_config = {0: 4, 1: 0, 2: 1, 3: 2, 4: 3}
        pos_val = combo_to_config.get(self.cmb_pos.currentIndex(), 4)

        cfg_obj = ImageLayerConfig(
            enabled=self.chk_enabled.isChecked(),
            path=path_val,
            position=pos_val,
            size=self.spn_size.value(),
            opacity=self.spn_opacity.value() / 100.0,
            margin_t=self.spn_margin_t.value(),
            margin_b=self.spn_margin_b.value(),
            margin_l=self.spn_margin_l.value(),
            margin_r=self.spn_margin_r.value()
        )
        # Extend config dynamically with crop/radius
        cfg_obj.crop_t = self.spn_crop_t.value()
        cfg_obj.crop_b = self.spn_crop_b.value()
        cfg_obj.crop_l = self.spn_crop_l.value()
        cfg_obj.crop_r = self.spn_crop_r.value()
        cfg_obj.radius = 0
        cfg_obj.source_type = idx # Save index
        return cfg_obj

    def set_config(self, cfg_obj: ImageLayerConfig):
        """Populates the widget values from a config object."""
        self.chk_enabled.setChecked(cfg_obj.enabled)
        
        idx = getattr(cfg_obj, "source_type", -1)
        if idx == -1:
            if cfg_obj.path == "Video nền":
                idx = 0
            elif cfg_obj.path == "Theo danh sách chạy" or not cfg_obj.path:
                idx = 1
            else:
                idx = 2
                
        self.cmb_source_type.setCurrentIndex(idx)
        if idx == 2:
            self.edit_path.setText(cfg_obj.path)
        else:
            self.edit_path.clear()

        # Config to Combo position mapping
        config_to_combo = {4: 0, 0: 1, 1: 2, 2: 3, 3: 4}
        self.cmb_pos.blockSignals(True)
        self.cmb_pos.setCurrentIndex(config_to_combo.get(cfg_obj.position, 0))
        self.cmb_pos.blockSignals(False)

        self.spn_size.setValue(cfg_obj.size)
        self.spn_opacity.setValue(int(getattr(cfg_obj, "opacity", 1.0) * 100))
        self.spn_margin_t.setValue(cfg_obj.margin_t)
        self.spn_margin_b.setValue(cfg_obj.margin_b)
        self.spn_margin_l.setValue(cfg_obj.margin_l)
        self.spn_margin_r.setValue(cfg_obj.margin_r)

        self.spn_crop_t.setValue(getattr(cfg_obj, "crop_t", 0))
        self.spn_crop_b.setValue(getattr(cfg_obj, "crop_b", 0))
        self.spn_crop_l.setValue(getattr(cfg_obj, "crop_l", 0))
        self.spn_crop_r.setValue(getattr(cfg_obj, "crop_r", 0))

    def _on_pos_changed(self, index: int):
        # Snap margins when position changes in UI
        self.spn_margin_t.blockSignals(True)
        self.spn_margin_b.blockSignals(True)
        self.spn_margin_l.blockSignals(True)
        self.spn_margin_r.blockSignals(True)
        
        if index == 0: # Center
            self.spn_margin_t.setValue(0)
            self.spn_margin_b.setValue(0)
            self.spn_margin_l.setValue(0)
            self.spn_margin_r.setValue(0)
        elif index == 1: # BR
            self.spn_margin_t.setValue(0)
            self.spn_margin_b.setValue(20)
            self.spn_margin_l.setValue(0)
            self.spn_margin_r.setValue(20)
        elif index == 2: # BL
            self.spn_margin_t.setValue(0)
            self.spn_margin_b.setValue(20)
            self.spn_margin_l.setValue(20)
            self.spn_margin_r.setValue(0)
        elif index == 3: # TR
            self.spn_margin_t.setValue(20)
            self.spn_margin_b.setValue(0)
            self.spn_margin_l.setValue(0)
            self.spn_margin_r.setValue(20)
        elif index == 4: # TL
            self.spn_margin_t.setValue(20)
            self.spn_margin_b.setValue(0)
            self.spn_margin_l.setValue(20)
            self.spn_margin_r.setValue(0)

        self.spn_margin_t.blockSignals(False)
        self.spn_margin_b.blockSignals(False)
        self.spn_margin_l.blockSignals(False)
        self.spn_margin_r.blockSignals(False)
        
        self._on_changed()

"""
Subtitle Editor Widget — Phase 1.

Provides a table of subtitle entries, an edit form for the selected entry,
and save/validate actions.
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path

_root = str(_Path(__file__).parent.parent)
if _root not in _sys.path:
    _sys.path.insert(0, _root)

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QPushButton,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox,
    QGroupBox, QGridLayout, QTextEdit, QHeaderView,
    QMessageBox, QToolButton, QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from core.subtitle_model import SubtitleDocument, SubtitleEntry
from core.srt_service import SrtService


class SubtitleEditorWidget(QWidget):
    """
    Widget for viewing and editing SRT subtitle entries.

    Signals:
        entry_selected(SubtitleEntry | None) — emitted when user selects an entry.
        dirty_changed(bool) — emitted when the document has unsaved changes.
    """

    entry_selected = pyqtSignal(object)
    dirty_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: SubtitleDocument | None = None

        self._build_ui()
        self._set_edit_enabled(False)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def load_document(self, file_path: str) -> bool:
        """Parse an SRT file and display its entries. Returns True on success."""
        try:
            entries = SrtService.parse(file_path)
            self._doc = SubtitleDocument(file_path=file_path, entries=entries, dirty=False)
            self._populate_table()
            self._clear_edit_form()
            self._set_edit_enabled(False)
            self.dirty_changed.emit(False)
            self.entry_selected.emit(None)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Loi doc SRT", str(e))
            return False

    def save_document(self) -> bool:
        """Write the current entries back to the SRT file. Returns True on success."""
        if self._doc is None:
            return False
        try:
            self._apply_edit_to_doc()
            self._doc.save()
            self._mark_clean()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Loi luu SRT", str(e))
            return False

    def is_dirty(self) -> bool:
        return self._doc.dirty if self._doc else False

    def document(self) -> SubtitleDocument | None:
        return self._doc

    # -------------------------------------------------------------------------
    # UI Construction
    # -------------------------------------------------------------------------

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # Header with file name + action buttons
        header = self._build_header()
        lay.addWidget(header)

        # Entry table
        self._build_table()
        lay.addWidget(self.table, 1)

        # Edit form
        form_group = self._build_edit_form()
        lay.addWidget(form_group)

    def _build_header(self) -> QWidget:
        bar = QWidget()
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(0, 0, 0, 0)
        bar_lay.setSpacing(6)

        self.lbl_file = QLabel("Chua mo file nao")
        self.lbl_file.setStyleSheet("font-size: 12px; color: #6b7280; font-style: italic;")
        bar_lay.addWidget(self.lbl_file)

        bar_lay.addStretch()

        self.btn_save = QPushButton("Luu")
        self.btn_save.setFixedWidth(60)
        self.btn_save.setStyleSheet("font-size: 12px;")
        self.btn_save.clicked.connect(self._on_save)
        bar_lay.addWidget(self.btn_save)

        self.btn_validate = QPushButton("Kiem tra")
        self.btn_validate.setFixedWidth(70)
        self.btn_validate.setStyleSheet("font-size: 12px;")
        self.btn_validate.clicked.connect(self._on_validate)
        bar_lay.addWidget(self.btn_validate)

        self.btn_reload = QPushButton("Tai lai")
        self.btn_reload.setFixedWidth(65)
        self.btn_reload.setStyleSheet("font-size: 12px;")
        self.btn_reload.clicked.connect(self._on_reload)
        bar_lay.addWidget(self.btn_reload)

        return bar

    def _build_table(self):
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["#", "Start", "End", "Text"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet("font-size: 12px;")

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 90)

        self.table.itemSelectionChanged.connect(self._on_table_selection)

    def _build_edit_form(self) -> QGroupBox:
        grp = QGroupBox("Chi tiet entry")
        grp.setStyleSheet("QGroupBox { font-size: 12px; font-weight: 600; }")
        lay = QGridLayout(grp)
        lay.setSpacing(6)

        # Row 0: index
        lay.addWidget(QLabel("Index:"), 0, 0)
        self.spn_idx = QSpinBox()
        self.spn_idx.setReadOnly(True)
        self.spn_idx.setStyleSheet("font-size: 12px;")
        lay.addWidget(self.spn_idx, 0, 1)

        # Row 0: duration (computed)
        lay.addWidget(QLabel("Thoi luong:"), 0, 2)
        self.lbl_dur = QLabel("--")
        self.lbl_dur.setStyleSheet("font-size: 12px; color: #6b7280;")
        lay.addWidget(self.lbl_dur, 0, 3)

        # Row 1: start / end time
        lay.addWidget(QLabel("Start:"), 1, 0)
        self.edit_start = QLineEdit()
        self.edit_start.setPlaceholderText("HH:MM:SS,mmm")
        self.edit_start.setStyleSheet("font-size: 12px;")
        self.edit_start.textChanged.connect(self._on_field_changed)
        lay.addWidget(self.edit_start, 1, 1)

        lay.addWidget(QLabel("End:"), 1, 2)
        self.edit_end = QLineEdit()
        self.edit_end.setPlaceholderText("HH:MM:SS,mmm")
        self.edit_end.setStyleSheet("font-size: 12px;")
        self.edit_end.textChanged.connect(self._on_field_changed)
        lay.addWidget(self.edit_end, 1, 3)

        # Row 2: text (spans 2 columns)
        lay.addWidget(QLabel("Text:"), 2, 0)
        self.edit_text = QTextEdit()
        self.edit_text.setPlaceholderText("Noi dung phu de...")
        self.edit_text.setMinimumHeight(60)
        self.edit_text.setMaximumHeight(100)
        self.edit_text.setStyleSheet("font-size: 12px; font-family: 'Arial';")
        self.edit_text.textChanged.connect(self._on_field_changed)
        lay.addWidget(self.edit_text, 2, 1, 1, 3)

        return grp

    # -------------------------------------------------------------------------
    # Table population
    # -------------------------------------------------------------------------

    def _populate_table(self):
        self.table.setRowCount(0)
        if self._doc is None:
            return

        for entry in self._doc.entries:
            row = self.table.rowCount()
            self.table.insertRow(row)

            idx_item = QTableWidgetItem(str(entry.index))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, idx_item)

            start_item = QTableWidgetItem(entry.start_time)
            start_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, start_item)

            end_item = QTableWidgetItem(entry.end_time)
            end_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, end_item)

            text_item = QTableWidgetItem(entry.text.replace("\n", " "))
            self.table.setItem(row, 3, text_item)

        # Update header
        path = Path(self._doc.file_path)
        self.lbl_file.setText(path.name + (" *" if self._doc.dirty else ""))

    # -------------------------------------------------------------------------
    # Table selection
    # -------------------------------------------------------------------------

    def _on_table_selection(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._clear_edit_form()
            self._set_edit_enabled(False)
            self.entry_selected.emit(None)
            return

        row = rows[0].row()
        self._set_edit_enabled(True)
        self._load_entry_into_form(row)
        self.entry_selected.emit(self._doc.entries[row] if self._doc else None)

    def _load_entry_into_form(self, row: int):
        if self._doc is None or row >= len(self._doc.entries):
            return
        entry = self._doc.entries[row]
        self.spn_idx.setValue(entry.index)
        self.edit_start.setText(entry.start_time)
        self.edit_end.setText(entry.end_time)
        self.edit_text.setPlainText(entry.text)
        dur_ms = entry.duration_ms()
        dur_s = dur_ms / 1000.0
        self.lbl_dur.setText(f"{dur_s:.2f}s ({dur_ms}ms)")

    def _clear_edit_form(self):
        self.spn_idx.setValue(0)
        self.edit_start.clear()
        self.edit_end.clear()
        self.edit_text.clear()
        self.lbl_dur.setText("--")

    def _set_edit_enabled(self, enabled: bool):
        self.edit_start.setEnabled(enabled)
        self.edit_end.setEnabled(enabled)
        self.edit_text.setEnabled(enabled)

    # -------------------------------------------------------------------------
    # Form changes
    # -------------------------------------------------------------------------

    def _on_field_changed(self):
        if self._doc is None:
            return
        # Update live duration label
        try:
            start_ms = self._parse_time(self.edit_start.text())
            end_ms = self._parse_time(self.edit_end.text())
            dur = max(0, end_ms - start_ms)
            self.lbl_dur.setText(f"{dur/1000:.2f}s ({dur}ms)")
        except Exception:
            self.lbl_dur.setText("??")

        self._mark_dirty()

    def _apply_edit_to_doc(self):
        """Apply current form values back to the selected entry."""
        if self._doc is None:
            return
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        entry = self._doc.entries[row]
        entry.start_time = self.edit_start.text().strip()
        entry.end_time = self.edit_end.text().strip()
        entry.text = self.edit_text.toPlainText().strip()
        self._doc.dirty = True
        self.dirty_changed.emit(True)
        self._populate_table()
        self.table.selectRow(row)

    def _mark_dirty(self):
        if self._doc is None:
            return
        if not self._doc.dirty:
            self._doc.dirty = True
            self.dirty_changed.emit(True)
            self.lbl_file.setText(Path(self._doc.file_path).name + " *")

    def _mark_clean(self):
        if self._doc:
            self._doc.dirty = False
            self.dirty_changed.emit(False)
            self.lbl_file.setText(Path(self._doc.file_path).name)

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def _on_save(self):
        if self.save_document():
            self._populate_table()

    def _on_validate(self):
        if self._doc is None:
            QMessageBox.information(self, "Kiem tra", "Chua mo file nao")
            return
        valid, msg = SrtService.validate(self._doc.file_path)
        if valid:
            QMessageBox.information(self, "Kiem tra", msg)
        else:
            QMessageBox.warning(self, "Kiem tra — Co loi", msg)

    def _on_reload(self):
        if self._doc is None:
            return
        if self._doc.dirty:
            reply = QMessageBox.question(
                self, "Tai lai",
                "Co thay doi chua luu. Tai lai se mat cac thay doi nay.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._doc.reload()
        self._populate_table()
        self._clear_edit_form()
        self._set_edit_enabled(False)
        self.dirty_changed.emit(False)

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_time(ts: str) -> int:
        """Parse SRT timestamp to milliseconds. Raises ValueError on bad format."""
        ts = ts.strip().replace(",", ":")
        parts = ts.split(":")
        if len(parts) != 4:
            raise ValueError(f"Bad timestamp: {ts}")
        h, m, s, ms = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        return (h * 3600 + m * 60 + s) * 1000 + ms

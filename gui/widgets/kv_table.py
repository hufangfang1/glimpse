"""
KeyValueTable — a small, reusable editable table for params / headers / cookies.

Each row has an enable checkbox, a key cell, a value cell, and a delete button.
An always-present blank row at the bottom lets the user add entries by simply
typing, mirroring how Postman's key/value editors behave. Rows are exposed as
``(enabled, key, value)`` triples so they round-trip through
:mod:`proxy.collections`.
"""
from __future__ import annotations

from typing import List, Tuple

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from gui.icons import close_x
from gui.i18n import tr

KVRow = Tuple[bool, str, str]


class KeyValueTable(QWidget):
    """Editable key/value grid with per-row enable toggles."""

    changed = pyqtSignal()   # emitted whenever rows are edited/added/removed

    def __init__(self, key_header: str = "Key", value_header: str = "Value", parent=None) -> None:
        super().__init__(parent)
        self._key_header = key_header
        self._value_header = value_header
        # Guard so programmatic edits during _ensure_trailing_row / set_rows
        # don't recursively fire change handling.
        self._suspend = False

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(["", key_header, value_header, ""])
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 32)
        self._table.setColumnWidth(3, 36)

        self._table.cellChanged.connect(self._on_cell_changed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table)

        self._ensure_trailing_row()

    # ------------------------------------------------------------------ #
    # i18n
    # ------------------------------------------------------------------ #

    def retranslate(self, key_header: str | None = None, value_header: str | None = None) -> None:
        if key_header is not None:
            self._key_header = key_header
        if value_header is not None:
            self._value_header = value_header
        self._table.setHorizontalHeaderLabels(["", self._key_header, self._value_header, ""])

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def set_rows(self, rows: List[KVRow]) -> None:
        self._suspend = True
        try:
            self._table.setRowCount(0)
            for enabled, key, value in rows:
                self._append_row(enabled, key, value)
        finally:
            self._suspend = False
        self._ensure_trailing_row()
        self.changed.emit()

    def rows(self, *, enabled_only: bool = False) -> List[KVRow]:
        """Return non-empty rows. The trailing blank row is skipped."""
        out: List[KVRow] = []
        for r in range(self._table.rowCount()):
            key = self._cell_text(r, 1)
            value = self._cell_text(r, 2)
            if not key and not value:
                continue
            enabled = self._is_checked(r)
            if enabled_only and not enabled:
                continue
            out.append((enabled, key, value))
        return out

    # ------------------------------------------------------------------ #
    # Row construction
    # ------------------------------------------------------------------ #

    def _append_row(self, enabled: bool, key: str, value: str) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        check = QTableWidgetItem()
        check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        check.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        check.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, 0, check)

        self._table.setItem(row, 1, QTableWidgetItem(key))
        self._table.setItem(row, 2, QTableWidgetItem(value))

        delete = QPushButton()
        delete.setObjectName("kv_delete_btn")
        delete.setIcon(close_x("#a6adc8", 12))
        delete.setIconSize(QSize(12, 12))
        delete.setFixedSize(28, 28)
        delete.setToolTip(tr("editor.kv.delete"))
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.clicked.connect(lambda _=False: self._delete_row_widget(delete))
        self._table.setCellWidget(row, 3, delete)

    def _delete_row_widget(self, button: QPushButton) -> None:
        for r in range(self._table.rowCount()):
            if self._table.cellWidget(r, 3) is button:
                self._table.removeRow(r)
                self._ensure_trailing_row()
                self.changed.emit()
                return

    def _ensure_trailing_row(self) -> None:
        """Guarantee exactly one empty editable row at the end."""
        self._suspend = True
        try:
            count = self._table.rowCount()
            if count == 0:
                self._append_row(True, "", "")
                return
            last_key = self._cell_text(count - 1, 1)
            last_val = self._cell_text(count - 1, 2)
            if last_key or last_val:
                self._append_row(True, "", "")
        finally:
            self._suspend = False

    # ------------------------------------------------------------------ #
    # Slots / helpers
    # ------------------------------------------------------------------ #

    def _on_cell_changed(self, _row: int, _col: int) -> None:
        if self._suspend:
            return
        self._ensure_trailing_row()
        self.changed.emit()

    def _cell_text(self, row: int, col: int) -> str:
        item = self._table.item(row, col)
        return item.text().strip() if item is not None else ""

    def _is_checked(self, row: int) -> bool:
        item = self._table.item(row, 0)
        return item is not None and item.checkState() == Qt.CheckState.Checked

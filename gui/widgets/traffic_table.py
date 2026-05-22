"""
Traffic table — displays captured HTTP flows.
"""
from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from proxy.models import FlowModel
from gui.themes import METHOD_COLORS, status_color

COLUMNS = ["#", "Method", "Status", "Host", "Path", "Type", "Size", "Time"]


class TrafficModel(QAbstractTableModel):
    """Qt data model backing the traffic table."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._flows: List[FlowModel] = []

    # ------------------------------------------------------------------ #
    # QAbstractTableModel interface
    # ------------------------------------------------------------------ #

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._flows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        flow = self._flows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(flow, index.row(), col)

        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(flow, col)

        if role == Qt.ItemDataRole.FontRole:
            if col in (1, 2):   # Method / Status — slightly bold
                f = QFont()
                f.setWeight(QFont.Weight.Medium)
                return f

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (0, 2, 6, 7):
                return Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.UserRole:
            return flow

        return None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _display(self, f: FlowModel, row: int, col: int) -> str:
        if col == 0: return str(row + 1)
        if col == 1: return f.method
        if col == 2: return str(f.status_code) if f.status_code else ("-" if not f.error else "ERR")
        if col == 3: return f.host
        if col == 4: return f.path or "/"
        if col == 5: return f.display_type() or "-"
        if col == 6: return f.format_size()
        if col == 7: return f.format_duration()
        return ""

    def _foreground(self, f: FlowModel, col: int) -> Optional[QColor]:
        if col == 1:
            colors = METHOD_COLORS.get(f.method, ("#cdd6f4", "#2a2a3e"))
            return QColor(colors[0])
        if col == 2:
            return QColor(status_color(f.status_code))
        return None

    # ------------------------------------------------------------------ #
    # Public mutations
    # ------------------------------------------------------------------ #

    def append_flow(self, flow: FlowModel) -> None:
        row = len(self._flows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._flows.append(flow)
        self.endInsertRows()

    def update_flow(self, flow: FlowModel) -> None:
        """Update an existing flow (e.g., WebSocket ended)."""
        for i, f in enumerate(self._flows):
            if f.id == flow.id:
                self._flows[i] = flow
                top_left = self.index(i, 0)
                bottom_right = self.index(i, len(COLUMNS) - 1)
                self.dataChanged.emit(top_left, bottom_right)
                return
        self.append_flow(flow)

    def clear(self) -> None:
        self.beginResetModel()
        self._flows.clear()
        self.endResetModel()

    def pop_oldest(self, count: int) -> List[FlowModel]:
        """Remove and return the oldest *count* flows."""
        if count <= 0:
            return []
        count = min(count, len(self._flows))
        removed = self._flows[:count]
        self.beginRemoveRows(QModelIndex(), 0, count - 1)
        self._flows = self._flows[count:]
        self.endRemoveRows()
        return removed

    def flow_at(self, row: int) -> Optional[FlowModel]:
        if 0 <= row < len(self._flows):
            return self._flows[row]
        return None

    def all_flows(self) -> List[FlowModel]:
        return list(self._flows)


class TrafficTable(QWidget):
    """Traffic table widget with built-in filter proxy."""

    flow_selected = pyqtSignal(object)   # emits FlowModel | None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._model = TrafficModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)          # search all columns

        self._view = QTableView()
        self._view.setModel(self._proxy)
        self._view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setAlternatingRowColors(True)
        self._view.setShowGrid(False)
        self._view.verticalHeader().setVisible(False)
        self._view.horizontalHeader().setStretchLastSection(False)
        self._view.setWordWrap(False)
        self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.setSortingEnabled(False)
        self._view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        hh = self._view.horizontalHeader()
        hh.setSectionsMovable(False)
        hh.setStretchLastSection(False)
        hh.setCascadingSectionResizes(False)
        hh.setMinimumSectionSize(48)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        col_widths = [40, 72, 58, 160, 240, 120, 72, 72]
        for col, width in enumerate(col_widths):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            hh.resizeSection(col, width)

        self._view.selectionModel().selectionChanged.connect(self._on_selection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def append_flow(self, flow: FlowModel) -> None:
        self._model.append_flow(flow)
        if self._view.verticalScrollBar().value() >= self._view.verticalScrollBar().maximum() - 40:
            self._view.scrollToBottom()

    def update_flow(self, flow: FlowModel) -> None:
        self._model.update_flow(flow)

    def clear(self) -> None:
        self._model.clear()
        self.flow_selected.emit(None)

    def set_filter(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)

    def count(self) -> int:
        return self._model.rowCount()

    def pop_oldest(self, count: int) -> List[FlowModel]:
        return self._model.pop_oldest(count)

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #

    def _on_selection(self) -> None:
        indexes = self._view.selectionModel().selectedRows()
        if not indexes:
            self.flow_selected.emit(None)
            return
        proxy_index = indexes[0]
        source_index = self._proxy.mapToSource(proxy_index)
        flow = self._model.flow_at(source_index.row())
        self.flow_selected.emit(flow)

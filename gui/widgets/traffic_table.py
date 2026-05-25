"""
Traffic table — displays captured HTTP flows.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from proxy.models import FlowModel
from gui.i18n import i18n, tr
from gui.themes import METHOD_COLORS, status_color

# Column ids — used both as canonical identifiers and i18n keys.
COLUMN_KEYS = [
    "col.seq",
    "col.method",
    "col.status",
    "col.host",
    "col.path",
    "col.type",
    "col.size",
    "col.duration",
    "col.time",
]

# Custom role used by the proxy model when sorting — lets us return typed
# values (ints / floats / datetimes) instead of the displayed strings.
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class TrafficModel(QAbstractTableModel):
    """Qt data model backing the traffic table."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._flows: List[FlowModel] = []
        self._seqs: List[int] = []
        self._next_seq = 0

    # ------------------------------------------------------------------ #
    # QAbstractTableModel interface
    # ------------------------------------------------------------------ #

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._flows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMN_KEYS)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return tr(COLUMN_KEYS[section])
        return None

    def retranslate(self) -> None:
        """Force header view to repaint translated column titles."""
        if self.columnCount():
            self.headerDataChanged.emit(
                Qt.Orientation.Horizontal, 0, self.columnCount() - 1
            )

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        flow = self._flows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(flow, index.row(), col)

        if role == SORT_ROLE:
            return self._sort_key(flow, index.row(), col)

        if role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(flow, col)

        if role == Qt.ItemDataRole.FontRole:
            if col in (1, 2):   # Method / Status — slightly bold
                f = QFont()
                f.setWeight(QFont.Weight.Medium)
                return f

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (0, 2, 6, 7, 8):
                return Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.UserRole:
            return flow

        return None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _display(self, f: FlowModel, row: int, col: int) -> str:
        if col == 0: return str(self._seqs[row])
        if col == 1: return f.method
        if col == 2:
            if f.status_code:
                return str(f.status_code)
            return "ERR" if f.error else "-"
        if col == 3: return f.host
        if col == 4: return f.path or "/"
        if col == 5: return f.display_type() or "-"
        if col == 6: return f.format_size()
        if col == 7: return f.format_duration()
        if col == 8: return f.timestamp.strftime("%H:%M:%S.%f")[:-3]
        return ""

    def _sort_key(self, f: FlowModel, row: int, col: int):
        # Return typed values so sorting works numerically/chronologically.
        if col == 0: return self._seqs[row]
        if col == 1: return f.method
        if col == 2:
            # Errors and missing statuses sort to the bottom in ascending order.
            return f.status_code if f.status_code is not None else 10_000
        if col == 3: return f.host
        if col == 4: return f.path or "/"
        if col == 5: return f.display_type() or ""
        if col == 6: return f.response_size
        if col == 7: return f.duration
        if col == 8: return f.timestamp.timestamp()
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
        self._next_seq += 1
        self._seqs.append(self._next_seq)
        self.endInsertRows()

    def update_flow(self, flow: FlowModel) -> None:
        """Update an existing flow (e.g., WebSocket ended)."""
        for i, f in enumerate(self._flows):
            if f.id == flow.id:
                self._flows[i] = flow
                top_left = self.index(i, 0)
                bottom_right = self.index(i, len(COLUMN_KEYS) - 1)
                self.dataChanged.emit(top_left, bottom_right)
                return
        self.append_flow(flow)

    def clear(self) -> None:
        self.beginResetModel()
        self._flows.clear()
        self._seqs.clear()
        self._next_seq = 0
        self.endResetModel()

    def pop_oldest(self, count: int) -> List[FlowModel]:
        """Remove and return the oldest *count* flows."""
        if count <= 0:
            return []
        count = min(count, len(self._flows))
        removed = self._flows[:count]
        self.beginRemoveRows(QModelIndex(), 0, count - 1)
        self._flows = self._flows[count:]
        self._seqs = self._seqs[count:]
        self.endRemoveRows()
        return removed

    def remove_flow(self, flow_id: str) -> Optional[FlowModel]:
        for i, f in enumerate(self._flows):
            if f.id == flow_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                removed = self._flows.pop(i)
                self._seqs.pop(i)
                self.endRemoveRows()
                return removed
        return None

    def flow_at(self, row: int) -> Optional[FlowModel]:
        if 0 <= row < len(self._flows):
            return self._flows[row]
        return None

    def all_flows(self) -> List[FlowModel]:
        return list(self._flows)


class TrafficTable(QWidget):
    """Traffic table widget with built-in filter proxy."""

    flow_selected = pyqtSignal(object)      # emits FlowModel | None
    replay_requested = pyqtSignal(object)   # emits FlowModel
    delete_requested = pyqtSignal(object)   # emits FlowModel
    filter_host_requested = pyqtSignal(str) # emits host string
    scope_add_requested = pyqtSignal(str, str)  # (action, pattern) — action: "allow"|"block"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._model = TrafficModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)          # search all columns
        self._proxy.setSortRole(SORT_ROLE)
        self._proxy.setDynamicSortFilter(True)

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
        self._view.setSortingEnabled(True)
        self._view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        self._view.doubleClicked.connect(self._on_double_clicked)

        hh = self._view.horizontalHeader()
        hh.setSectionsMovable(False)
        hh.setStretchLastSection(False)
        hh.setCascadingSectionResizes(False)
        hh.setMinimumSectionSize(48)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setSortIndicatorShown(True)
        hh.setSortIndicator(0, Qt.SortOrder.AscendingOrder)

        col_widths = [44, 72, 58, 160, 240, 120, 72, 78, 96]
        for col, width in enumerate(col_widths):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            hh.resizeSection(col, width)

        self._view.selectionModel().selectionChanged.connect(self._on_selection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        i18n.language_changed.connect(self._on_language_changed)

    # ------------------------------------------------------------------ #
    # i18n
    # ------------------------------------------------------------------ #

    def _on_language_changed(self, _lang: str) -> None:
        self._model.retranslate()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def append_flow(self, flow: FlowModel) -> None:
        self._model.append_flow(flow)
        # Only auto-follow when the user is sorted by arrival order ascending
        # (otherwise scrolling to bottom would jump them away from their sort).
        sort_col = self._view.horizontalHeader().sortIndicatorSection()
        sort_order = self._view.horizontalHeader().sortIndicatorOrder()
        following = sort_col == 0 and sort_order == Qt.SortOrder.AscendingOrder
        if following and self._view.verticalScrollBar().value() >= self._view.verticalScrollBar().maximum() - 40:
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

    def remove_flow(self, flow_id: str) -> Optional[FlowModel]:
        return self._model.remove_flow(flow_id)

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #

    def _flow_at_proxy_row(self, proxy_row: int) -> Optional[FlowModel]:
        source_row = self._proxy.mapToSource(self._proxy.index(proxy_row, 0)).row()
        return self._model.flow_at(source_row)

    def _on_selection(self) -> None:
        indexes = self._view.selectionModel().selectedRows()
        if not indexes:
            self.flow_selected.emit(None)
            return
        flow = self._flow_at_proxy_row(indexes[0].row())
        self.flow_selected.emit(flow)

    def _on_double_clicked(self, index) -> None:
        flow = self._flow_at_proxy_row(index.row())
        if flow:
            self.replay_requested.emit(flow)

    def _on_context_menu(self, pos) -> None:
        index = self._view.indexAt(pos)
        if not index.isValid():
            return

        flow = self._flow_at_proxy_row(index.row())
        if flow is None:
            return

        menu = QMenu(self)
        menu.setSeparatorsCollapsible(False)

        # ── Header: shows what the menu is targeting (disabled, italic). ──
        header_text = self._format_menu_header(flow)
        header_act = QAction(header_text, menu)
        header_act.setEnabled(False)
        font = header_act.font()
        font.setItalic(True)
        font.setPointSize(max(font.pointSize() - 1, 10))
        header_act.setFont(font)
        menu.addAction(header_act)
        menu.addSeparator()

        # ── Copy group ──
        self._add_menu_action(menu, "📋", tr("ctx.copy_url"),
                              lambda: self._copy_to_clipboard(flow.url))
        self._add_menu_action(menu, "🔧", tr("ctx.copy_curl"),
                              lambda: self._copy_to_clipboard(flow.to_curl()))
        if flow.host:
            self._add_menu_action(menu, "🌐", tr("ctx.copy_host"),
                                  lambda: self._copy_to_clipboard(flow.host))
        if flow.path:
            self._add_menu_action(menu, "🧭", tr("ctx.copy_path"),
                                  lambda: self._copy_to_clipboard(flow.path))
        if flow.response_body:
            text, _ = flow.get_response_body_display()
            self._add_menu_action(menu, "📥", tr("ctx.copy_body"),
                                  lambda t=text: self._copy_to_clipboard(t))

        menu.addSeparator()

        # ── Replay ──
        self._add_menu_action(menu, "↩", tr("ctx.replay"),
                              lambda: self.replay_requested.emit(flow))

        # ── Scope / filter group ──
        if flow.host:
            menu.addSeparator()
            self._add_menu_action(
                menu, "🔎",
                tr("ctx.filter_host", host=flow.host),
                lambda: self.filter_host_requested.emit(flow.host),
            )

            allow_menu = menu.addMenu(self._submenu_title("✅", tr("ctx.add_allow")))
            self._populate_scope_menu(allow_menu, "allow", flow.host)

            block_menu = menu.addMenu(self._submenu_title("🚫", tr("ctx.add_block")))
            self._populate_scope_menu(block_menu, "block", flow.host)

        menu.addSeparator()

        # ── Destructive — visually separated and colored red ──
        delete_act = self._add_menu_action(
            menu, "🗑", tr("ctx.delete"),
            lambda: self.delete_requested.emit(flow),
        )
        delete_font = delete_act.font()
        delete_font.setWeight(500)
        delete_act.setFont(delete_font)

        menu.exec(self._view.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ #
    # Context menu helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _icon_prefix(icon: str) -> str:
        """Pad an emoji icon so it lines up with text-only menu rows."""
        return f"{icon}   "

    @staticmethod
    def _submenu_title(icon: str, label: str) -> str:
        """Menu title with left emoji and right-aligned chevron (replaces native arrow)."""
        return f"{TrafficTable._icon_prefix(icon)}{label}\t▸"

    def _add_menu_action(self, menu: QMenu, icon: str, label: str, callback) -> QAction:
        action = QAction(self._icon_prefix(icon) + label, menu)
        action.triggered.connect(callback)
        menu.addAction(action)
        return action

    @staticmethod
    def _format_menu_header(flow: FlowModel) -> str:
        """Compact METHOD + host/path summary shown at the top of the menu."""
        path = flow.path or "/"
        if len(path) > 48:
            path = path[:45] + "…"
        host = flow.host or ""
        if host and path.startswith("/"):
            return f"{flow.method}  {host}{path}"
        return f"{flow.method}  {path}"

    def _populate_scope_menu(self, menu: QMenu, action: str, host: str) -> None:
        """Fill the Allow/Block submenu with one or two suggested patterns."""
        patterns = self._scope_suggestions(host)
        for pattern in patterns:
            act = QAction(pattern, menu)
            # late-binding closure: capture `pattern` explicitly.
            act.triggered.connect(
                lambda _checked=False, p=pattern: self.scope_add_requested.emit(action, p)
            )
            menu.addAction(act)

    @staticmethod
    def _scope_suggestions(host: str) -> List[str]:
        host = (host or "").strip()
        if not host:
            return []
        suggestions = [host]
        if not TrafficTable._looks_like_ip(host):
            parts = host.split(".")
            # Only suggest a wildcard when the host has a clear subdomain
            # (e.g. api.example.com → *.example.com). Skip bare 2-segment
            # domains so we don't propose `*.com`.
            if len(parts) >= 3:
                wildcard = "*." + ".".join(parts[-2:])
                if wildcard != host:
                    suggestions.append(wildcard)
        return suggestions

    @staticmethod
    def _looks_like_ip(host: str) -> bool:
        parts = host.split(".")
        if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            return True
        return ":" in host  # crude IPv6 check

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text or "")

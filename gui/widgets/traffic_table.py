"""
Traffic table — displays captured HTTP flows.
"""
from __future__ import annotations

import fnmatch
import re
from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QAction, QColor, QFont, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QStackedWidget,
    QTableView,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from proxy.models import FlowModel
from gui.i18n import i18n, tr
from gui.themes import METHOD_COLORS, status_color

# Column ids — used both as canonical identifiers and i18n keys.
COLUMN_KEYS = [
    "col.seq",
    "col.host",
    "col.path",
    "col.method",
    "col.status",
    "col.type",
    "col.size",
    "col.duration",
    "col.time",
]

DEFAULT_COL_WIDTHS = [44, 160, 240, 72, 58, 120, 72, 78, 96]

# Row tag colours (name, swatch emoji, dark-tint hex applied as row background).
TAG_COLORS = [
    ("red", "🔴", "#3a2730"),
    ("yellow", "🟡", "#3a3727"),
    ("green", "🟢", "#273a2c"),
    ("blue", "🔵", "#27313a"),
]

# Custom role used by the proxy model when sorting — lets us return typed
# values (ints / floats / datetimes) instead of the displayed strings.
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


def _match_status(code: Optional[int], val: str) -> bool:
    if code is None:
        return False
    val = val.lower()
    if len(val) == 3 and val[1:] == "xx" and val[0].isdigit():
        return str(code)[0] == val[0]                 # 5xx / 4xx class
    m = re.match(r"(>=|<=|>|<)(\d+)$", val)
    if m:
        op, num = m.group(1), int(m.group(2))
        return {">": code > num, ">=": code >= num,
                "<": code < num, "<=": code <= num}[op]
    return val.isdigit() and code == int(val)         # exact


def _match_duration(dur: float, val: str) -> bool:
    m = re.match(r"(>=|<=|>|<)?\s*([\d.]+)\s*(ms|s)?$", val.lower())
    if not m:
        return False
    op = m.group(1) or ">"
    threshold = float(m.group(2)) / (1000 if (m.group(3) or "ms") == "ms" else 1)
    return {">": dur > threshold, ">=": dur >= threshold,
            "<": dur < threshold, "<=": dur <= threshold}[op]


def _match_glob(value: str, pat: str) -> bool:
    value, pat = value.lower(), pat.lower()
    if "*" in pat or "?" in pat:
        return fnmatch.fnmatch(value, pat)
    return pat in value                               # plain substring


def _token_matches(flow: FlowModel, tok: str) -> bool:
    if ":" in tok:
        key, _, val = tok.partition(":")
        key, val = key.lower(), val.strip()
        if not val:
            return True
        if key == "status":
            return _match_status(flow.status_code, val)
        if key == "host":
            return _match_glob(flow.host or "", val)
        if key == "path":
            return _match_glob(flow.path or "", val)
        if key == "method":
            return (flow.method or "").lower() == val.lower()
        if key == "slow":
            return _match_duration(flow.duration, val)
        if key == "is":
            v = val.lower()
            if v == "flagged":
                return bool(flow.flagged)
            if v == "tagged":
                return bool(flow.tag_color)
            if v == "noted":
                return bool(flow.note)
            return False
        # unknown key → fall through to free-text matching of the whole token
    t = tok.lower()
    return (t in (flow.host or "").lower()
            or t in (flow.path or "").lower()
            or t in (flow.method or "").lower())


def flow_matches_query(flow: FlowModel, query: str) -> bool:
    """Structured filter: space-separated predicates, ANDed together.

    Examples: ``status:500``  ``status:5xx``  ``host:u.api.*``  ``method:POST``
    ``slow:>500ms``  ``status:>=400 host:*orangevip*``  or plain substrings.
    """
    return all(_token_matches(flow, tok) for tok in query.split())


class TrafficFilterProxy(QSortFilterProxyModel):
    """Filter proxy: structured query language above, plus muted hosts."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._query = ""
        self._muted: set[str] = set()

    def set_query(self, text: str) -> None:
        self._query = text or ""
        self.invalidateFilter()

    def mute(self, host: str) -> None:
        if host:
            self._muted.add(host.lower())
            self.invalidateFilter()

    def unmute(self, host: str) -> None:
        self._muted.discard((host or "").lower())
        self.invalidateFilter()

    def clear_muted(self) -> None:
        if self._muted:
            self._muted.clear()
            self.invalidateFilter()

    def is_muted(self, host: str) -> bool:
        return (host or "").lower() in self._muted

    def muted_hosts(self) -> set:
        return set(self._muted)

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        model = self.sourceModel()
        flow = model.data(model.index(source_row, 0, source_parent),
                          Qt.ItemDataRole.UserRole)
        if flow is None:
            return True
        if flow.host and flow.host.lower() in self._muted:
            return False
        return not self._query.strip() or flow_matches_query(flow, self._query)


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

        if role == Qt.ItemDataRole.BackgroundRole and flow.tag_color:
            return QColor(flow.tag_color)

        if role == Qt.ItemDataRole.ToolTipRole and flow.note:
            return flow.note

        if role == Qt.ItemDataRole.FontRole:
            if col in (3, 4):   # Method / Status — slightly bold
                f = QFont()
                f.setWeight(QFont.Weight.Medium)
                return f

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (0, 4, 6, 7, 8):
                return Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.UserRole:
            return flow

        return None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _display(self, f: FlowModel, row: int, col: int) -> str:
        if col == 0: return ("★ " if f.flagged else "") + str(self._seqs[row])
        if col == 1: return f.host
        if col == 2: return f.path or "/"
        if col == 3: return f.method
        if col == 4:
            if f.status_code:
                return str(f.status_code)
            return "ERR" if f.error else "-"
        if col == 5: return f.display_type() or "-"
        if col == 6: return f.format_size()
        if col == 7: return f.format_duration()
        if col == 8: return f.timestamp.strftime("%H:%M:%S.%f")[:-3]
        return ""

    def _sort_key(self, f: FlowModel, row: int, col: int):
        # Return typed values so sorting works numerically/chronologically.
        if col == 0: return self._seqs[row]
        if col == 1: return f.host
        if col == 2: return f.path or "/"
        if col == 3: return f.method
        if col == 4:
            # Errors and missing statuses sort to the bottom in ascending order.
            return f.status_code if f.status_code is not None else 10_000
        if col == 5: return f.display_type() or ""
        if col == 6: return f.response_size
        if col == 7: return f.duration
        if col == 8: return f.timestamp.timestamp()
        return ""

    def _foreground(self, f: FlowModel, col: int) -> Optional[QColor]:
        if col == 3:
            colors = METHOD_COLORS.get(f.method, ("#cdd6f4", "#2a2a3e"))
            return QColor(colors[0])
        if col == 4:
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

    def mark_flow_changed(self, flow: FlowModel) -> None:
        """Repaint a row after its annotations (flag / note / colour) change."""
        for i, f in enumerate(self._flows):
            if f is flow:
                tl = self.index(i, 0)
                br = self.index(i, len(COLUMN_KEYS) - 1)
                self.dataChanged.emit(tl, br)
                return

    def flows_with_seq(self) -> list:
        """[(seq, flow), …] in arrival order — used to build the grouped tree."""
        return list(zip(self._seqs, self._flows))

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
    inspect_requested = pyqtSignal(object)  # emits FlowModel (open standalone window)
    replay_requested = pyqtSignal(object)   # emits FlowModel
    delete_requested = pyqtSignal(object)   # emits FlowModel
    filter_host_requested = pyqtSignal(str) # emits host string
    scope_add_requested = pyqtSignal(str, str)  # (action, pattern) — action: "allow"|"block"
    muted_changed = pyqtSignal()            # muted-host set changed (refresh counts/status)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._model = TrafficModel()
        self._proxy = TrafficFilterProxy()
        self._proxy.setSourceModel(self._model)
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
        hh.setSectionsMovable(True)   # drag column headers to reorder
        hh.setStretchLastSection(False)
        hh.setCascadingSectionResizes(False)
        hh.setMinimumSectionSize(48)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setSortIndicatorShown(True)
        hh.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        hh.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hh.customContextMenuRequested.connect(self._on_header_menu)

        for col, width in enumerate(DEFAULT_COL_WIDTHS):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            hh.resizeSection(col, width)

        self._view.selectionModel().selectionChanged.connect(self._on_selection)
        # Re-emit when clicking the already-selected row (e.g. switch back from collections).
        self._view.clicked.connect(self._on_row_clicked)

        # Grouped view (by host): a tree rebuilt from the flat model on demand.
        self._grouped = False
        self._tree_model = QStandardItemModel(self)
        self._tree = QTreeView()
        self._tree.setModel(self._tree_model)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(18)
        # Native branch arrows render black (invisible on the dark bg); swap in the
        # light chevron PNGs used elsewhere via QSS.
        from gui.icons import ensure_tree_branch_icons
        _br = ensure_tree_branch_icons()
        self._tree.setStyleSheet(
            "QTreeView::branch:has-children:!has-siblings:closed,"
            "QTreeView::branch:closed:has-children:has-siblings {"
            f'  border-image: none; image: url("{_br["closed"]}"); }}'
            "QTreeView::branch:open:has-children:!has-siblings,"
            "QTreeView::branch:open:has-children:has-siblings {"
            f'  border-image: none; image: url("{_br["open"]}"); }}'
        )
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._tree.doubleClicked.connect(self._on_tree_double_clicked)
        self._tree.selectionModel().selectionChanged.connect(self._on_tree_selection)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._view)   # 0 — flat table
        self._stack.addWidget(self._tree)   # 1 — grouped tree

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        i18n.language_changed.connect(self._on_language_changed)

    # ------------------------------------------------------------------ #
    # i18n
    # ------------------------------------------------------------------ #

    def _on_language_changed(self, _lang: str) -> None:
        self._model.retranslate()
        self._refresh_grouped()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def append_flow(self, flow: FlowModel) -> None:
        self._model.append_flow(flow)
        self._refresh_grouped()
        # Only auto-follow when the user is sorted by arrival order ascending
        # (otherwise scrolling to bottom would jump them away from their sort).
        sort_col = self._view.horizontalHeader().sortIndicatorSection()
        sort_order = self._view.horizontalHeader().sortIndicatorOrder()
        following = sort_col == 0 and sort_order == Qt.SortOrder.AscendingOrder
        if following and self._view.verticalScrollBar().value() >= self._view.verticalScrollBar().maximum() - 40:
            self._view.scrollToBottom()

    def update_flow(self, flow: FlowModel) -> None:
        self._model.update_flow(flow)
        self._refresh_grouped()

    def clear(self) -> None:
        self._model.clear()
        self._refresh_grouped()
        self.flow_selected.emit(None)

    def set_filter(self, text: str) -> None:
        self._proxy.set_query(text)
        self._refresh_grouped()

    def count(self) -> int:
        return self._model.rowCount()

    def visible_count(self) -> int:
        """Rows currently passing the filter (≤ count())."""
        return self._proxy.rowCount()

    def mute_host(self, host: str) -> None:
        self._proxy.mute(host)
        self.muted_changed.emit()
        self._refresh_grouped()

    def unmute_host(self, host: str) -> None:
        self._proxy.unmute(host)
        self.muted_changed.emit()
        self._refresh_grouped()

    def clear_muted(self) -> None:
        self._proxy.clear_muted()
        self.muted_changed.emit()
        self._refresh_grouped()

    def is_host_muted(self, host: str) -> bool:
        return self._proxy.is_muted(host)

    def muted_hosts(self) -> set:
        return self._proxy.muted_hosts()

    def set_compact(self, compact: bool) -> None:
        """Toggle compact row height for scanning lots of traffic at once."""
        vh = self._view.verticalHeader()
        if not hasattr(self, "_default_row_h"):
            self._default_row_h = vh.defaultSectionSize()
        vh.setDefaultSectionSize(22 if compact else self._default_row_h)

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

    def _on_row_clicked(self, index) -> None:
        if not index.isValid():
            return
        flow = self._flow_at_proxy_row(index.row())
        if flow is not None:
            self.flow_selected.emit(flow)

    def _on_double_clicked(self, index) -> None:
        flow = self._flow_at_proxy_row(index.row())
        if flow:
            self.inspect_requested.emit(flow)

    def _on_header_menu(self, pos) -> None:
        """Right-click the header to show/hide columns; drag headers to reorder."""
        hh = self._view.horizontalHeader()
        menu = QMenu(self)
        menu.setSeparatorsCollapsible(False)

        title = QAction(tr("col.menu.title"), menu)
        title.setEnabled(False)
        f = title.font()
        f.setItalic(True)
        f.setPointSize(max(f.pointSize() - 1, 10))
        title.setFont(f)
        menu.addAction(title)
        menu.addSeparator()

        visible = sum(1 for c in range(hh.count()) if not hh.isSectionHidden(c))
        for col in range(hh.count()):
            act = QAction(tr(COLUMN_KEYS[col]), menu)
            act.setCheckable(True)
            shown = not hh.isSectionHidden(col)
            act.setChecked(shown)
            if shown and visible <= 1:
                act.setEnabled(False)   # never hide the last visible column
            act.toggled.connect(lambda checked, c=col: hh.setSectionHidden(c, not checked))
            menu.addAction(act)

        menu.addSeparator()
        reset = QAction(tr("col.menu.reset"), menu)
        reset.triggered.connect(self._reset_columns)
        menu.addAction(reset)
        menu.exec(hh.mapToGlobal(pos))

    def _reset_columns(self) -> None:
        """Restore default column order, visibility and widths."""
        hh = self._view.horizontalHeader()
        for logical in range(hh.count()):
            vis = hh.visualIndex(logical)
            if vis != logical:
                hh.moveSection(vis, logical)
        for col, width in enumerate(DEFAULT_COL_WIDTHS):
            hh.setSectionHidden(col, False)
            hh.resizeSection(col, width)

    def _on_context_menu(self, pos) -> None:
        index = self._view.indexAt(pos)
        if not index.isValid():
            return
        flow = self._flow_at_proxy_row(index.row())
        if flow is not None:
            self._show_flow_menu(flow, self._view.viewport().mapToGlobal(pos))

    def _show_flow_menu(self, flow: FlowModel, global_pos) -> None:
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

        # ── Open in standalone window / Replay ──
        self._add_menu_action(menu, "⧉", tr("traffic.menu.open_inspector"),
                              lambda: self.inspect_requested.emit(flow))
        self._add_menu_action(menu, "↩", tr("ctx.replay"),
                              lambda: self.replay_requested.emit(flow))

        # ── Annotate group (flag / colour / note) ──
        menu.addSeparator()
        flag_icon = "★" if flow.flagged else "☆"
        flag_label = tr("ctx.unflag") if flow.flagged else tr("ctx.flag")
        self._add_menu_action(menu, flag_icon, flag_label,
                              lambda: self._toggle_flag(flow))
        color_menu = menu.addMenu(self._submenu_title("🎨", tr("ctx.color")))
        for name, emoji, hexv in TAG_COLORS:
            self._add_menu_action(color_menu, emoji, tr("ctx.tag." + name),
                                  lambda h=hexv: self._set_tag_color(flow, h))
        color_menu.addSeparator()
        self._add_menu_action(color_menu, "⚪", tr("ctx.tag.clear"),
                              lambda: self._set_tag_color(flow, ""))
        note_label = tr("ctx.note.edit") if flow.note else tr("ctx.note.add")
        self._add_menu_action(menu, "📝", note_label,
                              lambda: self._edit_note(flow))

        # ── Scope / filter group ──
        if flow.host:
            menu.addSeparator()
            self._add_menu_action(
                menu, "🔎",
                tr("ctx.filter_host", host=flow.host),
                lambda: self.filter_host_requested.emit(flow.host),
            )
            if self.is_host_muted(flow.host):
                self._add_menu_action(menu, "🔊", tr("ctx.unmute", host=flow.host),
                                      lambda: self.unmute_host(flow.host))
            else:
                self._add_menu_action(menu, "🔇", tr("ctx.mute", host=flow.host),
                                      lambda: self.mute_host(flow.host))

            allow_menu = menu.addMenu(self._submenu_title("✅", tr("ctx.add_allow")))
            self._populate_scope_menu(allow_menu, "allow", flow.host)

            block_menu = menu.addMenu(self._submenu_title("🚫", tr("ctx.add_block")))
            self._populate_scope_menu(block_menu, "block", flow.host)

        if self.muted_hosts():
            self._add_menu_action(
                menu, "🔊", tr("ctx.unmute_all", n=len(self.muted_hosts())),
                self.clear_muted,
            )

        menu.addSeparator()

        # ── Destructive — visually separated and colored red ──
        delete_act = self._add_menu_action(
            menu, "🗑", tr("ctx.delete"),
            lambda: self.delete_requested.emit(flow),
        )
        delete_font = delete_act.font()
        delete_font.setWeight(500)
        delete_act.setFont(delete_font)

        menu.exec(global_pos)

    # ------------------------------------------------------------------ #
    # Grouped view (by host)
    # ------------------------------------------------------------------ #

    def set_grouped(self, grouped: bool) -> None:
        self._grouped = bool(grouped)
        if self._grouped:
            self._rebuild_tree()
        self._stack.setCurrentIndex(1 if self._grouped else 0)

    def _refresh_grouped(self) -> None:
        if self._grouped:
            self._rebuild_tree()

    @staticmethod
    def _status_text(f: FlowModel) -> str:
        if f.status_code:
            return str(f.status_code)
        return "ERR" if f.error else "-"

    def _rebuild_tree(self) -> None:
        """Rebuild the host-grouped tree from the flat model (filter + mute applied)."""
        self._tree_model.clear()
        self._tree_model.setHorizontalHeaderLabels(
            [tr("col.group"), tr("col.method"), tr("col.status"), tr("col.seq")]
        )
        query = self._proxy._query
        groups: dict = {}
        for seq, flow in self._model.flows_with_seq():
            host = flow.host or "—"
            if self._proxy.is_muted(host):
                continue
            if query.strip() and not flow_matches_query(flow, query):
                continue
            groups.setdefault(host, []).append((seq, flow))

        for host in sorted(groups):
            rows = groups[host]
            g0 = QStandardItem(f"{host}  ({len(rows)})")
            grp = [g0, QStandardItem(), QStandardItem(), QStandardItem()]
            for cell in grp:
                cell.setEditable(False)
            for seq, flow in rows:
                c0 = QStandardItem(("★ " if flow.flagged else "") + (flow.path or "/"))
                c1 = QStandardItem(flow.method)
                c2 = QStandardItem(self._status_text(flow))
                c3 = QStandardItem(str(seq))
                c1.setForeground(QColor(METHOD_COLORS.get(flow.method, ("#cdd6f4", ""))[0]))
                c2.setForeground(QColor(status_color(flow.status_code)))
                for cell in (c0, c1, c2, c3):
                    cell.setEditable(False)
                    cell.setData(flow, Qt.ItemDataRole.UserRole)
                    if flow.tag_color:
                        cell.setBackground(QColor(flow.tag_color))
                    if flow.note:
                        cell.setToolTip(flow.note)
                g0.appendRow([c0, c1, c2, c3])
            self._tree_model.appendRow(grp)

        self._tree.expandAll()
        self._tree.setColumnWidth(0, 320)
        self._tree.setColumnWidth(1, 72)
        self._tree.setColumnWidth(2, 64)

    def _on_tree_selection(self, *_) -> None:
        idx = self._tree.currentIndex()
        flow = idx.data(Qt.ItemDataRole.UserRole) if idx.isValid() else None
        self.flow_selected.emit(flow)

    def _on_tree_double_clicked(self, idx) -> None:
        flow = idx.data(Qt.ItemDataRole.UserRole)
        if flow is not None:
            self.inspect_requested.emit(flow)

    def _on_tree_context_menu(self, pos) -> None:
        idx = self._tree.indexAt(pos)
        flow = idx.data(Qt.ItemDataRole.UserRole) if idx.isValid() else None
        if flow is not None:
            self._show_flow_menu(flow, self._tree.viewport().mapToGlobal(pos))

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

    def _toggle_flag(self, flow: FlowModel) -> None:
        flow.flagged = not flow.flagged
        self._model.mark_flow_changed(flow)
        self._refresh_grouped()

    def _set_tag_color(self, flow: FlowModel, hex_color: str) -> None:
        flow.tag_color = hex_color
        self._model.mark_flow_changed(flow)
        self._refresh_grouped()

    def _edit_note(self, flow: FlowModel) -> None:
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, tr("ctx.note.title"), tr("ctx.note.prompt"), text=flow.note
        )
        if ok:
            flow.note = text.strip()
            self._model.mark_flow_changed(flow)
            self._refresh_grouped()

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

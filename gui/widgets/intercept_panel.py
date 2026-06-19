"""
Intercept panel — the breakpoint edit surface.

When a flow hits a breakpoint it is paused in the proxy and announced to this
panel. The user picks a held flow from the list, edits its method/URL/headers/
body (request side) or status/headers/body (response side), then releases it —
the edits are handed back to the proxy and applied to the live flow before it is
forwarded. ``Abort`` drops the connection; ``Release all`` forwards everything
unchanged.

The panel only emits intent (release / release-unchanged / abort / abort-all);
the main window owns the cross-thread handoff to the proxy.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from proxy.models import FlowModel
from gui.i18n import i18n, tr
from gui.widgets.kv_table import KeyValueTable

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class _Held:
    """A held flow plus the GUI item representing it."""

    def __init__(self, direction: str, flow: FlowModel, item: QListWidgetItem) -> None:
        self.direction = direction
        self.flow = flow
        self.item = item


class InterceptPanel(QWidget):
    """List of paused flows + an editor to modify and release them."""

    # (flow_id, edits | None) — edits None means "release unchanged".
    release_requested = pyqtSignal(str, object)
    abort_requested = pyqtSignal(str)            # flow_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._held: Dict[str, _Held] = {}
        self._current_id: Optional[str] = None
        self._build_ui()
        i18n.language_changed.connect(self.retranslate)
        self.retranslate()
        self._update_enablement()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Held-flow list.
        self._list = QListWidget()
        self._list.setObjectName("intercept_list")
        self._list.setMaximumHeight(120)
        self._list.currentItemChanged.connect(self._on_select)
        root.addWidget(self._list)

        # Empty-state hint vs editor.
        self._stack = QStackedWidget()

        self._empty = QLabel()
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color: #6c7086; font-size: 13px;")

        self._editor = self._build_editor()

        self._stack.addWidget(self._empty)
        self._stack.addWidget(self._editor)
        root.addWidget(self._stack, 1)

        # Action buttons.
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._btn_release = QPushButton()
        self._btn_release.setObjectName("btn_start")
        self._btn_release.clicked.connect(self._on_release)
        self._btn_release_unchanged = QPushButton()
        self._btn_release_unchanged.clicked.connect(self._on_release_unchanged)
        self._btn_abort = QPushButton()
        self._btn_abort.clicked.connect(self._on_abort)
        self._btn_release_all = QPushButton()
        self._btn_release_all.clicked.connect(self._on_release_all)
        actions.addWidget(self._btn_release)
        actions.addWidget(self._btn_release_unchanged)
        actions.addWidget(self._btn_abort)
        actions.addStretch()
        actions.addWidget(self._btn_release_all)
        root.addLayout(actions)

    def _build_editor(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # First line: method + URL (request) OR status (response).
        line = QHBoxLayout()
        line.setSpacing(6)
        self._method_combo = QComboBox()
        self._method_combo.addItems(_METHODS)
        self._method_combo.setFixedWidth(110)
        self._url_input = QLineEdit()
        self._status_input = QLineEdit()
        self._status_input.setFixedWidth(110)
        self._status_label = QLabel()
        line.addWidget(self._method_combo)
        line.addWidget(self._url_input, 1)
        line.addWidget(self._status_label)
        line.addWidget(self._status_input)
        layout.addLayout(line)

        # Headers + body tabs.
        self._tabs = QTabWidget()
        self._headers_table = KeyValueTable()
        self._body_edit = QPlainTextEdit()
        self._body_edit.setPlaceholderText("")
        self._tabs.addTab(self._headers_table, "")
        self._tabs.addTab(self._body_edit, "")
        layout.addWidget(self._tabs, 1)
        return wrap

    # ------------------------------------------------------------------ #
    # i18n
    # ------------------------------------------------------------------ #

    def retranslate(self) -> None:
        self._empty.setText(tr("intercept.empty"))
        self._btn_release.setText(tr("intercept.release"))
        self._btn_release_unchanged.setText(tr("intercept.release_unchanged"))
        self._btn_abort.setText(tr("intercept.abort"))
        self._btn_release_all.setText(tr("intercept.release_all"))
        self._status_label.setText(tr("intercept.status"))
        self._tabs.setTabText(0, tr("intercept.tab.headers"))
        self._tabs.setTabText(1, tr("intercept.tab.body"))
        self._headers_table.retranslate(tr("intercept.tab.headers"), tr("intercept.value"))
        # Refresh held-row labels (direction badge is translated).
        for held in self._held.values():
            held.item.setText(self._row_label(held.direction, held.flow))

    # ------------------------------------------------------------------ #
    # Public — held flows
    # ------------------------------------------------------------------ #

    def add_held(self, direction: str, flow_id: str, flow: FlowModel) -> None:
        if flow_id in self._held:
            return
        item = QListWidgetItem(self._row_label(direction, flow))
        item.setData(Qt.ItemDataRole.UserRole, flow_id)
        self._list.addItem(item)
        self._held[flow_id] = _Held(direction, flow, item)
        # Auto-select the first/only held flow so the user can act immediately.
        if self._list.count() == 1:
            self._list.setCurrentItem(item)
        self._update_enablement()

    def remove_held(self, flow_id: str) -> None:
        """Drop a held flow that the proxy already resolved (e.g. timeout)."""
        held = self._held.pop(flow_id, None)
        if held is None:
            return
        row = self._list.row(held.item)
        self._list.takeItem(row)
        if self._current_id == flow_id:
            self._current_id = None
        self._update_enablement()

    def has_held(self) -> bool:
        return bool(self._held)

    def held_ids(self) -> List[str]:
        return list(self._held.keys())

    def _row_label(self, direction: str, flow: FlowModel) -> str:
        badge = tr("intercept.held.request") if direction == "request" else tr("intercept.held.response")
        return f"{badge}  {flow.method}  {flow.url}"

    # ------------------------------------------------------------------ #
    # Selection / editor population
    # ------------------------------------------------------------------ #

    def _on_select(self, current: Optional[QListWidgetItem], _prev=None) -> None:
        if current is None:
            self._current_id = None
            self._stack.setCurrentWidget(self._empty)
            self._update_enablement()
            return
        flow_id = current.data(Qt.ItemDataRole.UserRole)
        held = self._held.get(flow_id)
        if held is None:
            return
        self._current_id = flow_id
        self._populate(held)
        self._stack.setCurrentWidget(self._editor)
        self._update_enablement()

    def _populate(self, held: _Held) -> None:
        flow = held.flow
        is_request = held.direction == "request"
        # Toggle which first-line controls apply.
        self._method_combo.setVisible(is_request)
        self._url_input.setVisible(is_request)
        self._status_label.setVisible(not is_request)
        self._status_input.setVisible(not is_request)

        if is_request:
            idx = self._method_combo.findText(flow.method)
            if idx < 0:
                self._method_combo.addItem(flow.method)
                idx = self._method_combo.findText(flow.method)
            self._method_combo.setCurrentIndex(idx)
            self._url_input.setText(flow.url)
            headers = flow.request_headers
            body = flow.request_body
        else:
            self._status_input.setText(str(flow.status_code or ""))
            headers = flow.response_headers
            body = flow.response_body

        self._headers_table.set_rows([(True, k, v) for k, v in headers.items()])
        self._body_edit.setPlainText(self._decode(body))

    @staticmethod
    def _decode(body: bytes) -> str:
        if not body:
            return ""
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return body.decode("latin-1", errors="replace")

    # ------------------------------------------------------------------ #
    # Collect edits
    # ------------------------------------------------------------------ #

    def _collect_edits(self, held: _Held) -> dict:
        headers: List[Tuple[str, str]] = [
            (k, v) for enabled, k, v in self._headers_table.rows() if enabled and k
        ]
        body = self._body_edit.toPlainText().encode("utf-8")
        if held.direction == "request":
            return {
                "method": self._method_combo.currentText(),
                "url": self._url_input.text().strip(),
                "headers": headers,
                "body": body,
            }
        status_text = self._status_input.text().strip()
        try:
            status_code = int(status_text) if status_text else None
        except ValueError:
            status_code = None
        return {
            "status_code": status_code,
            "headers": headers,
            "body": body,
        }

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    def _on_release(self) -> None:
        if self._current_id is None:
            return
        held = self._held.get(self._current_id)
        if held is None:
            return
        flow_id = self._current_id
        edits = self._collect_edits(held)
        self.remove_held(flow_id)
        self.release_requested.emit(flow_id, edits)

    def _on_release_unchanged(self) -> None:
        if self._current_id is None:
            return
        flow_id = self._current_id
        self.remove_held(flow_id)
        self.release_requested.emit(flow_id, None)

    def _on_abort(self) -> None:
        if self._current_id is None:
            return
        flow_id = self._current_id
        self.remove_held(flow_id)
        self.abort_requested.emit(flow_id)

    def _on_release_all(self) -> None:
        for flow_id in self.held_ids():
            self.remove_held(flow_id)
            self.release_requested.emit(flow_id, None)

    def _update_enablement(self) -> None:
        has_sel = self._current_id is not None
        has_any = bool(self._held)
        self._btn_release.setEnabled(has_sel)
        self._btn_release_unchanged.setEnabled(has_sel)
        self._btn_abort.setEnabled(has_sel)
        self._btn_release_all.setEnabled(has_any)
        if not has_any:
            self._stack.setCurrentWidget(self._empty)

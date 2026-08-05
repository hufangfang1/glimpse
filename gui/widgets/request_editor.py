"""
RequestEditorPanel — Postman-style request composer embedded in the main window.

Layout (right side of main window):

    ┌──────────────────────────────────────────────┬─┬──────────┐
    │ [METHOD ▾] [ URL ................ ] [Send] │▸│ Saved    │
    │ [Name] [Save] [Save As]                      │ │ requests │
    │ ┌ Params │ Headers │ Cookies │ Body ┐       │ │ (drawer) │
    │ ├────────────────────────────────────┤       │ │          │
    │ │  Response: status · headers · body │       │ │          │
    └──────────────────────────────────────────────┴─┴──────────┘
    Collections drawer on the right edge; closed by default (icon rail only).

Selecting a captured flow loads it for editing; saving only affects the collection
store, not captured traffic. Sending runs httpx on a worker thread.
"""
from __future__ import annotations

import json
import threading
import uuid
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from PyQt6.QtCore import QEvent, QObject, Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QPalette, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from proxy.collections import (
    CollectionStore,
    RequestGroup,
    SavedRequest,
    SavedResponseSnapshot,
)
from proxy.signing import AuthStore, apply_signer
from proxy.cookies import (
    CapturedCookieJar,
    ChromeCookieRead,
    read_chrome_cookies_detail,
    read_safari_cookies,
    cookie_value_for_wire,
    normalize_cookie_value,
)
from proxy.http_client import make_client
from proxy.models import FlowModel
from gui.i18n import i18n, tr
from gui.icons import file_doc
from gui.themes import CONTROL_HEIGHT, METHOD_COLORS, status_color
from gui.widgets.detail_panel import BodyPanel, HeadersView, JsonHighlighter, WebSocketTab
from gui.widgets.kv_table import KeyValueTable

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


_EDITOR_CONTROL_HEIGHT = CONTROL_HEIGHT


def _form_value_to_json(value: str):
    """Preserve JSON-looking form values while keeping ordinary text as text."""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _form_rows_to_json(rows) -> dict:
    """Convert enabled form rows to an object, retaining duplicate keys as arrays."""
    result = {}
    duplicate_keys = set()
    for _enabled, key, value in rows:
        converted = _form_value_to_json(value)
        if key not in result:
            result[key] = converted
        elif key in duplicate_keys:
            result[key].append(converted)
        else:
            result[key] = [result[key], converted]
            duplicate_keys.add(key)
    return result


class _ComboPopupNoScrollFilter(QObject):
    """Block wheel/trackpad scroll inside combo popups sized to fit all rows."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel:
            return True
        return super().eventFilter(obj, event)

_COLLECTIONS_DRAWER_WIDTH = 240      # default width when the drawer is first opened
_COLLECTIONS_DRAWER_MIN_WIDTH = 200  # user can't drag the drawer narrower than this
_COLLECTIONS_DRAWER_MAX_WIDTH = 640  # ...nor wider
_COLLECTIONS_RAIL_WIDTH = 32

# Sent only when the user has not set them — mimics a normal browser navigation.
_BROWSER_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class _MethodDelegate(QStyledItemDelegate):
    """Paint each HTTP verb in the method combo popup with its badge colour."""

    def paint(self, painter, option, index) -> None:
        method = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        fg = QColor(METHOD_COLORS.get(method, ("#cdd6f4", ""))[0])
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.palette.setColor(QPalette.ColorRole.Text, fg)
        if opt.state & QStyle.StateFlag.State_Selected:
            opt.palette.setColor(QPalette.ColorRole.Text, QColor("#cdd6f4"))
        widget = option.widget
        if widget is not None:
            widget.style().drawControl(
                QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)


class _ChromeCookieWorker(threading.Thread):
    """Reads Chrome cookies off the GUI thread (keychain prompt can block for a while)."""

    def __init__(self, host: str, on_done) -> None:
        super().__init__(daemon=True)
        self._host = host
        self._on_done = on_done

    def run(self) -> None:
        self._on_done(read_chrome_cookies_detail(self._host))


class _SendWorker(threading.Thread):
    """Runs one httpx request off the GUI thread and reports back via callback.

    The callback is invoked from this worker thread, so the dialog wraps it in a
    Qt signal emission to hop safely back onto the GUI thread.
    """

    def __init__(self, method, url, headers, cookies, body, on_done) -> None:
        super().__init__(daemon=True)
        self._method = method
        self._url = url
        self._headers = headers
        self._cookies = cookies
        self._body = body
        self._on_done = on_done

    def run(self) -> None:
        try:
            with make_client(self._url) as client:
                req = client.build_request(
                    method=self._method,
                    url=self._url,
                    headers=self._headers,
                    cookies=self._cookies or None,
                    content=self._body or None,
                )
                resp = client.send(req)
            parsed = urlparse(str(resp.request.url))
            flow = FlowModel(
                id=f"edit_{uuid.uuid4().hex[:8]}",
                flow_type="http",
                method=self._method,
                scheme=parsed.scheme or "http",
                host=parsed.hostname or "",
                path=parsed.path or "/",
                query=parsed.query,
                status_code=resp.status_code,
                status_message=resp.reason_phrase,
                request_headers=dict(resp.request.headers),
                request_body=self._body,
                response_headers=dict(resp.headers),
                response_body=resp.content,
                duration=resp.elapsed.total_seconds(),
            )
            self._on_done(flow, None)
        except Exception as exc:   # network error, bad URL, timeout, …
            self._on_done(None, str(exc))


class BodyEditor(QPlainTextEdit):
    """Editable monospace body field with optional JSON highlighting."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFont(QFont("Menlo, SF Mono, monospace", 11))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._highlighter: Optional[JsonHighlighter] = None
        self._highlighter = JsonHighlighter(self.document())

    def format_json(self) -> bool:
        """Pretty-print the current text if it is valid JSON. Returns success."""
        text = self.toPlainText().strip()
        if not text:
            return False
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return False
        self.setPlainText(json.dumps(parsed, indent=2, ensure_ascii=False))
        return True


class RequestBodyEditor(QWidget):
    """Body editor with a Form / JSON mode switch.

    Form mode edits ``application/x-www-form-urlencoded`` pairs in a key/value
    grid; JSON mode is a monospace text editor (it also doubles as a raw text
    editor for non-JSON bodies). Both round-trip through a single ``body``
    string plus the request's Content-Type header, so nothing extra needs to be
    persisted. Switching from Form to JSON replaces the JSON editor with a
    pretty-printed conversion of the enabled form rows; switching back keeps
    the form rows available for further editing.
    """

    MODE_FORM = "form"
    MODE_JSON = "json"

    _MODE_QSS = """
    QPushButton#body_mode_btn {
        padding: 3px 16px; border: 1px solid #313244;
        background: #181825; color: #a6adc8;
    }
    QPushButton#body_mode_btn:checked {
        background: #313244; color: #cdd6f4; border-color: #585b70;
    }
    """

    mode_changed = pyqtSignal(str)   # user switched mode (not on programmatic load)
    format_failed = pyqtSignal()     # Format JSON pressed but body isn't JSON
    changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mode = self.MODE_JSON

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        bar = QHBoxLayout()
        self._btn_form = QPushButton()
        self._btn_json = QPushButton()
        for b in (self._btn_form, self._btn_json):
            b.setObjectName("body_mode_btn")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(_EDITOR_CONTROL_HEIGHT)
        self._btn_form.clicked.connect(lambda: self.set_mode(self.MODE_FORM))
        self._btn_json.clicked.connect(lambda: self.set_mode(self.MODE_JSON))
        bar.addWidget(self._btn_form)
        bar.addWidget(self._btn_json)
        bar.addStretch()
        self._btn_format = QPushButton()
        self._btn_format.setFixedWidth(120)
        self._btn_format.clicked.connect(self._on_format_clicked)
        bar.addWidget(self._btn_format)
        layout.addLayout(bar)

        self._stack = QStackedWidget()
        self._json_editor = BodyEditor()
        self._form_table = KeyValueTable()
        self._stack.addWidget(self._json_editor)   # index 0 — JSON / raw
        self._stack.addWidget(self._form_table)    # index 1 — Form grid
        layout.addWidget(self._stack, 1)

        self._json_editor.textChanged.connect(self.changed)
        self._form_table.changed.connect(self.changed)

        self.setStyleSheet(self._MODE_QSS)
        self._apply_mode_ui()
        self.retranslate()

    # ----------------------------- public API ----------------------------- #

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str, *, silent: bool = False) -> None:
        if mode not in (self.MODE_FORM, self.MODE_JSON):
            return
        changed = mode != self._mode
        if changed and not silent and self._mode == self.MODE_FORM and mode == self.MODE_JSON:
            data = _form_rows_to_json(self._form_table.rows(enabled_only=True))
            self._json_editor.setPlainText(
                json.dumps(data, indent=2, ensure_ascii=False)
            )
        self._mode = mode
        self._apply_mode_ui()
        if changed and not silent:
            self.mode_changed.emit(mode)
            self.changed.emit()

    def set_body(self, body: str, content_type: str = "") -> None:
        """Load a body string, picking the mode from the Content-Type header."""
        if "x-www-form-urlencoded" in (content_type or "").lower():
            pairs = parse_qsl(body, keep_blank_values=True) if body else []
            self._form_table.set_rows([(True, k, v) for k, v in pairs])
            self._json_editor.setPlainText("")
            self.set_mode(self.MODE_FORM, silent=True)
        else:
            self._json_editor.setPlainText(body)
            self._form_table.set_rows([])
            self.set_mode(self.MODE_JSON, silent=True)

    def body_text(self) -> str:
        """Serialize the active mode back to a wire-ready body string."""
        if self._mode == self.MODE_FORM:
            pairs = [(k, v) for _en, k, v in self._form_table.rows(enabled_only=True)]
            return urlencode(pairs)
        return self._json_editor.toPlainText()

    def clear(self) -> None:
        self._json_editor.clear()
        self._form_table.set_rows([])
        self.set_mode(self.MODE_JSON, silent=True)

    def format_json(self) -> bool:
        return self._json_editor.format_json()

    def retranslate(self) -> None:
        self._btn_form.setText(tr("editor.body.mode_form"))
        self._btn_json.setText(tr("editor.body.mode_json"))
        self._btn_format.setText(tr("editor.format_json"))

    # ------------------------------ internals ----------------------------- #

    def _apply_mode_ui(self) -> None:
        is_form = self._mode == self.MODE_FORM
        self._btn_form.setChecked(is_form)
        self._btn_json.setChecked(not is_form)
        self._stack.setCurrentWidget(self._form_table if is_form else self._json_editor)
        self._btn_format.setVisible(not is_form)

    def _on_format_clicked(self) -> None:
        if not self.format_json():
            self.format_failed.emit()


class GroupPickerDialog(QDialog):
    """Small dark-styled 'choose a group' dialog used by Save / Save As.

    Replaces ``QInputDialog.getItem`` whose embedded combo popup ignores our
    stylesheet on macOS. A list is also clearer when there are many groups.
    """

    def __init__(
        self,
        title: str,
        prompt: str,
        names: list[str],
        parent=None,
        *,
        new_group_label: str = "",
        on_new_group: Optional[Callable[[], Optional[str]]] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("group_picker_dialog")
        self.setWindowTitle(title)
        self.setMinimumWidth(340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        label = QLabel(prompt)
        self._list = QListWidget()
        self._list.setObjectName("group_picker_list")
        self._list.addItems(names)
        if names:
            self._list.setCurrentRow(0)
        row_h = self._list.sizeHintForRow(0) if names else 28
        self._list.setMinimumHeight(min(220, max(120, row_h * max(len(names), 1) + 12)))
        self._list.itemDoubleClicked.connect(lambda _i: self.accept())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(label)
        layout.addWidget(self._list, 1)

        if on_new_group is not None:
            new_row = QHBoxLayout()
            btn_new = QPushButton(new_group_label)
            btn_new.clicked.connect(lambda: self._add_new_group(on_new_group))
            new_row.addWidget(btn_new)
            new_row.addStretch()
            layout.addLayout(new_row)

        layout.addWidget(buttons)

    def _add_new_group(self, on_new_group: Callable[[], Optional[str]]) -> None:
        name = on_new_group()
        if not name:
            return
        for i in range(self._list.count()):
            if self._list.item(i).text() == name:
                self._list.setCurrentRow(i)
                return
        self._list.addItem(name)
        self._list.setCurrentRow(self._list.count() - 1)

    def selected(self) -> Optional[str]:
        item = self._list.currentItem()
        return item.text() if item is not None else None


class TextPromptDialog(QDialog):
    """Dark-styled single-line prompt (replaces QInputDialog on macOS)."""

    def __init__(self, title: str, label: str, initial: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("text_prompt_dialog")
        self.setWindowTitle(title)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        layout.addWidget(QLabel(label))
        self._edit = QLineEdit(initial)
        self._edit.selectAll()
        self._edit.returnPressed.connect(self.accept)
        layout.addWidget(self._edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self._edit.text().strip()


class _CollectionsTree(QTreeWidget):
    """Collections tree — drag request rows onto a group to move them."""

    request_dropped = pyqtSignal(str, str)  # request_id, target_group_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._drag_request_id: Optional[str] = None

    def startDrag(self, supportedActions) -> None:
        items = self.selectedItems()
        if len(items) != 1:
            return
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "request":
            return
        self._drag_request_id = data[1]
        super().startDrag(supportedActions)

    def dragEnterEvent(self, event) -> None:
        if event.source() is self and self._drag_request_id:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.source() is not self or not self._drag_request_id:
            event.ignore()
            return
        if self._drop_group_id(self.itemAt(event.position().toPoint())):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if event.source() is not self or not self._drag_request_id:
            event.ignore()
            return
        target_gid = self._drop_group_id(self.itemAt(event.position().toPoint()))
        if target_gid:
            self.request_dropped.emit(self._drag_request_id, target_gid)
            event.acceptProposedAction()
        else:
            event.ignore()
        self._drag_request_id = None

    @staticmethod
    def _drop_group_id(item: Optional[QTreeWidgetItem]) -> Optional[str]:
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return None
        if data[0] == "group":
            return data[1]
        if data[0] == "request":
            parent = item.parent()
            if parent is not None:
                pdata = parent.data(0, Qt.ItemDataRole.UserRole)
                if pdata and pdata[0] == "group":
                    return pdata[1]
        return None


class RequestEditorPanel(QWidget):
    """Embedded Postman-style request composer with saved collections."""

    # Worker → GUI thread bridge. Carries (FlowModel|None, error_str|None).
    _response_ready = pyqtSignal(object, object)
    _chrome_cookies_ready = pyqtSignal(object)

    def __init__(self, store: CollectionStore, cookie_jar: CapturedCookieJar,
                 on_store_changed=None, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._auth_store = AuthStore.load()
        self._cookie_jar = cookie_jar
        self._on_store_changed = on_store_changed
        self._current_request_id: Optional[str] = None
        self._current_group_id: Optional[str] = None
        self._last_save_group_id: Optional[str] = None
        self._suspend_sync = False
        self._send_disabled = False
        self._saved_status_text = ""
        self._collections_drawer_open = False
        # Width the drawer reopens at — updated whenever the user resizes it.
        self._collections_drawer_width = _COLLECTIONS_DRAWER_WIDTH
        # Remembered request/response divider sizes per orientation (① flippable split).
        self._resp_sizes_v = [360, 320]   # stacked (request top, response bottom)
        self._resp_sizes_h: Optional[list] = None  # side-by-side (lazily set on first flip)
        # Response currently shown in the pane (capture, send, or persisted reload).
        self._last_response_flow: Optional[FlowModel] = None

        self._build_ui()
        self._response_ready.connect(self._on_response_ready)
        self._chrome_cookies_ready.connect(self._on_chrome_cookies_ready)
        self._chrome_sync_busy = False
        i18n.language_changed.connect(self.retranslate)
        self.retranslate()
        self._reload_signer_combo()
        self._reload_tree()
        self.clear()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Main: placeholder or editor + response ──
        self._placeholder = QLabel()
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #6c7086; font-size: 14px;")

        self._work = QWidget()
        work_layout = QVBoxLayout(self._work)
        work_layout.setContentsMargins(8, 8, 8, 8)
        work_layout.setSpacing(8)
        work_layout.addLayout(self._build_url_bar())
        work_layout.addLayout(self._build_save_bar())

        self._editor_response = QSplitter(Qt.Orientation.Vertical)
        self._editor_response.addWidget(self._build_request_tabs())
        self._editor_response.addWidget(self._build_response_area())
        self._editor_response.setSizes(self._resp_sizes_v)
        work_layout.addWidget(self._editor_response, 1)

        self._work_stack = QStackedWidget()
        self._work_stack.addWidget(self._placeholder)
        self._work_stack.addWidget(self._work)

        # ── Right edge: collections drawer + icon rail ──
        self._tree = _CollectionsTree()
        self._tree.setObjectName("editor_collections")
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(180)
        self._tree.setIndentation(18)
        self._tree.setIconSize(QSize(22, 22))
        self._tree.setRootIsDecorated(False)
        self._tree.setAnimated(True)
        self._tree.request_dropped.connect(self._on_request_dropped)
        self._tree.itemClicked.connect(self._on_tree_clicked)
        self._tree.itemExpanded.connect(self._on_group_expand_changed)
        self._tree.itemCollapsed.connect(self._on_group_expand_changed)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_menu)

        self._collections_drawer = QWidget()
        self._collections_drawer.setObjectName("editor_collections_drawer")
        drawer_layout = QVBoxLayout(self._collections_drawer)
        drawer_layout.setContentsMargins(8, 8, 4, 8)
        drawer_layout.setSpacing(6)

        drawer_header = QHBoxLayout()
        drawer_header.setSpacing(6)
        self._collections_title = QLabel()
        self._collections_title.setObjectName("editor_collections_title")
        self._btn_new_group = QToolButton()
        self._btn_new_group.setObjectName("editor_collections_add")
        self._btn_new_group.setFixedSize(28, 28)
        self._btn_new_group.clicked.connect(self._new_group)
        drawer_header.addWidget(self._collections_title, 1)
        drawer_header.addWidget(self._btn_new_group)
        drawer_layout.addLayout(drawer_header)
        drawer_layout.addWidget(self._tree, 1)

        self._collections_rail = QWidget()
        self._collections_rail.setObjectName("editor_collections_rail")
        self._collections_rail.setFixedWidth(_COLLECTIONS_RAIL_WIDTH)
        rail_layout = QVBoxLayout(self._collections_rail)
        rail_layout.setContentsMargins(4, 8, 4, 8)
        rail_layout.setSpacing(8)

        self._btn_collections_toggle = QToolButton()
        self._btn_collections_toggle.setObjectName("editor_collections_toggle")
        self._btn_collections_toggle.setFixedSize(24, 24)
        self._btn_collections_toggle.clicked.connect(self._toggle_collections_drawer)

        self._btn_rail_new_group = QToolButton()
        self._btn_rail_new_group.setObjectName("editor_collections_add")
        self._btn_rail_new_group.setFixedSize(24, 24)
        self._btn_rail_new_group.clicked.connect(self._new_group)

        rail_layout.addWidget(self._btn_collections_toggle)
        rail_layout.addWidget(self._btn_rail_new_group)
        rail_layout.addStretch()

        # ③ Collections as a slide-over: the drawer floats over the work area on
        # demand instead of occupying a permanent column. Only the rail stays docked.
        self._collections_drawer.setParent(self)
        self._collections_drawer.hide()

        outer.addWidget(self._work_stack, 1)
        outer.addWidget(self._collections_rail)

        QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(self._toggle_collections_drawer)

        self._set_collections_drawer_open(False)

    def _build_url_bar(self):
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._method_combo = QComboBox()
        self._method_combo.setObjectName("method_combo")
        self._method_combo.addItems(_METHODS)
        self._method_combo.setFixedWidth(104)
        self._method_combo.setFixedHeight(_EDITOR_CONTROL_HEIGHT)
        # QListView forces a Qt popup on macOS; native menus ignore our dark QSS.
        popup = QListView(self._method_combo)
        popup.setSpacing(2)
        popup.setUniformItemSizes(True)
        popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        popup.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        popup.setFrameShape(QListView.Shape.NoFrame)
        self._method_combo.setView(popup)
        self._method_combo.setMaxVisibleItems(len(_METHODS))
        self._method_combo.setItemDelegate(_MethodDelegate(self._method_combo))
        self._method_combo.currentIndexChanged.connect(
            lambda _i: self._apply_method_combo_style())
        self._apply_method_combo_style()
        self._method_popup_filter = _ComboPopupNoScrollFilter(popup)
        popup.installEventFilter(self._method_popup_filter)
        _orig_show_popup = self._method_combo.showPopup

        def _show_method_popup() -> None:
            self._fit_combo_popup(self._method_combo, min_width=112)
            _orig_show_popup()
            QTimer.singleShot(0, lambda: self._fit_combo_popup(self._method_combo, min_width=112))
            QTimer.singleShot(20, lambda: self._fit_combo_popup(self._method_combo, min_width=112))

        self._method_combo.showPopup = _show_method_popup  # type: ignore[method-assign]
        self._url_input = QLineEdit()
        self._url_input.setObjectName("editor_url_input")
        self._url_input.setFixedHeight(_EDITOR_CONTROL_HEIGHT)
        self._url_input.setPlaceholderText("https://api.example.com/path")
        self._url_input.editingFinished.connect(self._sync_params_from_url)
        self._url_input.returnPressed.connect(self._send)
        self._signer_combo = QComboBox()
        self._signer_combo.setObjectName("signer_combo")
        self._signer_combo.setFixedWidth(108)
        self._signer_combo.setFixedHeight(_EDITOR_CONTROL_HEIGHT)
        self._signer_combo.setIconSize(QSize(16, 16))
        signer_popup = QListView(self._signer_combo)
        signer_popup.setSpacing(2)
        signer_popup.setUniformItemSizes(True)
        signer_popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        signer_popup.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        signer_popup.setFrameShape(QListView.Shape.NoFrame)
        self._signer_combo.setView(signer_popup)
        self._signer_combo.setMaxVisibleItems(64)
        self._signer_combo.currentIndexChanged.connect(self._update_signer_combo_appearance)
        self._configure_signer_popup_view()
        self._update_signer_combo_appearance()
        self._signer_popup_filter = _ComboPopupNoScrollFilter(signer_popup)
        signer_popup.installEventFilter(self._signer_popup_filter)
        _orig_signer_popup = self._signer_combo.showPopup

        def _show_signer_popup() -> None:
            self._fit_combo_popup(self._signer_combo, min_popup_width=248)
            _orig_signer_popup()
            QTimer.singleShot(0, lambda: self._fit_combo_popup(self._signer_combo, min_popup_width=248))
            QTimer.singleShot(20, lambda: self._fit_combo_popup(self._signer_combo, min_popup_width=248))

        self._signer_combo.showPopup = _show_signer_popup  # type: ignore[method-assign]
        self._btn_send = QPushButton()
        self._btn_send.setObjectName("btn_start")
        self._btn_send.setFixedWidth(90)
        self._btn_send.setFixedHeight(_EDITOR_CONTROL_HEIGHT)
        self._btn_send.clicked.connect(self._send)
        bar.addWidget(self._method_combo)
        bar.addWidget(self._url_input, 1)
        bar.addWidget(self._signer_combo)
        bar.addWidget(self._btn_send)
        return bar

    def _build_save_bar(self):
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._name_label = QLabel()
        self._name_input = QLineEdit()
        self._name_input.setObjectName("editor_name_input")
        self._name_input.setFixedHeight(_EDITOR_CONTROL_HEIGHT)
        self._name_input.setMinimumWidth(160)
        self._btn_save = QPushButton()
        self._btn_save.setFixedHeight(_EDITOR_CONTROL_HEIGHT)
        self._btn_save.clicked.connect(self._save)
        self._btn_save_as = QPushButton()
        self._btn_save_as.setFixedHeight(_EDITOR_CONTROL_HEIGHT)
        self._btn_save_as.clicked.connect(self._save_as)
        # ① Flip the request/response split between stacked and side-by-side.
        self._btn_flip_layout = QPushButton()
        self._btn_flip_layout.setObjectName("editor_flip_layout")
        self._btn_flip_layout.setFixedSize(40, _EDITOR_CONTROL_HEIGHT)
        self._btn_flip_layout.clicked.connect(self._toggle_response_orientation)
        bar.addWidget(self._name_label)
        bar.addWidget(self._name_input, 1)
        bar.addWidget(self._btn_save)
        bar.addWidget(self._btn_save_as)
        bar.addWidget(self._btn_flip_layout)
        return bar

    def _build_request_tabs(self) -> QTabWidget:
        self._tabs = QTabWidget()
        self._params_table = KeyValueTable()
        self._params_table.changed.connect(self._sync_url_from_params)
        self._headers_table = KeyValueTable()
        self._cookies_table = KeyValueTable()

        # Cookies tab gets a "sync from…" button above the grid.
        cookies_wrap = QWidget()
        cw = QVBoxLayout(cookies_wrap)
        cw.setContentsMargins(0, 0, 0, 0)
        cw.setSpacing(4)
        cookie_bar = QHBoxLayout()
        # A plain QPushButton with an attached menu — picks up the dark button
        # theme cleanly. (QToolButton defaults to icon-only and draws its own
        # popup arrow, which collided with the text "▾" and looked broken.)
        self._btn_sync_cookie = QPushButton()
        self._btn_sync_cookie.setMinimumWidth(150)
        self._cookie_menu = QMenu(self._btn_sync_cookie)
        self._act_cookie_captured = self._cookie_menu.addAction(
            "", lambda: self._sync_cookies("captured"))
        self._act_cookie_chrome = self._cookie_menu.addAction(
            "", self._sync_cookies_chrome)
        self._act_cookie_safari = self._cookie_menu.addAction(
            "", lambda: self._sync_cookies("safari"))
        self._btn_sync_cookie.setMenu(self._cookie_menu)
        cookie_bar.addWidget(self._btn_sync_cookie)
        cookie_bar.addStretch()
        cw.addLayout(cookie_bar)
        cw.addWidget(self._cookies_table)

        # Body tab: Form / JSON mode switch (see RequestBodyEditor).
        self._body_area = RequestBodyEditor()
        self._body_area.mode_changed.connect(self._on_body_mode_changed)
        self._body_area.format_failed.connect(self._on_body_format_failed)

        self._tabs.addTab(self._params_table, "")
        self._tabs.addTab(self._headers_table, "")
        self._tabs.addTab(cookies_wrap, "")
        self._tabs.addTab(self._body_area, "")
        return self._tabs

    def _build_response_area(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._resp_status = QLabel()
        self._resp_status.setStyleSheet(
            "background:#181825; color:#a6adc8; font-size:12px; padding:6px 12px;"
            "border-bottom:1px solid #313244;"
        )
        self._resp_tabs = QTabWidget()
        self._resp_headers = HeadersView()
        self._resp_headers.enable_cors_highlight()
        self._resp_body = BodyPanel()
        self._ws_tab = WebSocketTab()
        self._resp_tabs.addTab(self._resp_body, "")
        self._resp_tabs.addTab(self._resp_headers, "")
        self._resp_tabs.addTab(self._ws_tab, "")
        self._ws_tab_index = self._resp_tabs.indexOf(self._ws_tab)
        self._resp_tabs.setTabVisible(self._ws_tab_index, False)

        layout.addWidget(self._resp_status)
        layout.addWidget(self._resp_tabs, 1)
        return wrap

    # ------------------------------------------------------------------ #
    # Panel state (embedded in main window)
    # ------------------------------------------------------------------ #

    def clear(self) -> None:
        """Return to the default blank compose view when no flow is selected."""
        self.new_draft()

    def _show_work_area(self) -> None:
        self._work_stack.setCurrentWidget(self._work)

    def new_draft(self) -> None:
        """Blank editor (toolbar「请求集」) — does not affect captured traffic."""
        self._current_request_id = None
        self._current_group_id = None
        self._set_signer_id("")
        self._send_disabled = False
        self._btn_send.setEnabled(True)
        self._show_work_area()
        self._method_combo.setCurrentText("GET")
        self._apply_method_combo_style()
        self._url_input.clear()
        self._name_input.clear()
        self._params_table.set_rows([])
        self._headers_table.set_rows([])
        self._cookies_table.set_rows([])
        self._body_area.clear()
        self._reset_response_pane()
        self._configure_response_tabs_for_flow(None)

    def load_inspect_flow(self, flow: Optional[FlowModel]) -> None:
        """Load a captured flow for editing; show its response (read-only inspect)."""
        if flow is None:
            self.clear()
            return
        self._send_disabled = flow.flow_type == "websocket"
        self._btn_send.setEnabled(not self._send_disabled)
        self._show_work_area()
        self._tree.clearSelection()
        self.load_flow(flow)
        self._display_captured_response(flow)
        self._configure_response_tabs_for_flow(flow)

    @staticmethod
    def _flow_has_storable_response(flow: Optional[FlowModel]) -> bool:
        if flow is None or flow.flow_type == "websocket":
            return False
        return (
            flow.status_code is not None
            or bool(flow.response_body)
            or bool(flow.response_headers)
        )

    def _reset_response_pane(self) -> None:
        self._last_response_flow = None
        self._resp_status.setText(tr("editor.no_response"))
        self._resp_status.setStyleSheet(
            "background:#181825; color:#a6adc8; font-size:12px; padding:6px 12px;"
            "border-bottom:1px solid #313244;"
        )
        self._resp_headers.set_headers({})
        self._resp_body.set_body("")

    def _display_captured_response(self, flow: FlowModel) -> None:
        """Fill the response pane from a captured flow (not from Send)."""
        sc = flow.status_code or 0
        self._resp_status.setText(
            tr("editor.response_status",
               code=sc, reason=flow.status_message or "",
               size=flow.format_size(), dur=flow.format_duration())
        )
        self._resp_status.setStyleSheet(
            f"background:#181825; color:{status_color(sc)}; font-size:12px; padding:6px 12px;"
            "border-bottom:1px solid #313244;"
        )
        self._resp_headers.set_headers(flow.response_headers or {})
        if flow.flow_type == "websocket":
            self._ws_tab.load(flow)
        elif flow.is_image():
            self._resp_body.set_body(
                tr("body.binary_image", ctype=flow.content_type or "?", size=flow.format_size()),
                is_json=False,
            )
        else:
            text, is_json = flow.get_response_body_display()
            self._resp_body.set_body(text, is_json=is_json)
        if self._flow_has_storable_response(flow):
            self._last_response_flow = flow

    def _configure_response_tabs_for_flow(self, flow: Optional[FlowModel]) -> None:
        if flow is not None and flow.flow_type == "websocket":
            self._resp_tabs.setTabVisible(self._ws_tab_index, True)
            self._resp_tabs.setCurrentWidget(self._ws_tab)
        else:
            self._resp_tabs.setTabVisible(self._ws_tab_index, False)
            if flow is not None and (flow.response_body or flow.status_code is not None):
                self._resp_tabs.setCurrentWidget(self._resp_body)
            else:
                self._resp_tabs.setCurrentIndex(0)

    # ------------------------------------------------------------------ #
    # Collections drawer
    # ------------------------------------------------------------------ #

    def _toggle_collections_drawer(self) -> None:
        self._set_collections_drawer_open(not self._collections_drawer_open)

    def _set_collections_drawer_open(self, open: bool) -> None:
        self._collections_drawer_open = open
        if open:
            self._reload_signer_combo(self._selected_signer_id())
            self._position_drawer()
            self._collections_drawer.show()
            self._collections_drawer.raise_()
        else:
            self._collections_drawer.hide()
        self._sync_collections_toggle_label()

    def _position_drawer(self) -> None:
        """Anchor the floating drawer to the right edge, just left of the rail."""
        width = max(
            _COLLECTIONS_DRAWER_MIN_WIDTH,
            min(self._collections_drawer_width, _COLLECTIONS_DRAWER_MAX_WIDTH),
        )
        x = self.width() - _COLLECTIONS_RAIL_WIDTH - width
        self._collections_drawer.setGeometry(x, 0, width, self.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._collections_drawer_open:
            self._position_drawer()

    def _sync_collections_toggle_label(self) -> None:
        if self._collections_drawer_open:
            self._btn_collections_toggle.setText("›")
            self._btn_collections_toggle.setToolTip(tr("editor.collections.hide"))
        else:
            self._btn_collections_toggle.setText("‹")
            self._btn_collections_toggle.setToolTip(tr("editor.collections.show"))

    def _toggle_response_orientation(self) -> None:
        sp = self._editor_response
        if sp.orientation() == Qt.Orientation.Vertical:
            self._resp_sizes_v = sp.sizes()
            sp.setOrientation(Qt.Orientation.Horizontal)
            if self._resp_sizes_h:
                sp.setSizes(self._resp_sizes_h)
            else:
                half = max(sp.width(), 400) // 2
                sp.setSizes([half, half])
        else:
            self._resp_sizes_h = sp.sizes()
            sp.setOrientation(Qt.Orientation.Vertical)
            sp.setSizes(self._resp_sizes_v)
        self._sync_flip_button()

    def _sync_flip_button(self) -> None:
        # The glyph shows the layout a click switches TO.
        if self._editor_response.orientation() == Qt.Orientation.Vertical:
            self._btn_flip_layout.setText("⇄")
            self._btn_flip_layout.setToolTip(tr("editor.layout.side_by_side"))
        else:
            self._btn_flip_layout.setText("⇅")
            self._btn_flip_layout.setToolTip(tr("editor.layout.stacked"))

    # ------------------------------------------------------------------ #
    # i18n
    # ------------------------------------------------------------------ #

    def retranslate(self, _lang: str = "") -> None:
        self._collections_title.setText(tr("editor.collections.title"))
        self._btn_new_group.setText("+")
        self._btn_new_group.setToolTip(tr("editor.new_group"))
        self._btn_rail_new_group.setText("+")
        self._btn_rail_new_group.setToolTip(tr("editor.new_group"))
        self._sync_collections_toggle_label()
        self._btn_send.setText(tr("editor.send"))
        self._signer_combo.setToolTip(tr("editor.signer.tooltip"))
        if hasattr(self, "_signer_combo"):
            self._reload_signer_combo(self._selected_signer_id())
        self._name_label.setText(tr("editor.name.label"))
        self._name_input.setPlaceholderText(tr("editor.name.placeholder"))
        self._name_input.setToolTip(tr("editor.name.tooltip"))
        self._btn_save.setText(tr("editor.save"))
        self._btn_save.setToolTip(tr("editor.save.tooltip"))
        self._btn_save_as.setText(tr("editor.save_as"))
        self._btn_save_as.setToolTip(tr("editor.save_as.tooltip"))
        self._sync_flip_button()
        self._btn_sync_cookie.setText(tr("editor.sync_cookie"))
        self._act_cookie_captured.setText(tr("editor.cookie.captured"))
        self._act_cookie_chrome.setText(tr("editor.cookie.chrome"))
        self._act_cookie_safari.setText(tr("editor.cookie.safari"))
        self._body_area.retranslate()
        self._tabs.setTabText(0, tr("editor.tab.params"))
        self._tabs.setTabText(1, tr("editor.tab.headers"))
        self._tabs.setTabText(2, tr("editor.tab.cookies"))
        self._tabs.setTabText(3, tr("editor.tab.body"))
        self._placeholder.setText(tr("detail.placeholder"))
        self._resp_tabs.setTabText(0, tr("section.body"))
        self._resp_tabs.setTabText(1, tr("section.headers"))
        self._resp_tabs.setTabText(self._ws_tab_index, tr("detail.tab.websocket"))
        self._ws_tab.retranslate()
        self._params_table.retranslate(tr("editor.kv.key"), tr("editor.kv.value"))
        self._headers_table.retranslate(tr("editor.kv.key"), tr("editor.kv.value"))
        self._cookies_table.retranslate(tr("editor.kv.key"), tr("editor.kv.value"))
        if not self._resp_status.text():
            self._resp_status.setText(tr("editor.no_response"))
        self._resp_headers.retranslate()
        self._resp_body.retranslate()

    # ------------------------------------------------------------------ #
    # Collections tree
    # ------------------------------------------------------------------ #

    def _configure_signer_popup_view(self) -> None:
        """One-time popup list styling (avoid re-applying on every open → flicker)."""
        view = self._signer_combo.view()
        if view is None:
            return
        view.setStyleSheet("""
            QListView {
                background-color: #1e1e2e;
                border: none;
                outline: none;
            }
            QListView::item {
                padding: 8px 14px;
                min-height: 28px;
            }
            QListView::item:selected,
            QListView::item:hover {
                background-color: #45475a;
                color: #cdd6f4;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                width: 0px;
                height: 0px;
                background: transparent;
                border: none;
            }
        """)
        frame = view.window()
        frame.setStyleSheet("""
            QFrame {
                background-color: #1e1e2e;
                border: 1px solid #45475a;
                border-radius: 8px;
            }
        """)

    def _update_signer_combo_appearance(self, _index: int = -1) -> None:
        """Update closed combo colours only — do not restyle the popup on open."""
        from gui.icons import ensure_tree_branch_icons

        active = bool(self._selected_signer_id())
        fg = "#f9e2af" if active else "#6c7086"
        border = "#f9e2af" if active else "#45475a"
        bg = "#2a2838" if active else "#252536"
        hover_border = "#f9e2af" if active else "#585b70"
        try:
            combo_arrow = ensure_tree_branch_icons().get("combo", "")
        except Exception:
            combo_arrow = ""
        arrow_rule = (
            f'QComboBox#signer_combo::down-arrow {{ image: url("{combo_arrow}"); '
            f"width: 12px; height: 12px; margin-right: 6px; }}"
            if combo_arrow
            else ""
        )
        self._signer_combo.setStyleSheet(f"""
            QComboBox#signer_combo {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 2px 26px 2px 8px;
                color: {fg};
                font-size: 12px;
                font-weight: 500;
                min-height: {_EDITOR_CONTROL_HEIGHT}px;
                max-height: {_EDITOR_CONTROL_HEIGHT}px;
            }}
            QComboBox#signer_combo:hover {{
                border-color: {hover_border};
            }}
            QComboBox#signer_combo:focus,
            QComboBox#signer_combo:on {{
                border-color: #89b4fa;
            }}
            QComboBox#signer_combo::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 22px;
                border: none;
                background: transparent;
            }}
            {arrow_rule}
        """)

    def _fit_combo_popup(
        self,
        combo: QComboBox,
        *,
        min_width: int = 0,
        min_popup_width: int = 0,
    ) -> None:
        """Expand combo popup to fit every row — no scrollbar, no wheel scroll."""
        view = combo.view()
        if view is None:
            return

        n = max(1, combo.count())
        combo.setMaxVisibleItems(n)

        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setAutoScroll(False)

        view.doItemsLayout()
        list_h = 0
        for i in range(n):
            list_h += max(view.sizeHintForRow(i), 1)
        if n > 1:
            list_h += view.spacing() * (n - 1)
        margins = view.contentsMargins()
        list_h += margins.top() + margins.bottom() + 12

        w = max(min_width, combo.width())
        if min_popup_width:
            fm = view.fontMetrics()
            text_w = max(fm.horizontalAdvance(combo.itemText(i)) for i in range(n))
            w = max(w, combo.width() + 80, text_w + 52, min_popup_width)

        view.setMinimumWidth(w)
        view.setMaximumWidth(max(w, 640))
        view.setMinimumHeight(list_h)
        view.setMaximumHeight(list_h)

        vbar = view.verticalScrollBar()
        if vbar is not None:
            vbar.setEnabled(False)
            vbar.hide()
        hbar = view.horizontalScrollBar()
        if hbar is not None:
            hbar.setEnabled(False)
            hbar.hide()

        popup = view.window()
        if popup is None or not popup.isVisible():
            return
        filt = None
        if combo is self._method_combo:
            filt = self._method_popup_filter
        elif combo is self._signer_combo:
            filt = self._signer_popup_filter
        if filt is not None:
            popup.installEventFilter(filt)
        frame = popup.frameWidth() * 2
        popup.setFixedSize(w + frame, list_h + frame)
        for bar in popup.findChildren(QScrollBar):
            bar.setEnabled(False)
            bar.hide()
        for area in popup.findChildren(QScrollArea):
            area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def _apply_method_combo_style(self) -> None:
        """Full method-selector QSS: badge colour, PNG chevron, dark popup list."""
        from gui.icons import ensure_tree_branch_icons

        method = self._method_combo.currentText()
        fg = METHOD_COLORS.get(method, ("#cdd6f4", ""))[0]
        try:
            combo_arrow = ensure_tree_branch_icons().get("combo", "")
        except Exception:
            combo_arrow = ""
        arrow_rule = (
            f'QComboBox#method_combo::down-arrow {{ image: url("{combo_arrow}"); '
            f"width: 12px; height: 12px; margin-right: 6px; }}"
            if combo_arrow
            else ""
        )
        self._method_combo.setStyleSheet(f"""
            QComboBox#method_combo {{
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 2px 28px 2px 10px;
                color: {fg};
                font-weight: 600;
                min-height: {_EDITOR_CONTROL_HEIGHT}px;
                max-height: {_EDITOR_CONTROL_HEIGHT}px;
            }}
            QComboBox#method_combo:hover {{
                border-color: #585b70;
            }}
            QComboBox#method_combo:focus,
            QComboBox#method_combo:on {{
                border-color: #89b4fa;
            }}
            QComboBox#method_combo::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 24px;
                border: none;
                background: transparent;
            }}
            {arrow_rule}
            QComboBox#method_combo QAbstractItemView {{
                background-color: #1e1e2e;
                border: none;
                padding: 4px;
                outline: none;
                selection-background-color: #45475a;
                selection-color: #cdd6f4;
            }}
            QComboBox#method_combo QAbstractItemView::item {{
                padding: 6px 12px;
                border-radius: 5px;
                min-height: 22px;
            }}
        """)
        view = self._method_combo.view()
        view.setStyleSheet("""
            QListView {
                background-color: #1e1e2e;
                border: none;
                outline: none;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                width: 0px;
                height: 0px;
                background: transparent;
                border: none;
            }
        """)
        frame = view.window()
        frame.setStyleSheet("""
            QFrame {
                background-color: #1e1e2e;
                border: 1px solid #45475a;
                border-radius: 8px;
            }
        """)

    @staticmethod
    def _path_from_url(url: str) -> str:
        """Path + query only (no scheme/host) for display names."""
        parsed = urlparse((url or "").strip())
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        return path[:120]

    @staticmethod
    def _request_tree_title(req: SavedRequest) -> str:
        """Label in the collections tree — uses saved name, else path from URL."""
        name = (req.name or "").strip()
        if name:
            return name
        if (req.url or "").strip():
            return RequestEditorPanel._path_from_url(req.url)
        return RequestEditorPanel._path_from_legacy_name(req.name)

    @staticmethod
    def _default_name_for_editor(url: str = "") -> str:
        """Initial value for the name field (path only, no host/method)."""
        if url.strip():
            return RequestEditorPanel._path_from_url(url)
        return "/"

    @staticmethod
    def _path_from_legacy_name(name: str) -> str:
        """Best-effort path for older saves that stored method/host in ``name``."""
        text = (name or "").strip() or "/"
        if text.startswith(("http://", "https://")):
            return RequestEditorPanel._path_from_url(text)
        upper = text.upper()
        for method in _METHODS:
            for sep in (" · ", " ", " - "):
                prefix = f"{method}{sep}"
                if upper.startswith(prefix):
                    text = text[len(prefix):].strip()
                    break
        if text.startswith(("http://", "https://")):
            return RequestEditorPanel._path_from_url(text)
        if "://" in text:
            return RequestEditorPanel._path_from_url(text)
        if "/" in text and not text.startswith("/"):
            slash = text.index("/")
            return text[slash:] or "/"
        return text if text.startswith("/") else f"/{text}"

    def _reload_tree(self) -> None:
        from PyQt6.QtGui import QColor
        from gui.icons import group_icon
        self._tree.clear()
        for group in self._store.groups():
            g_item = QTreeWidgetItem([group.name])
            g_item.setData(0, Qt.ItemDataRole.UserRole, ("group", group.id))
            g_item.setIcon(0, group_icon(expanded=True))
            f = g_item.font(0)
            f.setBold(True)
            g_item.setFont(0, f)
            g_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDropEnabled
            )
            for req in group.requests:
                r_item = QTreeWidgetItem([self._request_tree_title(req)])
                r_item.setData(0, Qt.ItemDataRole.UserRole, ("request", req.id))
                r_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsDragEnabled
                )
                color = METHOD_COLORS.get(req.method, ("#cdd6f4", ""))[0]
                r_item.setForeground(0, QColor(color))
                r_item.setIcon(0, file_doc(color))
                r_item.setToolTip(0, req.url)
                g_item.addChild(r_item)
            self._tree.addTopLevelItem(g_item)
            g_item.setExpanded(True)

    def _on_request_dropped(self, request_id: str, target_group_id: str) -> None:
        if not self._store.move_request(request_id, target_group_id):
            return
        if self._current_request_id == request_id:
            self._current_group_id = target_group_id
        self._persist()
        self._reload_tree()

    def _on_group_expand_changed(self, item: QTreeWidgetItem) -> None:
        """Swap the group's arrow glyph to match its expanded state."""
        from gui.icons import group_icon
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "group":
            item.setIcon(0, group_icon(expanded=item.isExpanded()))

    def _on_tree_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if data[0] == "group":
            # Click anywhere on the group row toggles expand/collapse, not just
            # the disclosure arrow. (itemExpanded/Collapsed updates the icon.)
            item.setExpanded(not item.isExpanded())
            return
        if data[0] == "request":
            found = self._store.find_request(data[1])
            if found:
                self.load_request(found[1])

    def _on_tree_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        menu = QMenu(self)
        if item is None:
            menu.addAction(tr("editor.new_group"), self._new_group)
        else:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] == "group":
                menu.addAction(tr("editor.rename_group"),
                               lambda: self._rename_group(data[1], item.text(0)))
                menu.addAction(tr("editor.delete_group"),
                               lambda: self._delete_group(data[1]))
            elif data and data[0] == "request":
                menu.addAction(tr("editor.delete_request"),
                               lambda: self._delete_request(data[1]))
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _new_group(self) -> None:
        dlg = TextPromptDialog(tr("editor.new_group"), tr("editor.group_name"), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = dlg.text()
        if name:
            self._store.add_group(name)
            self._persist()
            self._reload_tree()

    def _rename_group(self, group_id: str, current: str) -> None:
        dlg = TextPromptDialog(
            tr("editor.rename_group"), tr("editor.group_name"), initial=current, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name = dlg.text()
        if name:
            self._store.rename_group(group_id, name)
            self._persist()
            self._reload_tree()

    def _delete_group(self, group_id: str) -> None:
        if QMessageBox.question(self, tr("editor.delete_group"),
                                tr("editor.confirm_delete")) != QMessageBox.StandardButton.Yes:
            return
        self._store.delete_group(group_id)
        self._persist()
        self._reload_tree()

    def _delete_request(self, request_id: str) -> None:
        self._store.delete_request(request_id)
        if self._current_request_id == request_id:
            self._current_request_id = None
            self._reset_response_pane()
            self._configure_response_tabs_for_flow(None)
        self._persist()
        self._reload_tree()

    # ------------------------------------------------------------------ #
    # Loading flows / saved requests into the editor
    # ------------------------------------------------------------------ #

    def load_flow(self, flow: FlowModel) -> None:
        """Populate request fields from a captured FlowModel."""
        self._show_work_area()
        self._current_request_id = None
        self._current_group_id = None
        self._method_combo.setCurrentText(flow.method.upper())
        self._apply_method_combo_style()
        self._url_input.setText(flow.url)

        # Prefer cookies parsed at capture time — they survive HTTP/2's split
        # Cookie fields, which dict(headers) flattens into an un-splittable
        # ", "-joined string. Fall back to splitting the header only when the
        # structured list is absent (e.g. older saved/replayed flows).
        cookie_rows = [
            (True, name, normalize_cookie_value(val))
            for name, val in (getattr(flow, "request_cookies", None) or [])
        ]

        header_rows = []
        for key, value in (flow.request_headers or {}).items():
            low = key.lower()
            if low == "cookie":
                if not cookie_rows:
                    cookie_rows = [
                        (True, n, normalize_cookie_value(v))
                        for n, v in self._split_cookie_header(value)
                    ]
                continue   # cookies live in their own tab, not Headers
            if low in ("host", "content-length"):
                continue   # recomputed by httpx at send time
            header_rows.append((True, key, value))
        self._headers_table.set_rows(header_rows)
        self._cookies_table.set_rows(cookie_rows)

        raw_body = flow.get_request_body_raw_text() if flow.request_body else ""
        self._body_area.set_body(raw_body, flow.request_content_type)
        self._name_input.setText(self._default_name_for_editor(flow.url))
        self._sync_params_from_url()
        self._try_bind_saved_request_identity()

    def load_request(self, req: SavedRequest) -> None:
        """Populate the editor from a previously saved request."""
        self._send_disabled = False
        self._btn_send.setEnabled(True)
        self._show_work_area()
        self._current_request_id = req.id
        found = self._store.find_request(req.id)
        self._current_group_id = found[0].id if found else None
        self._method_combo.setCurrentText(req.method.upper())
        self._apply_method_combo_style()
        self._url_input.setText(req.url)
        self._headers_table.set_rows(req.headers)
        self._cookies_table.set_rows([
            (en, k, normalize_cookie_value(v)) for en, k, v in req.cookies
        ])
        self._body_area.set_body(req.body, self._content_type_from_rows(req.headers))
        self._name_input.setText(req.name.strip() or self._default_name_for_editor(req.url))
        self._set_signer_id(req.signer_id)
        self._sync_params_from_url()
        self._show_response_for_saved_request(req.id)

    def _show_response_for_saved_request(self, request_id: str) -> None:
        """Show persisted (or empty) last Send response for a saved request."""
        found = self._store.find_request(request_id)
        snap = found[1].last_response if found else None
        if snap and snap.has_data:
            flow = snap.to_flow_model(found[1])
            self._display_captured_response(flow)
            self._configure_response_tabs_for_flow(flow)
        else:
            self._reset_response_pane()
            self._configure_response_tabs_for_flow(None)

    @staticmethod
    def _split_cookie_header(value: str):
        out = []
        for chunk in (value or "").split(";"):
            chunk = chunk.strip()
            if "=" in chunk:
                name, _, val = chunk.partition("=")
                if name.strip():
                    out.append((name.strip(), val.strip()))
        return out

    # ------------------------------------------------------------------ #
    # URL ⇄ Params two-way sync
    # ------------------------------------------------------------------ #

    def _sync_params_from_url(self) -> None:
        if self._suspend_sync:
            return
        parsed = urlparse(self._url_input.text().strip())
        rows = [(True, k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)]
        self._suspend_sync = True
        try:
            self._params_table.set_rows(rows)
        finally:
            self._suspend_sync = False

    def _sync_url_from_params(self) -> None:
        if self._suspend_sync:
            return
        parsed = urlparse(self._url_input.text().strip())
        pairs = [(k, v) for _enabled, k, v in self._params_table.rows(enabled_only=False)]
        new_query = urlencode(pairs)
        rebuilt = urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, parsed.fragment,
        ))
        self._suspend_sync = True
        try:
            self._url_input.setText(rebuilt)
        finally:
            self._suspend_sync = False

    # ------------------------------------------------------------------ #
    # Cookie sync
    # ------------------------------------------------------------------ #

    def _sync_cookies(self, source: str) -> None:
        host = (urlparse(self._url_input.text().strip()).hostname or "").lower()
        if not host:
            QMessageBox.information(self, tr("editor.sync_cookie"), tr("editor.cookie.no_host"))
            return

        if source == "captured":
            pairs = self._cookie_jar.cookies_for(host)
            source_label = tr("editor.cookie.captured")
        else:
            pairs = read_safari_cookies(host)
            source_label = tr("editor.cookie.safari")

        if not pairs:
            QMessageBox.information(
                self, tr("editor.sync_cookie"),
                tr("editor.cookie.none", host=host, source=source_label),
            )
            return

        self._merge_cookie_pairs(pairs)

    def _sync_cookies_chrome(self) -> None:
        host = (urlparse(self._url_input.text().strip()).hostname or "").lower()
        if not host:
            QMessageBox.information(self, tr("editor.sync_cookie"), tr("editor.cookie.no_host"))
            return
        if self._chrome_sync_busy:
            return
        self._chrome_sync_busy = True
        self._btn_sync_cookie.setEnabled(False)

        wait = QProgressDialog(tr("editor.cookie.chrome_wait"), None, 0, 0, self)
        wait.setWindowTitle(tr("editor.sync_cookie"))
        wait.setWindowModality(Qt.WindowModality.WindowModal)
        wait.setMinimumDuration(0)
        wait.setCancelButton(None)
        wait.setAutoClose(False)
        wait.setAutoReset(False)
        self._chrome_wait = wait
        wait.show()

        def _done(result: ChromeCookieRead) -> None:
            self._chrome_cookies_ready.emit(result)

        _ChromeCookieWorker(host, _done).start()

    def _on_chrome_cookies_ready(self, result: ChromeCookieRead) -> None:
        self._chrome_sync_busy = False
        self._btn_sync_cookie.setEnabled(True)
        if hasattr(self, "_chrome_wait"):
            self._chrome_wait.close()

        host = (urlparse(self._url_input.text().strip()).hostname or "").lower()
        if result.error == "keychain_denied":
            QMessageBox.warning(
                self, tr("editor.sync_cookie"), tr("editor.cookie.chrome_keychain_denied"))
            return
        if result.error == "keychain_unavailable":
            QMessageBox.warning(
                self, tr("editor.sync_cookie"), tr("editor.cookie.chrome_keychain_unavailable"))
            return
        if result.error == "no_database":
            QMessageBox.warning(
                self, tr("editor.sync_cookie"), tr("editor.cookie.chrome_no_database"))
            return
        if result.error == "permission_denied":
            QMessageBox.warning(
                self, tr("editor.sync_cookie"), tr("editor.cookie.chrome_permission"))
            return
        if result.error == "decrypt_unavailable":
            QMessageBox.warning(
                self, tr("editor.sync_cookie"), tr("editor.cookie.chrome_decrypt"))
            return
        if not result.pairs:
            QMessageBox.information(
                self, tr("editor.sync_cookie"),
                tr("editor.cookie.none", host=host, source=tr("editor.cookie.chrome")),
            )
            return
        self._merge_cookie_pairs(result.pairs)
        if not self._has_session_cookie(result.pairs):
            QMessageBox.warning(
                self, tr("editor.sync_cookie"), tr("editor.cookie.chrome_no_session"))

    def _merge_cookie_pairs(self, pairs: list) -> None:
        existing = {k: (en, v) for en, k, v in self._cookies_table.rows()}
        for name, value in pairs:
            clean = normalize_cookie_value(value)
            if name and clean:
                existing[name] = (True, clean)
        merged = [(en, k, v) for k, (en, v) in existing.items()]
        self._cookies_table.set_rows(merged)

    @staticmethod
    def _has_session_cookie(pairs: list) -> bool:
        for name, val in pairs:
            low = name.lower()
            if "sess" in low or low in ("sid", "sessionid", "token"):
                return len(val) >= 8
        return False

    @staticmethod
    def _http_header_value(value: str) -> str:
        """Ensure generic header values are latin-1 safe for httpx."""
        return cookie_value_for_wire(value) if value else value

    # ------------------------------------------------------------------ #
    # Body
    # ------------------------------------------------------------------ #

    def _on_body_format_failed(self) -> None:
        QMessageBox.information(self, tr("editor.format_json"), tr("editor.body.not_json"))

    def _on_body_mode_changed(self, mode: str) -> None:
        """Keep the Content-Type header in step when the user switches Body mode."""
        current = self._content_type_from_rows(self._headers_table.rows())
        if mode == RequestBodyEditor.MODE_FORM:
            if "x-www-form-urlencoded" not in current.lower():
                self._set_header_value("Content-Type", "application/x-www-form-urlencoded")
        elif "x-www-form-urlencoded" in current.lower():
            self._set_header_value("Content-Type", "application/json")

    @staticmethod
    def _content_type_from_rows(rows) -> str:
        for _en, key, value in rows:
            if key.lower() == "content-type":
                return value
        return ""

    def _set_header_value(self, name: str, value: str) -> None:
        low = name.lower()
        new_rows = []
        found = False
        for en, key, val in self._headers_table.rows():
            if key.lower() == low:
                new_rows.append((True, key, value))
                found = True
            else:
                new_rows.append((en, key, val))
        if not found:
            new_rows.append((True, name, value))
        self._headers_table.set_rows(new_rows)

    # ------------------------------------------------------------------ #
    # Signers (auth.json profiles)
    # ------------------------------------------------------------------ #

    def _reload_signer_combo(self, select_id: str = "") -> None:
        from gui.icons import lock_icon

        self._auth_store = AuthStore.load()
        keep = select_id if select_id != "" else self._selected_signer_id()
        self._signer_combo.blockSignals(True)
        self._signer_combo.clear()
        self._signer_combo.addItem(
            lock_icon("#6c7086"), tr("editor.signer.short_none"), "")
        for signer in self._auth_store.signers():
            label = signer.name or signer.id
            self._signer_combo.addItem(lock_icon("#f9e2af"), label, signer.id)
        idx = self._signer_combo.findData(keep)
        self._signer_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._signer_combo.setMaxVisibleItems(max(1, self._signer_combo.count()))
        self._signer_combo.blockSignals(False)
        self._update_signer_combo_appearance()

    def _selected_signer_id(self) -> str:
        data = self._signer_combo.currentData()
        return str(data) if data else ""

    def _set_signer_id(self, signer_id: str) -> None:
        idx = self._signer_combo.findData(signer_id or "")
        self._signer_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _apply_selected_signer(
        self, headers: dict, body: bytes
    ) -> Optional[Tuple[dict, bytes]]:
        """Return (headers, body) after signing, or None if user should abort."""
        signer_id = self._selected_signer_id()
        if not signer_id:
            return headers, body
        config = self._auth_store.find(signer_id)
        if config is None:
            QMessageBox.warning(
                self, tr("editor.signer.title"),
                tr("editor.signer.not_found", id=signer_id),
            )
            return None
        try:
            return apply_signer(config, headers, body)
        except ValueError as exc:
            QMessageBox.warning(
                self, tr("editor.signer.title"), tr("editor.signer.failed", err=str(exc)),
            )
            return None

    # ------------------------------------------------------------------ #
    # Sending
    # ------------------------------------------------------------------ #

    def _collect_send_headers(self) -> tuple[dict, dict]:
        """Build headers dict + cookies dict (httpx formats the Cookie header)."""
        headers: dict = {}
        cookies: dict = {}
        for _en, key, value in self._headers_table.rows(enabled_only=True):
            if not key:
                continue
            if key.lower() == "cookie":
                continue
            headers[key] = self._http_header_value(value)
        for _en, key, value in self._cookies_table.rows(enabled_only=True):
            if key and value:
                wire = cookie_value_for_wire(value)
                if wire:
                    cookies[key] = wire
        lower = {k.lower() for k in headers}
        for name, val in _BROWSER_DEFAULT_HEADERS.items():
            if name.lower() not in lower:
                headers[name] = val
        return headers, cookies

    def _send(self) -> None:
        if self._send_disabled:
            return
        url = self._url_input.text().strip()
        if not url:
            QMessageBox.information(self, tr("editor.send"), tr("editor.no_url"))
            return
        if "://" not in url:
            url = "http://" + url
            self._url_input.setText(url)

        method = self._method_combo.currentText()
        headers, cookies = self._collect_send_headers()
        if self._body_area.mode() == RequestBodyEditor.MODE_FORM and not any(
            k.lower() == "content-type" for k in headers
        ):
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = self._body_area.body_text().encode("utf-8")

        signed = self._apply_selected_signer(headers, body)
        if signed is None:
            return
        headers, body = signed

        self._btn_send.setEnabled(False)
        self._resp_status.setText(tr("editor.sending"))

        worker = _SendWorker(
            method, url, headers, cookies, body,
            on_done=lambda flow, err: self._response_ready.emit(flow, err),
        )
        worker.start()

    def _on_response_ready(self, flow: Optional[FlowModel], error: Optional[str]) -> None:
        self._btn_send.setEnabled(not self._send_disabled)
        self._configure_response_tabs_for_flow(
            None if flow is None else flow)
        if flow is not None and flow.flow_type != "websocket":
            self._resp_tabs.setTabVisible(self._ws_tab_index, False)
        if error is not None or flow is None:
            self._resp_status.setText(tr("editor.error", err=error or "unknown"))
            self._resp_status.setStyleSheet(
                "background:#2d1b1b; color:#f38ba8; font-size:12px; padding:6px 12px;"
                "border-bottom:1px solid #45293a;"
            )
            self._resp_body.set_body("")
            self._resp_headers.set_headers({})
            return

        self._display_captured_response(flow)
        if flow.flow_type != "websocket":
            text, _ = flow.get_response_body_display()
            if "登录失效" in text or '"errno": 4000' in text:
                self._maybe_tip_auth_failure()
        self._persist_last_response_for_current(flow)

    def _persist_last_response_for_current(self, flow: FlowModel) -> None:
        """Write last Send response onto the open saved request in collections.json."""
        if not self._current_request_id:
            return
        found = self._store.find_request(self._current_request_id)
        if not found:
            return
        _, req = found
        req.last_response = SavedResponseSnapshot.from_flow(flow)
        self._persist()

    def _maybe_tip_auth_failure(self) -> None:
        """Hint when the server rejects cookies (common after Chrome v20 encryption)."""
        QMessageBox.information(self, tr("editor.sync_cookie"), tr("editor.cookie.auth_tip"))

    # ------------------------------------------------------------------ #
    # Saving — identity / duplicate matching
    # ------------------------------------------------------------------ #

    @staticmethod
    def _method_url_key(method: str, url: str) -> Tuple[str, str]:
        return method.upper().strip(), url.strip()

    @staticmethod
    def _normalize_kv_rows(rows: List[tuple], *, normalize_values: bool = False) -> Tuple:
        out = []
        for en, key, value in rows:
            key = str(key).strip()
            if not key:
                continue
            val = normalize_cookie_value(value) if normalize_values else str(value)
            out.append((bool(en), key, val))
        return tuple(out)

    def _editor_content_signature(self) -> Tuple:
        return (
            self._method_url_key(
                self._method_combo.currentText(),
                self._url_input.text(),
            ),
            self._normalize_kv_rows(self._headers_table.rows()),
            self._normalize_kv_rows(self._cookies_table.rows(), normalize_values=True),
            self._body_area.body_text(),
        )

    @staticmethod
    def _saved_content_signature(req: SavedRequest) -> Tuple:
        return (
            RequestEditorPanel._method_url_key(req.method, req.url),
            RequestEditorPanel._normalize_kv_rows(req.headers),
            RequestEditorPanel._normalize_kv_rows(req.cookies, normalize_values=True),
            req.body,
        )

    def _iter_saved_requests(self) -> List[Tuple[RequestGroup, SavedRequest]]:
        return [(g, r) for g in self._store.groups() for r in g.requests]

    def _find_exact_matching_saved_request(self) -> Optional[Tuple[RequestGroup, SavedRequest]]:
        sig = self._editor_content_signature()
        for group, req in self._iter_saved_requests():
            if self._saved_content_signature(req) == sig:
                return group, req
        return None

    def _find_by_method_url(self, method: str, url: str) -> List[Tuple[RequestGroup, SavedRequest]]:
        key = self._method_url_key(method, url)
        return [
            (g, r) for g, r in self._iter_saved_requests()
            if self._method_url_key(r.method, r.url) == key
        ]

    def _resolve_save_target(self) -> Optional[Tuple[RequestGroup, SavedRequest]]:
        """Pick an existing saved request to update, if the editor matches one."""
        if self._current_request_id:
            found = self._store.find_request(self._current_request_id)
            if found:
                return found
        exact = self._find_exact_matching_saved_request()
        if exact:
            return exact
        hits = self._find_by_method_url(
            self._method_combo.currentText(),
            self._url_input.text().strip(),
        )
        if len(hits) == 1:
            return hits[0]
        return None

    def _bind_saved_request(self, group: RequestGroup, req: SavedRequest) -> None:
        self._current_request_id = req.id
        self._current_group_id = group.id
        if req.name.strip():
            self._name_input.setText(req.name.strip())

    def _try_bind_saved_request_identity(self) -> None:
        """After loading from traffic, link to an existing saved entry when unambiguous."""
        target = self._resolve_save_target()
        if target is not None:
            self._bind_saved_request(target[0], target[1])

    # ------------------------------------------------------------------ #
    # Saving
    # ------------------------------------------------------------------ #

    def _build_saved_request(self, request_id: Optional[str]) -> SavedRequest:
        last_response: Optional[SavedResponseSnapshot] = None
        if self._flow_has_storable_response(self._last_response_flow):
            last_response = SavedResponseSnapshot.from_flow(self._last_response_flow)
        elif request_id:
            found = self._store.find_request(request_id)
            if found:
                last_response = found[1].last_response
        return SavedRequest(
            id=request_id or SavedRequest().id,
            name=self._name_input.text().strip()
                   or self._default_name_for_editor(self._url_input.text().strip()),
            method=self._method_combo.currentText(),
            url=self._url_input.text().strip(),
            headers=self._headers_table.rows(),
            cookies=self._cookies_table.rows(),
            body=self._body_area.body_text(),
            last_response=last_response,
            signer_id=self._selected_signer_id(),
        )

    def _new_group_from_picker(self) -> Optional[str]:
        """Create a group while the save picker is open; returns the new name."""
        dlg = TextPromptDialog(tr("editor.new_group"), tr("editor.group_name"), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        name = dlg.text()
        if not name:
            return None
        group = self._store.add_group(name)
        self._persist()
        self._reload_tree()
        return group.name

    def _group_for_host_url(self) -> Optional[RequestGroup]:
        """Find or create a collection group named after the request host."""
        url = self._url_input.text().strip()
        if not url:
            QMessageBox.information(self, tr("editor.save"), tr("editor.no_url"))
            return None
        host = (urlparse(url).hostname or "").strip()
        if not host:
            QMessageBox.information(self, tr("editor.save"), tr("editor.no_url"))
            return None
        for group in self._store.groups():
            if group.name == host:
                return group
        return self._store.add_group(host)

    def _pick_save_group(self, title_key: str = "editor.save_as") -> Optional[RequestGroup]:
        """Ask which group to save into (Save As only); returns RequestGroup or None if cancelled."""
        groups = self._store.groups()
        if not groups:
            self._store.ensure_default_group()
            groups = self._store.groups()
        names = [g.name for g in groups]
        dlg = GroupPickerDialog(
            tr(title_key),
            tr("editor.choose_group"),
            names,
            self,
            new_group_label=tr("editor.picker.new_group"),
            on_new_group=self._new_group_from_picker,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        choice = dlg.selected()
        if not choice:
            return None
        groups = self._store.groups()
        return next((g for g in groups if g.name == choice), groups[0] if groups else None)

    def _save(self) -> None:
        """Update a matching saved item, or save into the host-named group (no dialog)."""
        target = self._resolve_save_target()
        if target is not None:
            group, existing = target
            req = self._build_saved_request(existing.id)
            if self._store.update_request(req):
                self._bind_saved_request(group, req)
                self._last_save_group_id = group.id
                self._persist()
                self._reload_tree()
                self._flash_saved()
            return

        group = self._group_for_host_url()
        if group is None:
            return
        req = self._build_saved_request(None)
        self._store.add_request(group.id, req)
        self._bind_saved_request(group, req)
        self._last_save_group_id = group.id
        self._persist()
        self._reload_tree()
        self._flash_saved()

    def _save_as(self) -> None:
        """Always create a new saved request and pick the target group."""
        group = self._pick_save_group("editor.save_as")
        if group is None:
            return
        req = self._build_saved_request(None)
        self._store.add_request(group.id, req)
        self._current_request_id = req.id
        self._current_group_id = group.id
        self._last_save_group_id = group.id
        self._persist()
        self._reload_tree()
        self._flash_saved()

    def _flash_saved(self) -> None:
        from PyQt6.QtCore import QTimer
        prev = self._resp_status.text()
        self._resp_status.setText(tr("editor.saved"))
        QTimer.singleShot(
            1200,
            lambda: self._resp_status.setText(prev or tr("editor.no_response")),
        )

    def _persist(self) -> None:
        try:
            self._store.save()
        except OSError:
            pass
        if self._on_store_changed is not None:
            self._on_store_changed()


RequestEditorDialog = RequestEditorPanel

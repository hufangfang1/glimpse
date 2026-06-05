"""
RequestEditorDialog — a Postman-style editor for composing & sending requests.

Opened non-modally (so several can coexist) from the traffic table's right-click
"Edit" action, or empty from the toolbar. Layout:

    ┌───────────┬─────────────────────────────────────────────┐
    │ Collections│  [METHOD ▾] [ URL .................. ] [Send]│
    │  (groups   │  [Save] [Save As]                            │
    │   tree)    │  ┌ Params │ Headers │ Cookies │ Body ┐       │
    │            │  │            editable tabs            │     │
    │            │  ├────────────────────────────────────┤     │
    │            │  │  Response: status · headers · body  │     │
    └───────────┴─────────────────────────────────────────────┘

Sending runs httpx on a worker thread; the result is marshalled back to the GUI
thread via a Qt signal and rendered with the existing read-only viewers.
"""
from __future__ import annotations

import json
import threading
import uuid
from typing import List, Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

import httpx
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
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
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from proxy.collections import CollectionStore, SavedRequest
from proxy.cookies import (
    CapturedCookieJar,
    ChromeCookieRead,
    read_chrome_cookies_detail,
    read_safari_cookies,
    cookie_value_for_wire,
    normalize_cookie_value,
)
from proxy.models import FlowModel
from gui.i18n import i18n, tr
from gui.icons import file_doc
from gui.themes import DARK, METHOD_COLORS, status_color
from gui.widgets.detail_panel import BodyPanel, HeadersView, JsonHighlighter
from gui.widgets.kv_table import KeyValueTable

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

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
            with httpx.Client(verify=False, follow_redirects=True, timeout=30) as client:
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


class GroupPickerDialog(QDialog):
    """Small dark-styled 'choose a group' dialog used by Save As.

    Replaces ``QInputDialog.getItem`` whose embedded combo popup ignores our
    stylesheet on macOS. A list is also clearer when there are many groups.
    """

    def __init__(self, title: str, prompt: str, names: list[str], parent=None) -> None:
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
        self._list.setMinimumHeight(min(220, max(120, row_h * len(names) + 12)))
        self._list.itemDoubleClicked.connect(lambda _i: self.accept())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(label)
        layout.addWidget(self._list, 1)
        layout.addWidget(buttons)

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


class RequestEditorDialog(QDialog):
    """Non-modal Postman-style request composer with saved collections."""

    # Worker → GUI thread bridge. Carries (FlowModel|None, error_str|None).
    _response_ready = pyqtSignal(object, object)
    _chrome_cookies_ready = pyqtSignal(object)

    def __init__(self, store: CollectionStore, cookie_jar: CapturedCookieJar,
                 on_store_changed=None, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._cookie_jar = cookie_jar
        self._on_store_changed = on_store_changed
        # The saved request currently bound to the editor (None = unsaved draft).
        self._current_request_id: Optional[str] = None
        self._current_group_id: Optional[str] = None
        self._last_save_group_id: Optional[str] = None
        self._suspend_sync = False

        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(1040, 720)
        # Top-level editor windows do not always inherit the main window QSS on macOS.
        self.setStyleSheet(DARK)

        self._build_ui()
        self._response_ready.connect(self._on_response_ready)
        self._chrome_cookies_ready.connect(self._on_chrome_cookies_ready)
        self._chrome_sync_busy = False
        i18n.language_changed.connect(self.retranslate)
        self.retranslate()
        self._reload_tree()

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # ── Left: collections tree ──
        self._tree = QTreeWidget()
        self._tree.setObjectName("editor_collections")
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(220)
        # Indent child requests under groups; branch glyphs stay off (icons carry expand state).
        self._tree.setIndentation(18)
        self._tree.setIconSize(QSize(22, 22))
        self._tree.setRootIsDecorated(False)
        self._tree.setAnimated(True)
        self._tree.itemClicked.connect(self._on_tree_clicked)
        self._tree.itemExpanded.connect(self._on_group_expand_changed)
        self._tree.itemCollapsed.connect(self._on_group_expand_changed)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_menu)

        left = QWidget()
        left.setObjectName("editor_sidebar")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)
        self._btn_new_group = QPushButton()
        self._btn_new_group.clicked.connect(self._new_group)
        left_layout.addWidget(self._btn_new_group)
        left_layout.addWidget(self._tree, 1)

        # ── Right: editor + response ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)
        right_layout.addLayout(self._build_url_bar())
        right_layout.addLayout(self._build_save_bar())

        editor_response = QSplitter(Qt.Orientation.Vertical)
        editor_response.addWidget(self._build_request_tabs())
        editor_response.addWidget(self._build_response_area())
        editor_response.setSizes([360, 320])
        right_layout.addWidget(editor_response, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([240, 800])
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter)

    def _build_url_bar(self):
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._method_combo = QComboBox()
        self._method_combo.setObjectName("method_combo")
        self._method_combo.addItems(_METHODS)
        self._method_combo.setFixedWidth(104)
        # QListView forces a Qt popup on macOS; native menus ignore our dark QSS.
        popup = QListView(self._method_combo)
        popup.setSpacing(2)
        popup.setUniformItemSizes(True)
        popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        popup.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        popup.setFrameShape(QListView.Shape.NoFrame)
        self._method_combo.setView(popup)
        self._method_combo.setMaxVisibleItems(max(len(_METHODS), 12))
        self._method_combo.setItemDelegate(_MethodDelegate(self._method_combo))
        self._method_combo.currentIndexChanged.connect(
            lambda _i: self._apply_method_combo_style())
        self._apply_method_combo_style()
        _orig_show_popup = self._method_combo.showPopup

        def _show_method_popup() -> None:
            _orig_show_popup()
            self._fit_method_popup()

        self._method_combo.showPopup = _show_method_popup  # type: ignore[method-assign]
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://api.example.com/path")
        self._url_input.editingFinished.connect(self._sync_params_from_url)
        self._url_input.returnPressed.connect(self._send)
        self._btn_send = QPushButton()
        self._btn_send.setObjectName("btn_start")
        self._btn_send.setFixedWidth(90)
        self._btn_send.clicked.connect(self._send)
        bar.addWidget(self._method_combo)
        bar.addWidget(self._url_input, 1)
        bar.addWidget(self._btn_send)
        return bar

    def _build_save_bar(self):
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._name_label = QLabel()
        self._name_input = QLineEdit()
        self._name_input.setMinimumWidth(160)
        self._btn_save = QPushButton()
        self._btn_save.clicked.connect(self._save)
        self._btn_save_as = QPushButton()
        self._btn_save_as.clicked.connect(self._save_as)
        bar.addWidget(self._name_label)
        bar.addWidget(self._name_input, 1)
        bar.addWidget(self._btn_save)
        bar.addWidget(self._btn_save_as)
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

        # Body tab: format button + editable text.
        body_wrap = QWidget()
        bw = QVBoxLayout(body_wrap)
        bw.setContentsMargins(0, 0, 0, 0)
        bw.setSpacing(4)
        body_bar = QHBoxLayout()
        self._btn_format = QPushButton()
        self._btn_format.setFixedWidth(120)
        self._btn_format.clicked.connect(self._format_body)
        body_bar.addWidget(self._btn_format)
        body_bar.addStretch()
        self._body_editor = BodyEditor()
        bw.addLayout(body_bar)
        bw.addWidget(self._body_editor, 1)

        self._tabs.addTab(self._params_table, "")
        self._tabs.addTab(self._headers_table, "")
        self._tabs.addTab(cookies_wrap, "")
        self._tabs.addTab(body_wrap, "")
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
        self._resp_tabs.addTab(self._resp_body, "")
        self._resp_tabs.addTab(self._resp_headers, "")

        layout.addWidget(self._resp_status)
        layout.addWidget(self._resp_tabs, 1)
        return wrap

    # ------------------------------------------------------------------ #
    # i18n
    # ------------------------------------------------------------------ #

    def retranslate(self, _lang: str = "") -> None:
        self.setWindowTitle(tr("editor.title"))
        self._btn_new_group.setText(tr("editor.new_group"))
        self._btn_send.setText(tr("editor.send"))
        self._name_label.setText(tr("editor.name.label"))
        self._name_input.setPlaceholderText(tr("editor.name.placeholder"))
        self._name_input.setToolTip(tr("editor.name.tooltip"))
        self._btn_save.setText(tr("editor.save"))
        self._btn_save.setToolTip(tr("editor.save.tooltip"))
        self._btn_save_as.setText(tr("editor.save_as"))
        self._btn_save_as.setToolTip(tr("editor.save_as.tooltip"))
        self._btn_sync_cookie.setText(tr("editor.sync_cookie"))
        self._act_cookie_captured.setText(tr("editor.cookie.captured"))
        self._act_cookie_chrome.setText(tr("editor.cookie.chrome"))
        self._act_cookie_safari.setText(tr("editor.cookie.safari"))
        self._btn_format.setText(tr("editor.format_json"))
        self._tabs.setTabText(0, tr("editor.tab.params"))
        self._tabs.setTabText(1, tr("editor.tab.headers"))
        self._tabs.setTabText(2, tr("editor.tab.cookies"))
        self._tabs.setTabText(3, tr("editor.tab.body"))
        self._resp_tabs.setTabText(0, tr("section.body"))
        self._resp_tabs.setTabText(1, tr("section.headers"))
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
                padding: 4px 28px 4px 10px;
                color: {fg};
                font-weight: 600;
                min-height: 24px;
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
        """)
        frame = view.window()
        frame.setStyleSheet("""
            QFrame {
                background-color: #1e1e2e;
                border: 1px solid #45475a;
                border-radius: 8px;
            }
        """)

    def _fit_method_popup(self) -> None:
        """Size the method dropdown to exactly fit all items — no scrollbar."""
        from PyQt6.QtWidgets import QScrollBar

        combo = self._method_combo
        view = combo.view()
        if view is None:
            return
        n = max(1, combo.count())
        row_h = view.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 28
        pad = 8
        h = row_h * n + pad
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setFixedHeight(h)
        view.setMinimumHeight(h)
        view.setMaximumHeight(h)
        popup = view.window()
        w = max(combo.width(), 108)
        frame = popup.frameWidth() * 2
        popup.setFixedSize(w, h + frame)
        for bar in popup.findChildren(QScrollBar):
            bar.setVisible(False)

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
            return RequestEditorDialog._path_from_url(req.url)
        return RequestEditorDialog._path_from_legacy_name(req.name)

    @staticmethod
    def _default_name_for_editor(url: str = "") -> str:
        """Initial value for the name field (path only, no host/method)."""
        if url.strip():
            return RequestEditorDialog._path_from_url(url)
        return "/"

    @staticmethod
    def _path_from_legacy_name(name: str) -> str:
        """Best-effort path for older saves that stored method/host in ``name``."""
        text = (name or "").strip() or "/"
        if text.startswith(("http://", "https://")):
            return RequestEditorDialog._path_from_url(text)
        upper = text.upper()
        for method in _METHODS:
            for sep in (" · ", " ", " - "):
                prefix = f"{method}{sep}"
                if upper.startswith(prefix):
                    text = text[len(prefix):].strip()
                    break
        if text.startswith(("http://", "https://")):
            return RequestEditorDialog._path_from_url(text)
        if "://" in text:
            return RequestEditorDialog._path_from_url(text)
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
            for req in group.requests:
                r_item = QTreeWidgetItem([self._request_tree_title(req)])
                r_item.setData(0, Qt.ItemDataRole.UserRole, ("request", req.id))
                color = METHOD_COLORS.get(req.method, ("#cdd6f4", ""))[0]
                r_item.setForeground(0, QColor(color))
                r_item.setIcon(0, file_doc(color))
                r_item.setToolTip(0, req.url)
                g_item.addChild(r_item)
            self._tree.addTopLevelItem(g_item)
            g_item.setExpanded(True)

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
        self._persist()
        self._reload_tree()

    # ------------------------------------------------------------------ #
    # Loading flows / saved requests into the editor
    # ------------------------------------------------------------------ #

    def load_flow(self, flow: FlowModel) -> None:
        """Populate the editor from a captured FlowModel (right-click → Edit)."""
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

        body_text = flow.get_request_body_text() if flow.request_body else ""
        self._body_editor.setPlainText(body_text)
        self._name_input.setText(self._default_name_for_editor(flow.url))
        self._sync_params_from_url()

    def load_request(self, req: SavedRequest) -> None:
        """Populate the editor from a previously saved request."""
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
        self._body_editor.setPlainText(req.body)
        self._name_input.setText(req.name.strip() or self._default_name_for_editor(req.url))
        self._sync_params_from_url()

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

    def _format_body(self) -> None:
        if not self._body_editor.format_json():
            QMessageBox.information(self, tr("editor.format_json"), tr("editor.body.not_json"))

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
        url = self._url_input.text().strip()
        if not url:
            QMessageBox.information(self, tr("editor.send"), tr("editor.no_url"))
            return
        if "://" not in url:
            url = "http://" + url
            self._url_input.setText(url)

        method = self._method_combo.currentText()
        headers, cookies = self._collect_send_headers()
        body = self._body_editor.toPlainText().encode("utf-8")

        self._btn_send.setEnabled(False)
        self._resp_status.setText(tr("editor.sending"))

        worker = _SendWorker(
            method, url, headers, cookies, body,
            on_done=lambda flow, err: self._response_ready.emit(flow, err),
        )
        worker.start()

    def _on_response_ready(self, flow: Optional[FlowModel], error: Optional[str]) -> None:
        self._btn_send.setEnabled(True)
        if error is not None or flow is None:
            self._resp_status.setText(tr("editor.error", err=error or "unknown"))
            self._resp_status.setStyleSheet(
                "background:#2d1b1b; color:#f38ba8; font-size:12px; padding:6px 12px;"
                "border-bottom:1px solid #45293a;"
            )
            self._resp_body.set_body("")
            self._resp_headers.set_headers({})
            return

        sc = flow.status_code or 0
        self._resp_status.setText(
            tr("editor.response_status",
               code=sc, reason=flow.status_message,
               size=flow.format_size(), dur=flow.format_duration())
        )
        self._resp_status.setStyleSheet(
            f"background:#181825; color:{status_color(sc)}; font-size:12px; padding:6px 12px;"
            "border-bottom:1px solid #313244;"
        )
        self._resp_headers.set_headers(flow.response_headers)
        if flow.is_image():
            self._resp_body.set_body(
                tr("body.binary_image", ctype=flow.content_type or "?", size=flow.format_size()),
                is_json=False,
            )
        else:
            text, is_json = flow.get_response_body_display()
            self._resp_body.set_body(text, is_json=is_json)
            if "登录失效" in text or '"errno": 4000' in text:
                self._maybe_tip_auth_failure()

    def _maybe_tip_auth_failure(self) -> None:
        """Hint when the server rejects cookies (common after Chrome v20 encryption)."""
        QMessageBox.information(self, tr("editor.sync_cookie"), tr("editor.cookie.auth_tip"))

    # ------------------------------------------------------------------ #
    # Saving
    # ------------------------------------------------------------------ #

    def _build_saved_request(self, request_id: Optional[str]) -> SavedRequest:
        return SavedRequest(
            id=request_id or SavedRequest().id,
            name=self._name_input.text().strip()
                   or self._default_name_for_editor(self._url_input.text().strip()),
            method=self._method_combo.currentText(),
            url=self._url_input.text().strip(),
            headers=self._headers_table.rows(),
            cookies=self._cookies_table.rows(),
            body=self._body_editor.toPlainText(),
        )

    def _group_for_quick_save(self):
        """Default group for first-time Save (no picker)."""
        if self._last_save_group_id:
            for g in self._store.groups():
                if g.id == self._last_save_group_id:
                    return g
        if self._current_group_id:
            for g in self._store.groups():
                if g.id == self._current_group_id:
                    return g
        return self._store.ensure_default_group()

    def _save(self) -> None:
        """Update the open saved item, or first-time save into the default group."""
        if self._current_request_id is not None:
            req = self._build_saved_request(self._current_request_id)
            if self._store.update_request(req):
                if self._current_group_id:
                    self._last_save_group_id = self._current_group_id
                self._persist()
                self._reload_tree()
                self._flash_saved()
            return

        group = self._group_for_quick_save()
        req = self._build_saved_request(None)
        self._store.add_request(group.id, req)
        self._current_request_id = req.id
        self._current_group_id = group.id
        self._last_save_group_id = group.id
        self._persist()
        self._reload_tree()
        self._flash_saved()

    def _save_as(self) -> None:
        """Always create a new saved request and pick the target group."""
        groups = self._store.groups()
        if not groups:
            self._store.ensure_default_group()
            groups = self._store.groups()
        names = [g.name for g in groups]
        dlg = GroupPickerDialog(tr("editor.save_as"), tr("editor.choose_group"), names, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        choice = dlg.selected()
        if not choice:
            return
        group = next((g for g in groups if g.name == choice), groups[0])
        req = self._build_saved_request(None)
        self._store.add_request(group.id, req)
        self._current_request_id = req.id
        self._current_group_id = group.id
        self._last_save_group_id = group.id
        self._persist()
        self._reload_tree()
        self._flash_saved()

    def _flash_saved(self) -> None:
        self.setWindowTitle(tr("editor.saved"))
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(1200, lambda: self.setWindowTitle(tr("editor.title")))

    def _persist(self) -> None:
        try:
            self._store.save()
        except OSError:
            pass
        if self._on_store_changed is not None:
            self._on_store_changed()

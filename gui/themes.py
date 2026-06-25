"""
Dark theme stylesheet — Glimpse.
"""

# Toolbar / editor control row height (buttons, inputs, combos).
CONTROL_HEIGHT = 24

DARK = """
/* ── Global ─────────────────────────────────────────────────────── */
* {
    font-family: -apple-system, "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}

QMainWindow, QDialog {
    background-color: #1e1e2e;
}

QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
}

/* ── Menu bar ────────────────────────────────────────────────────── */
QMenuBar {
    background-color: #181825;
    color: #cdd6f4;
    border-bottom: 1px solid #313244;
    padding: 2px 4px;
    spacing: 2px;
}
QMenuBar::item {
    padding: 4px 10px;
    border-radius: 5px;
    background: transparent;
}
QMenuBar::item:selected,
QMenuBar::item:pressed {
    background-color: #313244;
    color: #cdd6f4;
}

/* ── Pop-up menus (menu bar dropdowns AND right-click context menus) ── */
QMenu {
    background-color: #1e1e2e;
    border: 1px solid #45475a;
    border-radius: 10px;
    padding: 6px 4px;
    color: #cdd6f4;
    font-size: 13px;
}
QMenu::item {
    background: transparent;
    color: #cdd6f4;
    padding: 6px 32px 6px 14px;
    margin: 1px 4px;
    border-radius: 6px;
    min-width: 170px;
}
QMenu::item:selected {
    background-color: #89b4fa;
    color: #11111b;
}
QMenu::item:disabled {
    color: #6c7086;
}
QMenu::separator {
    height: 1px;
    background-color: #313244;
    margin: 5px 10px;
}
QMenu::icon {
    padding-left: 8px;
}
/* Hide the checkable-item indicator column so non-checkable items don't
   get an awkward empty gutter on the left. */
QMenu::indicator {
    width: 0;
    height: 0;
    margin: 0;
}
QMenu::right-arrow {
    /* Native macOS arrow is inconsistent — we draw our own via menu title tabs. */
    width: 0;
    height: 0;
    margin: 0;
    image: none;
    border: none;
}

/* ── Find bar (response body search) ─────────────────────────────── */
QWidget#find_bar {
    background-color: #181825;
    border-bottom: 1px solid #313244;
}
QWidget#find_field {
    background-color: #11111b;
    border: 1px solid #313244;
    border-radius: 8px;
}
QWidget#find_field[focused="true"] {
    border-color: #89b4fa;
}
QLabel#find_icon {
    background: transparent;
    color: #6c7086;
    padding-left: 10px;
    padding-right: 2px;
}
QLineEdit#find_input {
    background: transparent;
    border: none;
    padding: 6px 4px 6px 0;
    color: #cdd6f4;
    font-size: 12px;
    selection-background-color: #45475a;
}
QLineEdit#find_input:focus {
    border: none;
}
QLabel#find_status {
    background: transparent;
    color: #6c7086;
    font-size: 11px;
    padding: 0 4px;
}
QWidget#find_nav_group {
    background-color: #1e1e2e;
    border: 1px solid #313244;
    border-radius: 7px;
}
QPushButton#find_nav_btn {
    background: transparent;
    border: none;
    border-radius: 0;
    min-width: 26px;
    max-width: 26px;
    min-height: 26px;
    max-height: 26px;
    padding: 0;
    margin: 0;
}
QPushButton#find_nav_btn:hover {
    background-color: #313244;
}
QPushButton#find_nav_btn:pressed {
    background-color: #45475a;
}
QPushButton#find_nav_btn:first-child {
    border-top-left-radius: 6px;
    border-bottom-left-radius: 6px;
    border-right: 1px solid #313244;
}
QPushButton#find_nav_btn:last-child {
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}
QPushButton#find_close_btn {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
    margin: 0;
}
QPushButton#find_close_btn:hover {
    background-color: #452632;
    border-color: #f38ba844;
}
QPushButton#find_close_btn:pressed {
    background-color: #5c3040;
}

/* ── Toolbar ─────────────────────────────────────────────────────── */
QToolBar {
    background-color: #181825;
    border-bottom: 1px solid #313244;
    padding: 3px 8px;
    spacing: 6px;
}
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 10px;
    color: #cdd6f4;
}
QToolButton:hover {
    background-color: #313244;
    border-color: #45475a;
}
QToolButton:pressed {
    background-color: #45475a;
}

/* ── Buttons ─────────────────────────────────────────────────────── */
QPushButton {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px 10px;
    color: #cdd6f4;
    min-height: 24px;
    max-height: 24px;
}
QPushButton:hover {
    background-color: #45475a;
}
QPushButton:pressed {
    background-color: #585b70;
}
QPushButton#btn_start {
    background-color: #a6e3a1;
    color: #1e1e2e;
    font-weight: 600;
    border-color: #a6e3a1;
}
QPushButton#btn_start:hover {
    background-color: #b9f5b4;
}
QPushButton#btn_stop {
    background-color: #f38ba8;
    color: #1e1e2e;
    font-weight: 600;
    border-color: #f38ba8;
}
QPushButton#btn_stop:hover {
    background-color: #f5a0b8;
}
QPushButton#kv_delete_btn {
    background: transparent;
    border: none;
    border-radius: 5px;
    padding: 0;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
}
QPushButton#kv_delete_btn:hover {
    background-color: #452632;
}
QPushButton#kv_delete_btn:pressed {
    background-color: #5c3040;
}
/* Dropdown arrow for buttons that own a QMenu (e.g. Sync Cookies). */
QPushButton::menu-indicator {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    right: 8px;
    width: 10px;
    height: 10px;
}
QPushButton#mode_selector {
    text-align: left;
    padding-left: 4px;
    padding-right: 28px;
}

/* ── LineEdit / SpinBox ──────────────────────────────────────────── */
QLineEdit, QSpinBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 2px 8px;
    color: #cdd6f4;
    min-height: 24px;
    max-height: 24px;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}
QLineEdit:focus, QSpinBox:focus {
    border-color: #89b4fa;
}
QSpinBox#proxy_port {
    min-height: 28px;
    max-height: 28px;
}
QLineEdit#editor_url_input,
QLineEdit#editor_name_input {
    padding: 4px 10px;
    min-height: 24px;
    max-height: 24px;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 0;
    border: none;
}

/* ── Signer combo (runtime QSS also applied in request_editor) ───── */
QComboBox#signer_combo {
    background-color: #252536;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 2px 26px 2px 8px;
    color: #6c7086;
    font-size: 12px;
    min-height: 24px;
    max-height: 24px;
}

/* ── ComboBox (method selector, Save-As group picker) ────────────── */
QComboBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 3px 8px;
    color: #cdd6f4;
    min-height: 22px;
}
QComboBox:hover {
    border-color: #585b70;
}
QComboBox:focus, QComboBox:on {
    border-color: #89b4fa;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border: none;
    background: transparent;
}
/* The down-arrow image is injected per-widget at runtime (a real PNG) because
   QSS cannot synthesize a triangle from borders — that renders as a square. */
QComboBox::down-arrow {
    width: 12px;
    height: 12px;
}
/* The popup list. QComboBox renders it via an item view, so style that too. */
QComboBox QAbstractItemView {
    background-color: #1e1e2e;
    border: 1px solid #45475a;
    border-radius: 8px;
    padding: 4px;
    color: #cdd6f4;
    outline: none;
    selection-background-color: #89b4fa;
    selection-color: #11111b;
}
QComboBox QAbstractItemView::item {
    padding: 5px 10px;
    border-radius: 5px;
    min-height: 20px;
}
QComboBox QAbstractItemView::item:selected,
QComboBox QAbstractItemView::item:hover {
    background-color: #89b4fa;
    color: #11111b;
}

/* ── Key/value tables (request editor Params / Headers / Cookies) ── */
QCheckBox#kv_row_check {
    background: transparent;
    spacing: 0;
}
QCheckBox#kv_row_check::indicator {
    width: 15px;
    height: 15px;
    border-radius: 3px;
    border: 1px solid #6c7086;
    background-color: #11111b;
}
QCheckBox#kv_row_check::indicator:hover {
    border-color: #89b4fa;
}
QCheckBox#kv_row_check::indicator:checked {
    border-color: #89b4fa;
    /* White check on blue tile — image set at runtime in KeyValueTable */
}
QTableWidget#kv_table {
    background-color: #1e1e2e;
    alternate-background-color: #181825;
    gridline-color: transparent;
    border: none;
    color: #cdd6f4;
    selection-background-color: #313244;
    selection-color: #cdd6f4;
}

/* ── Table ───────────────────────────────────────────────────────── */
QTableView {
    background-color: #1e1e2e;
    alternate-background-color: #181825;
    gridline-color: #313244;
    border: none;
    color: #cdd6f4;
    selection-background-color: #313244;
    selection-color: #cdd6f4;
}
QTableView::item:selected {
    background-color: #363654;
    color: #cdd6f4;
}

/* ── Filter presets button — drop Qt's extra menu-indicator arrow ── */
QToolButton#filter_presets::menu-indicator {
    image: none;
}

/* ── Grouped traffic tree (View ▸ Group by host) ─────────────────── */
QTreeView {
    background-color: #1e1e2e;
    alternate-background-color: #181825;
    border: none;
    color: #cdd6f4;
    selection-background-color: #313244;
    selection-color: #cdd6f4;
    outline: none;
}
QTreeView::item {
    padding: 2px 0;
}
QTreeView::item:selected {
    background-color: #363654;
    color: #cdd6f4;
}

/* ── Request editor collections (right drawer + rail) ─────────────── */
QWidget#editor_collections_drawer {
    background-color: #181825;
    border-left: 1px solid #313244;
}
QLabel#editor_collections_title {
    color: #a6adc8;
    font-size: 12px;
    font-weight: 600;
}
QWidget#editor_collections_rail {
    background-color: #11111b;
    border-left: 1px solid #313244;
}
QToolButton#editor_collections_toggle,
QToolButton#editor_collections_add {
    background-color: #313244;
    color: #cdd6f4;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
}
QToolButton#editor_collections_toggle:hover,
QToolButton#editor_collections_add:hover {
    background-color: #45475a;
}
QToolButton#editor_collections_toggle:pressed,
QToolButton#editor_collections_add:pressed {
    background-color: #585b70;
}

/* ── Capture-records column (left rail) ──────────────────────────── */
QWidget#traffic_rail {
    background-color: #11111b;
    border-right: 1px solid #313244;
}
QToolButton#traffic_toggle {
    background-color: #313244;
    color: #cdd6f4;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
}
QToolButton#traffic_toggle:hover {
    background-color: #45475a;
}
QToolButton#traffic_toggle:pressed {
    background-color: #585b70;
}
QTreeWidget#editor_collections {
    background-color: #181825;
    border: none;
    color: #cdd6f4;
    outline: none;
    padding: 4px 2px;
    /* macOS draws a light native strip in the branch/indent column when this is on */
    show-decoration-selected: 0;
}
QTreeWidget#editor_collections::branch {
    background: #181825;
    border: none;
    border-image: none;
    image: none;
    width: 0px;
}
QTreeWidget#editor_collections QAbstractScrollArea::viewport {
    background-color: #181825;
}
QTreeWidget#editor_collections QScrollBar:vertical {
    background: #181825;
    width: 8px;
    margin: 0;
}
QTreeWidget#editor_collections QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
    min-height: 24px;
}
QTreeWidget#editor_collections QScrollBar::add-line:vertical,
QTreeWidget#editor_collections QScrollBar::sub-line:vertical,
QTreeWidget#editor_collections QScrollBar::add-page:vertical,
QTreeWidget#editor_collections QScrollBar::sub-page:vertical {
    height: 0;
    background: #181825;
}
QTreeWidget#editor_collections::item {
    padding: 6px 8px;
    margin: 1px 4px;
    border-radius: 6px;
    color: #cdd6f4;
}
QTreeWidget#editor_collections::item:hover {
    background-color: #252539;
}
QTreeWidget#editor_collections::item:selected {
    background-color: #313244;
    color: #cdd6f4;
}
QTreeWidget#editor_collections::item:selected:active {
    background-color: #313244;
}
/* Legacy tree selector (non-editor trees, if any) */
QTreeWidget {
    background-color: #181825;
    border: none;
    color: #cdd6f4;
    outline: none;
    padding: 4px;
}
QTreeWidget::item {
    padding: 5px 4px;
    margin: 1px 4px;
    border-radius: 6px;
}
QTreeWidget::item:hover {
    background-color: #252539;
}
QTreeWidget::item:selected {
    background-color: #45475a;
    color: #cdd6f4;
}
/* Branch column: keep it clean. The disclosure arrows themselves are supplied
   per-widget via real PNGs (see request_editor) because QSS cannot synthesize
   triangles from borders the way web CSS can. */
QTreeWidget::branch {
    background: transparent;
    border-image: none;
    image: none;
}
QHeaderView::section {
    background-color: #181825;
    color: #a6adc8;
    border: none;
    border-right: 1px solid #313244;
    border-bottom: 1px solid #313244;
    padding: 4px 8px;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
QHeaderView::section:hover {
    background-color: #313244;
}

/* ── List (Save-As group picker) ─────────────────────────────────── */
QListWidget {
    background-color: #181825;
    border: 1px solid #313244;
    border-radius: 8px;
    padding: 4px;
    color: #cdd6f4;
    outline: none;
}
QListWidget::item {
    padding: 6px 10px;
    margin: 1px 2px;
    border-radius: 6px;
}
QListWidget::item:hover {
    background-color: #252539;
}
QListWidget::item:selected {
    background-color: #89b4fa;
    color: #11111b;
}
QDialog#group_picker_dialog QLabel {
    color: #a6adc8;
    font-size: 12px;
}
QDialog#group_picker_dialog QListWidget#group_picker_list {
    background-color: #11111b;
    border: 1px solid #313244;
    min-height: 120px;
}
QDialog#text_prompt_dialog QLineEdit {
    background-color: #11111b;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 6px 10px;
    color: #cdd6f4;
    min-height: 28px;
}
QDialog#text_prompt_dialog QLineEdit:focus {
    border-color: #89b4fa;
}

/* ── Splitter ────────────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #313244;
}
QSplitter::handle:horizontal {
    width: 1px;
}
QSplitter::handle:vertical {
    height: 1px;
}

/* ── Tab bar ─────────────────────────────────────────────────────── */
QTabWidget::pane {
    border: none;
    border-top: 1px solid #313244;
}
QTabBar::tab {
    background-color: transparent;
    color: #a6adc8;
    padding: 6px 16px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: #89b4fa;
    border-bottom: 2px solid #89b4fa;
}
QTabBar::tab:hover {
    color: #cdd6f4;
}

/* ── Text Edit ───────────────────────────────────────────────────── */
QTextEdit, QPlainTextEdit {
    background-color: #181825;
    border: none;
    color: #cdd6f4;
    selection-background-color: #45475a;
    font-family: "SF Mono", "Fira Code", "JetBrains Mono", Menlo, monospace;
    font-size: 12px;
    line-height: 1.5;
    padding: 8px;
}

/* ── ScrollBar ───────────────────────────────────────────────────── */
QScrollBar:vertical {
    background-color: #1e1e2e;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background-color: #45475a;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #585b70;
}
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar:horizontal {
    background-color: #1e1e2e;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background-color: #45475a;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #585b70;
}

/* ── StatusBar ───────────────────────────────────────────────────── */
QStatusBar {
    background-color: #181825;
    color: #a6adc8;
    border-top: 1px solid #313244;
    font-size: 11px;
    padding: 2px 8px;
}
QStatusBar::item { border: none; }

/* ── Label ───────────────────────────────────────────────────────── */
QLabel#status_dot {
    color: #a6adc8;
    font-size: 14px;
}

/* ── Separator ───────────────────────────────────────────────────── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {
    color: #313244;
}
"""

# Method badge colors
METHOD_COLORS = {
    "GET":     ("#89b4fa", "#1e3a5f"),   # blue
    "POST":    ("#a6e3a1", "#1a3a22"),   # green
    "PUT":     ("#fab387", "#3a2a14"),   # peach
    "PATCH":   ("#f9e2af", "#3a340a"),   # yellow
    "DELETE":  ("#f38ba8", "#3a1a24"),   # red
    "HEAD":    ("#94e2d5", "#123a36"),   # teal
    "OPTIONS": ("#cba6f7", "#2d1a3a"),   # mauve
    "CONNECT": ("#89dceb", "#0a2a30"),   # sky
}

# Status code colors
def status_color(code) -> str:  # int | None
    if code is None:
        return "#6c7086"
    if code < 300:
        return "#a6e3a1"
    if code < 400:
        return "#f9e2af"
    if code < 500:
        return "#fab387"
    return "#f38ba8"

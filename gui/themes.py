"""
Dark theme stylesheet — Proxyman-inspired.
"""

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
    padding: 2px 0;
}
QMenuBar::item:selected {
    background-color: #313244;
    border-radius: 4px;
}
QMenu {
    background-color: #1e1e2e;
    border: 1px solid #313244;
}
QMenu::item:selected {
    background-color: #45475a;
}

/* ── Toolbar ─────────────────────────────────────────────────────── */
QToolBar {
    background-color: #181825;
    border-bottom: 1px solid #313244;
    padding: 4px 8px;
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
    padding: 4px 12px;
    color: #cdd6f4;
    min-height: 22px;
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

/* ── LineEdit / SpinBox ──────────────────────────────────────────── */
QLineEdit, QSpinBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 3px 8px;
    color: #cdd6f4;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}
QLineEdit:focus, QSpinBox:focus {
    border-color: #89b4fa;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 0;
    border: none;
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

/* ── Tree (JSON) ─────────────────────────────────────────────────── */
QTreeWidget {
    background-color: #181825;
    border: none;
    color: #cdd6f4;
    outline: none;
}
QTreeWidget::item {
    padding: 2px 0;
}
QTreeWidget::item:selected {
    background-color: #313244;
    color: #cdd6f4;
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

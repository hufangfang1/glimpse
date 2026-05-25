"""
Detail panel — shows request / response headers and body for a selected flow.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from typing import Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QRect, QSize
from PyQt6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from proxy.models import FlowModel
from gui.themes import METHOD_COLORS, status_color


# ──────────────────────────────────────────────────────────────────────────────
# Simple JSON syntax highlighter
# ──────────────────────────────────────────────────────────────────────────────

class JsonHighlighter(QSyntaxHighlighter):
    """Very lightweight JSON syntax coloring."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._string_fmt = self._fmt("#a6e3a1")
        self._number_fmt = self._fmt("#fab387")
        self._key_fmt = self._fmt("#89b4fa")
        self._bool_fmt = self._fmt("#cba6f7")
        self._null_fmt = self._fmt("#f38ba8")

    @staticmethod
    def _fmt(color: str) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(QColor(color))
        return f

    def highlightBlock(self, text: str) -> None:
        import re
        # Fold summary comments: // 7 items
        for m in re.finditer(r"//.*$", text):
            fmt = self._fmt("#6c7086")
            self.setFormat(m.start(), m.end() - m.start(), fmt)
        # Keys (strings before colon)
        for m in re.finditer(r'"([^"\\]|\\.)*"\s*:', text):
            self.setFormat(m.start(), m.end() - m.start(), self._key_fmt)
        # String values
        for m in re.finditer(r':\s*("([^"\\]|\\.)*")', text):
            g = m.group(1)
            start = text.index(g, m.start())
            self.setFormat(start, len(g), self._string_fmt)
        # Numbers
        for m in re.finditer(r':\s*(-?\d+\.?\d*([eE][+-]?\d+)?)', text):
            g = m.group(1)
            start = text.index(g, m.start())
            self.setFormat(start, len(g), self._number_fmt)
        # Booleans
        for m in re.finditer(r'\b(true|false)\b', text):
            self.setFormat(m.start(), m.end() - m.start(), self._bool_fmt)
        # Null
        for m in re.finditer(r'\bnull\b', text):
            self.setFormat(m.start(), m.end() - m.start(), self._null_fmt)
        # Collapsed placeholders
        for m in re.finditer(r"\{\.\.\.\}|\[\.\.\.\]", text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt("#cba6f7"))


# ──────────────────────────────────────────────────────────────────────────────
# Small reusable widgets
# ──────────────────────────────────────────────────────────────────────────────

class InfoRow(QWidget):
    """Key–value label pair."""

    def __init__(self, key: str, value: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        key_label = QLabel(key + ":")
        key_label.setFixedWidth(90)
        key_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        key_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._val = QLabel(value)
        self._val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._val.setWordWrap(True)

        layout.addWidget(key_label)
        layout.addWidget(self._val, 1)

    def set_value(self, v: str) -> None:
        self._val.setText(v)

    def set_color(self, color: str) -> None:
        self._val.setStyleSheet(f"color: {color};")


class HeadersView(QTextEdit):
    """Read-only monospace view for HTTP headers."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Menlo, SF Mono, monospace", 11))

    def set_headers(self, headers: dict) -> None:
        lines = [
            f"<span style='color:#89b4fa'>{html.escape(k)}</span>: "
            f"<span style='color:#cdd6f4'>{html.escape(v)}</span>"
            for k, v in headers.items()
        ]
        self.setHtml("<br>".join(lines) or "<i style='color:#6c7086'>— no headers —</i>")


class BodyView(QPlainTextEdit):
    """Read-only monospace view for request/response body with optional JSON highlighting."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._highlighter: Optional[JsonHighlighter] = None

    def set_body(self, text: str, is_json: bool = False) -> None:
        self.setPlainText(text or "— empty body —")
        if is_json:
            if not self._highlighter:
                self._highlighter = JsonHighlighter(self.document())
            else:
                self._highlighter.rehighlight()
        elif self._highlighter:
            self._highlighter.setDocument(None)
            self._highlighter = None


@dataclass
class _FoldRegion:
    start: int
    end: int
    indent: int
    kind: str          # "object" | "array"
    count: int
    prefix: str = ""   # e.g. '"data": ' when brace is on same line as key


class JsonFoldGutter(QWidget):
    """Left gutter with visible fold triangles (▼/▶)."""

    WIDTH = 22

    def __init__(self, editor: "JsonFoldView") -> None:
        super().__init__(editor)
        self._editor = editor
        self.setFixedWidth(self.WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(self.WIDTH, 0)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#11111b"))

        block = self._editor.firstVisibleBlock()
        top = int(self._editor.blockBoundingGeometry(block).translated(self._editor.contentOffset()).top())
        bottom = top + int(self._editor.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line = block.blockNumber()
                source = self._editor.fold_source_at(line)
                if source is not None:
                    collapsed = source in self._editor._collapsed
                    color = QColor("#a6adc8") if collapsed else QColor("#f38ba8")
                    painter.setPen(color)
                    font = painter.font()
                    font.setPointSize(9)
                    painter.setFont(font)
                    y = top + int(self._editor.blockBoundingRect(block).height() * 0.72)
                    painter.drawText(QRect(0, int(top), self.WIDTH, int(self._editor.blockBoundingRect(block).height())),
                                     int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                                     "▶" if collapsed else "▼")
            block = block.next()
            top = bottom
            bottom = top + int(self._editor.blockBoundingRect(block).height())

    def mousePressEvent(self, event) -> None:
        y = event.position().y()
        block = self._editor.firstVisibleBlock()
        top = int(self._editor.blockBoundingGeometry(block).translated(self._editor.contentOffset()).top())
        bottom = top + int(self._editor.blockBoundingRect(block).height())
        while block.isValid():
            if top <= y <= bottom:
                line = block.blockNumber()
                source = self._editor.fold_source_at(line)
                if source is not None:
                    self._editor.toggle_fold(source)
                return
            block = block.next()
            top = bottom
            bottom = top + int(self._editor.blockBoundingRect(block).height())


class JsonFoldView(QPlainTextEdit):
    """JSON text view with gutter fold controls like common online formatters."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setFont(QFont("Menlo, SF Mono, monospace", 11))
        self.setViewportMargins(JsonFoldGutter.WIDTH, 0, 0, 0)

        self._gutter = JsonFoldGutter(self)
        self._highlighter: Optional[JsonHighlighter] = None
        self._all_lines: list[str] = []
        self._regions: Dict[int, _FoldRegion] = {}
        self._collapsed: set[int] = set()
        self._fold_at_line: Dict[int, int] = {}

        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._highlight_current_fold)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        rect = self.contentsRect()
        self._gutter.setGeometry(0, 0, JsonFoldGutter.WIDTH, rect.height())

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(JsonFoldGutter.WIDTH, 0, 0, 0)

    def _update_gutter(self, rect, dy) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def _highlight_current_fold(self) -> None:
        self._gutter.update()

    def load_json(self, text: str) -> bool:
        try:
            data = json.loads(text.strip())
        except json.JSONDecodeError:
            return False

        formatted = json.dumps(data, indent=2, ensure_ascii=False)
        self._all_lines = formatted.splitlines()
        self._regions = self._parse_folds(self._all_lines)
        self._collapsed = set()
        self._refresh()
        if not self._highlighter:
            self._highlighter = JsonHighlighter(self.document())
        else:
            self._highlighter.rehighlight()
        return True

    def fold_source_at(self, display_line: int) -> Optional[int]:
        return self._fold_at_line.get(display_line)

    def toggle_fold(self, source_line: int) -> None:
        old_visible, _ = self._build_visible()

        if source_line in self._collapsed:
            self._collapsed.remove(source_line)
        else:
            self._collapsed.add(source_line)

        new_visible, new_fold = self._build_visible()

        start = 0
        while start < len(old_visible) and start < len(new_visible) and old_visible[start] == new_visible[start]:
            start += 1

        end_old = len(old_visible)
        end_new = len(new_visible)
        while end_old > start and end_new > start and old_visible[end_old - 1] == new_visible[end_new - 1]:
            end_old -= 1
            end_new -= 1

        self._patch_lines(start, end_old, new_visible[start:end_new])
        self._fold_at_line = new_fold
        if self._highlighter:
            self._highlighter.rehighlight()
        self._gutter.update()

    def expand_all(self) -> None:
        self._collapsed.clear()
        self._refresh()
        self._gutter.update()

    def collapse_all(self) -> None:
        self._collapsed = set(self._regions.keys())
        self._refresh()
        self._gutter.update()

    def _build_visible(self) -> tuple[list[str], Dict[int, int]]:
        visible: list[str] = []
        fold_at_line: Dict[int, int] = {}
        i = 0
        while i < len(self._all_lines):
            if i in self._collapsed and i in self._regions:
                visible.append(self._collapsed_text(self._regions[i]))
                fold_at_line[len(visible) - 1] = i
                i = self._regions[i].end + 1
                continue
            visible.append(self._all_lines[i])
            if i in self._regions:
                fold_at_line[len(visible) - 1] = i
            i += 1
        return visible, fold_at_line

    def _patch_lines(self, start: int, end_exclusive: int, new_lines: list[str]) -> None:
        doc = self.document()
        if doc.blockCount() == 0:
            if new_lines:
                cursor = QTextCursor(doc)
                cursor.insertText("\n".join(new_lines))
            return

        start = max(0, min(start, doc.blockCount() - 1))
        end_exclusive = max(start, min(end_exclusive, doc.blockCount()))

        start_block = doc.findBlockByNumber(start)
        cursor = QTextCursor(doc)
        cursor.setPosition(start_block.position())

        if end_exclusive > start:
            end_block = doc.findBlockByNumber(end_exclusive - 1)
            end_pos = end_block.position() + max(0, end_block.length() - 1)
            cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)

        self.blockSignals(True)
        self.setUpdatesEnabled(False)
        try:
            cursor.beginEditBlock()
            cursor.insertText("\n".join(new_lines))
            cursor.endEditBlock()
        finally:
            self.blockSignals(False)
            self.setUpdatesEnabled(True)

    def _set_visible_text(self, text: str) -> None:
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(text)
        cursor.endEditBlock()

    def _refresh(self) -> None:
        visible, self._fold_at_line = self._build_visible()
        self._set_visible_text("\n".join(visible) if visible else "")
        if self._highlighter:
            self._highlighter.rehighlight()

    @staticmethod
    def _collapsed_text(region: _FoldRegion) -> str:
        pad = " " * region.indent
        if region.kind == "object":
            inner = "{...}"
            suffix = f"  // {region.count} keys"
        else:
            inner = "[...]"
            suffix = f"  // {region.count} items"
        if region.prefix:
            return f"{pad}{region.prefix}{inner}{suffix}"
        return f"{pad}{inner}{suffix}"

    @classmethod
    def _parse_folds(cls, lines: list[str]) -> Dict[int, _FoldRegion]:
        regions: Dict[int, _FoldRegion] = {}
        stack: list[tuple[int, str, int, str]] = []

        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if not stripped:
                continue
            indent = len(line) - len(stripped)

            if stripped in ("{", "["):
                stack.append((i, stripped, indent, ""))
                continue

            if stripped.endswith("{") or stripped.endswith("["):
                stack.append((i, stripped[-1], indent, stripped[:-1].rstrip()))
                continue

            if stripped[0] in ("}", "]"):
                if not stack:
                    continue
                start, kind, start_indent, prefix = stack.pop()
                count = cls._count_items(lines, start, i)
                regions[start] = _FoldRegion(
                    start=start,
                    end=i,
                    indent=start_indent,
                    kind="object" if kind == "{" else "array",
                    count=count,
                    prefix=prefix,
                )
        return regions

    @staticmethod
    def _count_items(lines: list[str], start: int, end: int) -> int:
        base_indent = len(lines[start]) - len(lines[start].lstrip())
        child_indent = base_indent + 2
        count = 0
        i = start + 1
        while i < end:
            stripped = lines[i].lstrip()
            if not stripped or stripped[0] in ("}", "]"):
                i += 1
                continue
            indent = len(lines[i]) - len(lines[i].lstrip())
            if indent == child_indent:
                count += 1
                i += 1
                while i < end:
                    s2 = lines[i].lstrip()
                    if not s2:
                        i += 1
                        continue
                    ind2 = len(lines[i]) - len(lines[i].lstrip())
                    if ind2 <= base_indent:
                        break
                    if ind2 == child_indent:
                        break
                    i += 1
            else:
                i += 1
        return count


class BodyFindBar(QWidget):
    """Inline find bar for QPlainTextEdit (⌘F style)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._target: Optional[QPlainTextEdit] = None

        self._input = QLineEdit()
        self._input.setPlaceholderText("Find in body…")
        self._input.returnPressed.connect(self.find_next)
        self._input.textChanged.connect(self._on_text_changed)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #6c7086; font-size: 11px;")
        self._status.setFixedWidth(80)
        self._status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        btn_prev = QPushButton("↑")
        btn_prev.setFixedWidth(28)
        btn_prev.setToolTip("Previous match  (⇧⏎)")
        btn_prev.clicked.connect(self.find_prev)

        btn_next = QPushButton("↓")
        btn_next.setFixedWidth(28)
        btn_next.setToolTip("Next match  (⏎)")
        btn_next.clicked.connect(self.find_next)

        btn_close = QPushButton("✕")
        btn_close.setFixedWidth(28)
        btn_close.setToolTip("Close  (Esc)")
        btn_close.clicked.connect(self.hide)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        layout.addWidget(self._input, 1)
        layout.addWidget(self._status)
        layout.addWidget(btn_prev)
        layout.addWidget(btn_next)
        layout.addWidget(btn_close)

        self.setStyleSheet("background: #181825; border-bottom: 1px solid #313244;")
        self.hide()

    def set_target(self, edit: Optional[QPlainTextEdit]) -> None:
        self._target = edit
        if self.isVisible():
            self._update_status()

    def show_and_focus(self) -> None:
        self.show()
        self._input.setFocus()
        self._input.selectAll()
        self._update_status()

    def find_next(self) -> None:
        self._find(backward=False)

    def find_prev(self) -> None:
        self._find(backward=True)

    def _find(self, *, backward: bool) -> None:
        text = self._input.text()
        if not text or self._target is None:
            return
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if not self._target.find(text, flags):
            # Wrap around to the start/end.
            cursor = self._target.textCursor()
            cursor.movePosition(
                QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start
            )
            self._target.setTextCursor(cursor)
            self._target.find(text, flags)
        self._update_status()

    def _on_text_changed(self, text: str) -> None:
        if not text or self._target is None:
            self._status.setText("")
            return
        # Move cursor to start so the first find lands on the first match.
        cursor = self._target.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self._target.setTextCursor(cursor)
        self._target.find(text)
        self._update_status()

    def _update_status(self) -> None:
        text = self._input.text()
        if not text or self._target is None:
            self._status.setText("")
            return
        haystack = self._target.toPlainText()
        # Count is case-sensitive, matching QPlainTextEdit.find's default.
        count = haystack.count(text)
        self._status.setText(f"{count} match{'es' if count != 1 else ''}")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            if self._target is not None:
                self._target.setFocus()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.find_prev()
            else:
                self.find_next()
            return
        super().keyPressEvent(event)


class BodyPanel(QWidget):
    """Body viewer with collapsible JSON tree and raw text fallback."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._is_json = False

        self._stack = QStackedWidget()
        self._fold = JsonFoldView()
        self._text = BodyView()
        self._stack.addWidget(self._fold)
        self._stack.addWidget(self._text)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        toolbar.setSpacing(6)

        self._btn_tree = QPushButton("Tree")
        self._btn_tree.setCheckable(True)
        self._btn_tree.setChecked(True)
        self._btn_tree.setFixedWidth(56)
        self._btn_tree.clicked.connect(lambda: self._set_mode(tree=True))

        self._btn_raw = QPushButton("Raw")
        self._btn_raw.setCheckable(True)
        self._btn_raw.setFixedWidth(56)
        self._btn_raw.clicked.connect(lambda: self._set_mode(tree=False))

        self._btn_expand = QPushButton("Expand All")
        self._btn_expand.setFixedWidth(88)
        self._btn_expand.clicked.connect(self._fold.expand_all)

        self._btn_collapse = QPushButton("Collapse All")
        self._btn_collapse.setFixedWidth(96)
        self._btn_collapse.clicked.connect(self._fold.collapse_all)

        self._btn_find = QPushButton("🔍 Find")
        self._btn_find.setFixedWidth(76)
        self._btn_find.setToolTip("Find in body  (⌘F)")
        self._btn_find.clicked.connect(self._show_find)

        toolbar.addWidget(self._btn_tree)
        toolbar.addWidget(self._btn_raw)
        toolbar.addSpacing(8)
        toolbar.addWidget(self._btn_expand)
        toolbar.addWidget(self._btn_collapse)
        toolbar.addStretch()
        toolbar.addWidget(self._btn_find)

        self._toolbar = QWidget()
        self._toolbar.setLayout(toolbar)
        self._toolbar.setStyleSheet("background: #181825; border-bottom: 1px solid #313244;")

        self._find_bar = BodyFindBar()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._find_bar)
        layout.addWidget(self._stack, 1)

        # ⌘F anywhere inside the body panel pops the find bar. ApplicationShortcut
        # would be too broad; WidgetWithChildrenShortcut is the right scope.
        find_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        find_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        find_shortcut.activated.connect(self._show_find)

    def set_body(self, text: str, is_json: bool = False) -> None:
        self._is_json = is_json
        self._text.set_body(text, is_json=is_json)

        json_loaded = is_json and self._fold.load_json(text)

        # Tree/Raw/Expand/Collapse only make sense for JSON; Find always available.
        for btn in (self._btn_tree, self._btn_raw, self._btn_expand, self._btn_collapse):
            btn.setVisible(json_loaded)

        self._toolbar.show()
        if json_loaded:
            self._set_mode(tree=True)
        else:
            self._stack.setCurrentWidget(self._text)

        # Hide find bar between flows; user can re-open with ⌘F.
        self._find_bar.hide()
        self._sync_find_target()

    def _set_mode(self, tree: bool) -> None:
        if not self._is_json:
            return
        self._btn_tree.setChecked(tree)
        self._btn_raw.setChecked(not tree)
        self._stack.setCurrentWidget(self._fold if tree else self._text)
        self._sync_find_target()

    def _show_find(self) -> None:
        self._sync_find_target()
        self._find_bar.show_and_focus()

    def _sync_find_target(self) -> None:
        current = self._stack.currentWidget()
        if isinstance(current, QPlainTextEdit):
            self._find_bar.set_target(current)


# ──────────────────────────────────────────────────────────────────────────────
# Tabs
# ──────────────────────────────────────────────────────────────────────────────

class OverviewTab(QWidget):
    replay_requested = pyqtSignal(object)   # emits FlowModel

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._flow: Optional[FlowModel] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)

        self._url = InfoRow("URL")
        self._method = InfoRow("Method")
        self._status = InfoRow("Status")
        self._host = InfoRow("Host")
        self._size = InfoRow("Size")
        self._duration = InfoRow("Duration")
        self._time = InfoRow("Timestamp")
        self._type = InfoRow("Content-Type")

        for w in [self._url, self._method, self._status, self._host,
                  self._size, self._duration, self._time, self._type]:
            layout.addWidget(w)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #313244;")
        layout.addWidget(sep)

        btn_row = QHBoxLayout()
        self._btn_replay = QPushButton("↩ Replay")
        self._btn_replay.setFixedWidth(100)
        self._btn_replay.clicked.connect(self._on_replay)
        btn_row.addWidget(self._btn_replay)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

    def load(self, flow: Optional[FlowModel]) -> None:
        self._flow = flow
        if not flow:
            for w in [self._url, self._method, self._status, self._host,
                      self._size, self._duration, self._time, self._type]:
                w.set_value("")
            return
        self._url.set_value(flow.url)
        self._method.set_value(flow.method)
        c = METHOD_COLORS.get(flow.method, ("#cdd6f4", ""))
        self._method.set_color(c[0])

        sc = flow.status_code
        self._status.set_value(f"{sc} {flow.status_message}" if sc else (flow.error or "-"))
        self._status.set_color(status_color(sc))

        self._host.set_value(flow.host)
        self._size.set_value(flow.format_size())
        self._duration.set_value(flow.format_duration())
        self._time.set_value(flow.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        self._type.set_value(flow.content_type or "-")

    def _on_replay(self) -> None:
        if self._flow:
            self.replay_requested.emit(self._flow)


class RequestTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        splitter = QSplitter(Qt.Orientation.Vertical, self)

        self._headers = HeadersView()
        self._body = BodyPanel()

        splitter.addWidget(self._make_section("Headers", self._headers))
        splitter.addWidget(self._make_section("Body", self._body))
        splitter.setSizes([200, 300])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def load(self, flow: Optional[FlowModel]) -> None:
        if not flow:
            self._headers.set_headers({})
            self._body.set_body("")
            return
        self._headers.set_headers(flow.request_headers)
        text, is_json = flow.get_request_body_display()
        self._body.set_body(text, is_json=is_json)

    @staticmethod
    def _make_section(title: str, widget: QWidget) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        lbl = QLabel(title)
        lbl.setStyleSheet(
            "background: #181825; color: #a6adc8; font-size: 11px; font-weight: 600;"
            "text-transform: uppercase; letter-spacing: 1px; padding: 4px 12px;"
            "border-bottom: 1px solid #313244;"
        )
        vl.addWidget(lbl)
        vl.addWidget(widget)
        return w


class ResponseTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        splitter = QSplitter(Qt.Orientation.Vertical, self)

        self._headers = HeadersView()
        self._body = BodyPanel()

        splitter.addWidget(RequestTab._make_section("Headers", self._headers))
        splitter.addWidget(RequestTab._make_section("Body", self._body))
        splitter.setSizes([200, 300])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def load(self, flow: Optional[FlowModel]) -> None:
        if not flow:
            self._headers.set_headers({})
            self._body.set_body("")
            return
        self._headers.set_headers(flow.response_headers)
        if flow.is_image():
            self._body.set_body(
                f"[Binary image: {flow.content_type}, {flow.format_size()}]",
                is_json=False,
            )
            return
        text, is_json = flow.get_response_body_display()
        self._body.set_body(text, is_json=is_json)


class WebSocketTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        layout.addWidget(self._text)

    def load(self, flow: Optional[FlowModel]) -> None:
        if not flow or not flow.ws_messages:
            self._text.setPlainText("— no WebSocket messages —")
            return
        lines = []
        for msg in flow.ws_messages:
            ts = msg.timestamp.strftime("%H:%M:%S.%f")[:-3]
            lines.append(f"[{ts}] {msg.direction}\n{msg.text}\n")
        self._text.setPlainText("\n".join(lines))


# ──────────────────────────────────────────────────────────────────────────────
# DetailPanel — main composite widget
# ──────────────────────────────────────────────────────────────────────────────

class DetailPanel(QWidget):
    replay_requested = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # placeholder when nothing is selected
        self._placeholder = QLabel("← Select a request to inspect")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #6c7086; font-size: 14px;")

        self._tabs = QTabWidget()
        self._overview = OverviewTab()
        self._request_tab = RequestTab()
        self._response_tab = ResponseTab()
        self._ws_tab = WebSocketTab()

        self._tabs.addTab(self._overview, "Overview")
        self._tabs.addTab(self._request_tab, "Request")
        self._tabs.addTab(self._response_tab, "Response")
        self._tabs.addTab(self._ws_tab, "WebSocket")

        self._overview.replay_requested.connect(self.replay_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._placeholder)
        layout.addWidget(self._tabs)
        self._tabs.hide()

    def load(self, flow: Optional[FlowModel]) -> None:
        if flow is None:
            self._tabs.hide()
            self._placeholder.show()
            return

        self._placeholder.hide()
        self._tabs.show()

        self._overview.load(flow)
        self._request_tab.load(flow)
        self._response_tab.load(flow)

        # Show/hide WebSocket tab
        ws_idx = 3
        if flow.flow_type == "websocket":
            self._ws_tab.load(flow)
            if self._tabs.indexOf(self._ws_tab) == -1:
                self._tabs.addTab(self._ws_tab, "WebSocket")
            self._tabs.setTabVisible(ws_idx, True)
        else:
            self._tabs.setTabVisible(ws_idx, False)

        self._tabs.setCurrentWidget(self._response_tab)

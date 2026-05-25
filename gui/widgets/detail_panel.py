"""
Detail panel — shows request / response headers and body for a selected flow.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from typing import Dict, Optional

from PyQt6.QtCore import Qt, pyqtSignal, QRect, QSize, QEvent
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
from gui.i18n import i18n, tr
from gui.icons import chevron_down, chevron_up, close_x, search_lens
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
    """Key–value label pair driven by an i18n key id."""

    def __init__(self, key_id: str, value: str = "", parent=None) -> None:
        super().__init__(parent)
        self._key_id = key_id

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        self._key_label = QLabel()
        self._key_label.setFixedWidth(90)
        self._key_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        self._key_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._val = QLabel(value)
        self._val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._val.setWordWrap(True)

        layout.addWidget(self._key_label)
        layout.addWidget(self._val, 1)

        self.retranslate()

    def retranslate(self) -> None:
        self._key_label.setText(tr(self._key_id) + ":")

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
        self._headers = dict(headers or {})
        self._render()

    def retranslate(self) -> None:
        if hasattr(self, "_headers"):
            self._render()

    def _render(self) -> None:
        headers = getattr(self, "_headers", {}) or {}
        lines = [
            f"<span style='color:#89b4fa'>{html.escape(k)}</span>: "
            f"<span style='color:#cdd6f4'>{html.escape(v)}</span>"
            for k, v in headers.items()
        ]
        if lines:
            self.setHtml("<br>".join(lines))
        else:
            empty = html.escape(tr("headers.empty"))
            self.setHtml(f"<i style='color:#6c7086'>{empty}</i>")


class SearchablePlainTextEdit(QPlainTextEdit):
    """QPlainTextEdit with visible find highlights via ExtraSelections."""

    _MATCH_BG = QColor("#585b20")       # muted gold — all matches
    _MATCH_FG = QColor("#f9e2af")
    _CURRENT_BG = QColor("#f9e2af")     # bright yellow — active match
    _CURRENT_FG = QColor("#11111b")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._find_query: str = ""
        self._find_index: int = 0
        self._find_spans: list[tuple[int, int]] = []

    def apply_find(self, query: str, *, index: int = 0) -> int:
        """Highlight all *query* matches; *index* selects the active one."""
        self._find_query = query
        self._find_spans = self._collect_spans(query) if query else []
        if self._find_spans:
            self._find_index = index % len(self._find_spans)
        else:
            self._find_index = 0
        self._render_find_highlights()
        return len(self._find_spans)

    def advance_find(self, delta: int) -> None:
        if not self._find_spans:
            return
        self._find_index = (self._find_index + delta) % len(self._find_spans)
        self._render_find_highlights()

    def clear_find(self) -> None:
        self._find_query = ""
        self._find_index = 0
        self._find_spans = []
        self.setExtraSelections([])

    def find_match_count(self) -> int:
        return len(self._find_spans)

    def find_current_index(self) -> int:
        return self._find_index

    def _collect_spans(self, query: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        if not query:
            return spans
        doc = self.document()
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        while True:
            cursor = doc.find(query, cursor)
            if cursor.isNull():
                break
            spans.append((cursor.selectionStart(), cursor.selectionEnd()))
        return spans

    def _render_find_highlights(self) -> None:
        if not self._find_spans:
            self.setExtraSelections([])
            return

        doc = self.document()
        extra: list[QTextEdit.ExtraSelection] = []
        for i, (start, end) in enumerate(self._find_spans):
            sel = QTextEdit.ExtraSelection()
            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cursor
            fmt = QTextCharFormat()
            if i == self._find_index:
                fmt.setBackground(self._CURRENT_BG)
                fmt.setForeground(self._CURRENT_FG)
                fmt.setFontWeight(QFont.Weight.Bold)
            else:
                fmt.setBackground(self._MATCH_BG)
                fmt.setForeground(self._MATCH_FG)
            sel.format = fmt
            extra.append(sel)

        self.setExtraSelections(extra)

        # Scroll the active match into view without using the grey selection color.
        cur_start, cur_end = self._find_spans[self._find_index]
        nav = QTextCursor(doc)
        nav.setPosition(cur_start)
        nav.setPosition(cur_end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(nav)
        self.ensureCursorVisible()
        nav.clearSelection()
        nav.setPosition(cur_end)
        self.setTextCursor(nav)


class BodyView(SearchablePlainTextEdit):
    """Read-only monospace view for request/response body with optional JSON highlighting."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._highlighter: Optional[JsonHighlighter] = None
        # Remember the last body so we can re-render the empty placeholder on
        # language switches without losing the actual content.
        self._raw_text: str = ""
        self._is_json: bool = False

    def set_body(self, text: str, is_json: bool = False) -> None:
        self._raw_text = text or ""
        self._is_json = is_json
        self.setPlainText(self._raw_text or tr("body.empty"))
        if is_json:
            if not self._highlighter:
                self._highlighter = JsonHighlighter(self.document())
            else:
                self._highlighter.rehighlight()
        elif self._highlighter:
            self._highlighter.setDocument(None)
            self._highlighter = None

    def retranslate(self) -> None:
        if not self._raw_text:
            self.setPlainText(tr("body.empty"))


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


class JsonFoldView(SearchablePlainTextEdit):
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

    _BTN = 26
    _CLOSE = 28

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("find_bar")
        self._target: Optional[QPlainTextEdit] = None

        # Search field — icon + input inside a rounded capsule.
        self._field = QWidget()
        self._field.setObjectName("find_field")
        field_layout = QHBoxLayout(self._field)
        field_layout.setContentsMargins(0, 0, 8, 0)
        field_layout.setSpacing(0)

        self._icon = QLabel()
        self._icon.setObjectName("find_icon")
        self._icon.setPixmap(search_lens().pixmap(QSize(16, 16)))

        self._input = QLineEdit()
        self._input.setObjectName("find_input")
        self._input.returnPressed.connect(self.find_next)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.installEventFilter(self)

        field_layout.addWidget(self._icon)
        field_layout.addWidget(self._input, 1)

        self._status = QLabel("")
        self._status.setObjectName("find_status")
        self._status.setFixedWidth(96)
        self._status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Prev / next as a compact segmented control.
        self._nav_group = QWidget()
        self._nav_group.setObjectName("find_nav_group")
        nav_layout = QHBoxLayout(self._nav_group)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        self._btn_prev = QPushButton()
        self._btn_prev.setObjectName("find_nav_btn")
        self._btn_prev.setFixedSize(self._BTN, self._BTN)
        self._btn_prev.setIcon(chevron_up())
        self._btn_prev.setIconSize(QSize(12, 12))
        self._btn_prev.clicked.connect(self.find_prev)

        self._btn_next = QPushButton()
        self._btn_next.setObjectName("find_nav_btn")
        self._btn_next.setFixedSize(self._BTN, self._BTN)
        self._btn_next.setIcon(chevron_down())
        self._btn_next.setIconSize(QSize(12, 12))
        self._btn_next.clicked.connect(self.find_next)

        nav_layout.addWidget(self._btn_prev)
        nav_layout.addWidget(self._btn_next)

        self._btn_close = QPushButton()
        self._btn_close.setObjectName("find_close_btn")
        self._btn_close.setFixedSize(self._CLOSE, self._CLOSE)
        self._btn_close.setIcon(close_x())
        self._btn_close.setIconSize(QSize(12, 12))
        self._btn_close.clicked.connect(self.hide)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        layout.addWidget(self._field, 1)
        layout.addWidget(self._status)
        layout.addWidget(self._nav_group)
        layout.addWidget(self._btn_close)

        self.hide()
        self.retranslate()

    def retranslate(self) -> None:
        self._input.setPlaceholderText(tr("find.placeholder"))
        self._btn_prev.setToolTip(tr("find.prev.tooltip"))
        self._btn_next.setToolTip(tr("find.next.tooltip"))
        self._btn_close.setToolTip(tr("find.close.tooltip"))
        self._update_status()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._input:
            if event.type() == QEvent.Type.FocusIn:
                self._field.setProperty("focused", True)
            elif event.type() == QEvent.Type.FocusOut:
                self._field.setProperty("focused", False)
            if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
                self._field.style().unpolish(self._field)
                self._field.style().polish(self._field)
        return super().eventFilter(obj, event)

    def set_target(self, edit: Optional[QPlainTextEdit]) -> None:
        if self._target is not None and hasattr(self._target, "clear_find"):
            self._target.clear_find()
        self._target = edit
        if self.isVisible() and self._input.text():
            self._refresh_find(index=0)
        self._update_status()

    def show_and_focus(self) -> None:
        self.show()
        self._input.setFocus()
        self._input.selectAll()
        if self._input.text():
            self._refresh_find(index=0)
        self._update_status()

    def hide(self) -> None:
        if self._target is not None and hasattr(self._target, "clear_find"):
            self._target.clear_find()
        super().hide()

    def find_next(self) -> None:
        if self._target is not None and hasattr(self._target, "advance_find"):
            self._target.advance_find(1)
        else:
            self._find(backward=False)
        self._update_status()

    def find_prev(self) -> None:
        if self._target is not None and hasattr(self._target, "advance_find"):
            self._target.advance_find(-1)
        else:
            self._find(backward=True)
        self._update_status()

    def _refresh_find(self, *, index: int = 0) -> None:
        text = self._input.text()
        if not text or self._target is None:
            if self._target is not None and hasattr(self._target, "clear_find"):
                self._target.clear_find()
            return
        if hasattr(self._target, "apply_find"):
            self._target.apply_find(text, index=index)

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

    def _on_text_changed(self, text: str) -> None:
        if not text or self._target is None:
            if self._target is not None and hasattr(self._target, "clear_find"):
                self._target.clear_find()
            self._status.setText("")
            return
        self._refresh_find(index=0)
        self._update_status()

    def _update_status(self) -> None:
        text = self._input.text()
        if not text or self._target is None:
            self._status.setText("")
            return
        if hasattr(self._target, "find_match_count"):
            count = self._target.find_match_count()
            if count == 0:
                self._status.setText(tr("find.matches", n=0))
            elif count == 1:
                self._status.setText(tr("find.matches.one"))
            else:
                cur = self._target.find_current_index() + 1
                self._status.setText(tr("find.matches.pos", cur=cur, total=count))
            return
        haystack = self._target.toPlainText()
        count = haystack.count(text)
        if count == 1:
            self._status.setText(tr("find.matches.one"))
        else:
            self._status.setText(tr("find.matches", n=count))

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

        self._btn_tree = QPushButton()
        self._btn_tree.setCheckable(True)
        self._btn_tree.setChecked(True)
        self._btn_tree.setFixedWidth(64)
        self._btn_tree.clicked.connect(lambda: self._set_mode(tree=True))

        self._btn_raw = QPushButton()
        self._btn_raw.setCheckable(True)
        self._btn_raw.setFixedWidth(64)
        self._btn_raw.clicked.connect(lambda: self._set_mode(tree=False))

        self._btn_expand = QPushButton()
        self._btn_expand.setFixedWidth(96)
        self._btn_expand.clicked.connect(self._fold.expand_all)

        self._btn_collapse = QPushButton()
        self._btn_collapse.setFixedWidth(96)
        self._btn_collapse.clicked.connect(self._fold.collapse_all)

        self._btn_find = QPushButton()
        self._btn_find.setFixedWidth(84)
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

        self.retranslate()

    def retranslate(self) -> None:
        self._btn_tree.setText(tr("body.tree"))
        self._btn_raw.setText(tr("body.raw"))
        self._btn_expand.setText(tr("body.expand_all"))
        self._btn_collapse.setText(tr("body.collapse_all"))
        self._btn_find.setText(tr("body.find"))
        self._btn_find.setToolTip(tr("body.find.tooltip"))
        self._text.retranslate()
        self._find_bar.retranslate()

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

        self._url = InfoRow("overview.url")
        self._method = InfoRow("overview.method")
        self._status = InfoRow("overview.status")
        self._host = InfoRow("overview.host")
        self._size = InfoRow("overview.size")
        self._duration = InfoRow("overview.duration")
        self._time = InfoRow("overview.timestamp")
        self._type = InfoRow("overview.content_type")

        self._rows = [
            self._url, self._method, self._status, self._host,
            self._size, self._duration, self._time, self._type,
        ]
        for w in self._rows:
            layout.addWidget(w)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #313244;")
        layout.addWidget(sep)

        btn_row = QHBoxLayout()
        self._btn_replay = QPushButton()
        self._btn_replay.setFixedWidth(100)
        self._btn_replay.clicked.connect(self._on_replay)
        btn_row.addWidget(self._btn_replay)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

        self.retranslate()

    def retranslate(self) -> None:
        for row in self._rows:
            row.retranslate()
        self._btn_replay.setText(tr("overview.replay"))

    def load(self, flow: Optional[FlowModel]) -> None:
        self._flow = flow
        if not flow:
            for w in self._rows:
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


def _make_section(title_key: str, widget: QWidget) -> tuple[QWidget, QLabel]:
    """Wrap *widget* with a colored section header label.

    Returns the wrapper *and* the label so callers can refresh the label
    text on language changes.
    """
    w = QWidget()
    vl = QVBoxLayout(w)
    vl.setContentsMargins(0, 0, 0, 0)
    vl.setSpacing(0)
    lbl = QLabel(tr(title_key))
    lbl.setProperty("i18n_key", title_key)
    lbl.setStyleSheet(
        "background: #181825; color: #a6adc8; font-size: 11px; font-weight: 600;"
        "text-transform: uppercase; letter-spacing: 1px; padding: 4px 12px;"
        "border-bottom: 1px solid #313244;"
    )
    vl.addWidget(lbl)
    vl.addWidget(widget)
    return w, lbl


class RequestTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        splitter = QSplitter(Qt.Orientation.Vertical, self)

        self._headers = HeadersView()
        self._body = BodyPanel()

        headers_section, self._headers_label = _make_section("section.headers", self._headers)
        body_section, self._body_label = _make_section("section.body", self._body)
        splitter.addWidget(headers_section)
        splitter.addWidget(body_section)
        splitter.setSizes([200, 300])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def retranslate(self) -> None:
        self._headers_label.setText(tr("section.headers"))
        self._body_label.setText(tr("section.body"))
        self._headers.retranslate()
        self._body.retranslate()

    def load(self, flow: Optional[FlowModel]) -> None:
        if not flow:
            self._headers.set_headers({})
            self._body.set_body("")
            return
        self._headers.set_headers(flow.request_headers)
        text, is_json = flow.get_request_body_display()
        self._body.set_body(text, is_json=is_json)


class ResponseTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        splitter = QSplitter(Qt.Orientation.Vertical, self)

        self._headers = HeadersView()
        self._body = BodyPanel()
        self._flow: Optional[FlowModel] = None

        headers_section, self._headers_label = _make_section("section.headers", self._headers)
        body_section, self._body_label = _make_section("section.body", self._body)
        splitter.addWidget(headers_section)
        splitter.addWidget(body_section)
        splitter.setSizes([200, 300])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def retranslate(self) -> None:
        self._headers_label.setText(tr("section.headers"))
        self._body_label.setText(tr("section.body"))
        self._headers.retranslate()
        self._body.retranslate()
        # Re-render binary-image placeholder in the new language.
        if self._flow is not None and self._flow.is_image():
            self._render_image_placeholder(self._flow)

    def load(self, flow: Optional[FlowModel]) -> None:
        self._flow = flow
        if not flow:
            self._headers.set_headers({})
            self._body.set_body("")
            return
        self._headers.set_headers(flow.response_headers)
        if flow.is_image():
            self._render_image_placeholder(flow)
            return
        text, is_json = flow.get_response_body_display()
        self._body.set_body(text, is_json=is_json)

    def _render_image_placeholder(self, flow: FlowModel) -> None:
        self._body.set_body(
            tr("body.binary_image", ctype=flow.content_type or "?", size=flow.format_size()),
            is_json=False,
        )


class WebSocketTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        layout.addWidget(self._text)
        self._flow: Optional[FlowModel] = None

    def retranslate(self) -> None:
        # Re-render so the empty placeholder picks up the new language.
        self.load(self._flow)

    def load(self, flow: Optional[FlowModel]) -> None:
        self._flow = flow
        if not flow or not flow.ws_messages:
            self._text.setPlainText(tr("ws.empty"))
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
        self._placeholder = QLabel()
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #6c7086; font-size: 14px;")

        self._tabs = QTabWidget()
        self._overview = OverviewTab()
        self._request_tab = RequestTab()
        self._response_tab = ResponseTab()
        self._ws_tab = WebSocketTab()

        self._tabs.addTab(self._overview, "")
        self._tabs.addTab(self._request_tab, "")
        self._tabs.addTab(self._response_tab, "")
        self._tabs.addTab(self._ws_tab, "")

        self._overview.replay_requested.connect(self.replay_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._placeholder)
        layout.addWidget(self._tabs)
        self._tabs.hide()

        self.retranslate()
        i18n.language_changed.connect(self._on_language_changed)

    def _on_language_changed(self, _lang: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        self._placeholder.setText(tr("detail.placeholder"))
        self._tabs.setTabText(self._tabs.indexOf(self._overview), tr("detail.tab.overview"))
        self._tabs.setTabText(self._tabs.indexOf(self._request_tab), tr("detail.tab.request"))
        self._tabs.setTabText(self._tabs.indexOf(self._response_tab), tr("detail.tab.response"))
        self._tabs.setTabText(self._tabs.indexOf(self._ws_tab), tr("detail.tab.websocket"))
        self._overview.retranslate()
        self._request_tab.retranslate()
        self._response_tab.retranslate()
        self._ws_tab.retranslate()

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
        ws_idx = self._tabs.indexOf(self._ws_tab)
        if flow.flow_type == "websocket":
            self._ws_tab.load(flow)
            self._tabs.setTabVisible(ws_idx, True)
        else:
            self._tabs.setTabVisible(ws_idx, False)

        self._tabs.setCurrentWidget(self._response_tab)

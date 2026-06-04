"""
Small programmatic icons for compact UI controls (find bar, menu chevrons).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


def _draw_icon(size: int, draw) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    draw(painter, size)
    painter.end()
    icon = QIcon()
    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
    return icon


def chevron_up(color: str = "#cdd6f4", size: int = 14) -> QIcon:
    c = QColor(color)

    def draw(p: QPainter, s: int) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        w, h = s * 0.52, s * 0.36
        x = (s - w) / 2
        y = (s - h) / 2 + 0.5
        points = [
            (x, y + h),
            (x + w / 2, y),
            (x + w, y + h),
        ]
        from PyQt6.QtGui import QPolygonF
        from PyQt6.QtCore import QPointF
        poly = QPolygonF([QPointF(px, py) for px, py in points])
        p.drawPolygon(poly)

    return _draw_icon(size, draw)


def chevron_down(color: str = "#cdd6f4", size: int = 14) -> QIcon:
    c = QColor(color)

    def draw(p: QPainter, s: int) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        w, h = s * 0.52, s * 0.36
        x = (s - w) / 2
        y = (s - h) / 2 - 0.5
        points = [
            (x, y),
            (x + w / 2, y + h),
            (x + w, y),
        ]
        from PyQt6.QtGui import QPolygonF
        from PyQt6.QtCore import QPointF
        poly = QPolygonF([QPointF(px, py) for px, py in points])
        p.drawPolygon(poly)

    return _draw_icon(size, draw)


def chevron_right(color: str = "#a6adc8", size: int = 12) -> QIcon:
    c = QColor(color)

    def draw(p: QPainter, s: int) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        w, h = s * 0.36, s * 0.52
        x = (s - w) / 2 + 0.5
        y = (s - h) / 2
        points = [
            (x, y),
            (x + w, y + h / 2),
            (x, y + h),
        ]
        from PyQt6.QtGui import QPolygonF
        from PyQt6.QtCore import QPointF
        poly = QPolygonF([QPointF(px, py) for px, py in points])
        p.drawPolygon(poly)

    return _draw_icon(size, draw)


def close_x(color: str = "#a6adc8", size: int = 14) -> QIcon:
    c = QColor(color)

    def draw(p: QPainter, s: int) -> None:
        pen = QPen(c, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        pad = int(s * 0.28)
        p.drawLine(pad, pad, s - pad, s - pad)
        p.drawLine(s - pad, pad, pad, s - pad)

    return _draw_icon(size, draw)


def search_lens(color: str = "#6c7086", size: int = 16) -> QIcon:
    c = QColor(color)

    def draw(p: QPainter, s: int) -> None:
        pen = QPen(c, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = s * 0.34
        cx, cy = s * 0.42, s * 0.42
        p.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))
        p.drawLine(int(cx + r * 0.65), int(cy + r * 0.65), int(s * 0.78), int(s * 0.78))

    return _draw_icon(size, draw)


def folder(color: str = "#89b4fa", size: int = 16) -> QIcon:
    """A small filled folder glyph for collection groups."""
    c = QColor(color)

    def draw(p: QPainter, s: int) -> None:
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QPainterPath
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)

        left = s * 0.12
        right = s * 0.88
        top = s * 0.26
        bottom = s * 0.78
        tab_w = (right - left) * 0.42
        radius = s * 0.07

        # Folder tab (back flap).
        tab = QPainterPath()
        tab.addRoundedRect(QRectF(left, top - s * 0.08, tab_w, s * 0.18), radius, radius)
        p.drawPath(tab)

        # Folder body.
        body = QPainterPath()
        body.addRoundedRect(QRectF(left, top, right - left, bottom - top), radius, radius)
        p.drawPath(body)

    return _draw_icon(size, draw)


def group_icon(expanded: bool, arrow_color: str = "#9399b2",
               folder_color: str = "#89b4fa", size: int = 22) -> QIcon:
    """A combined 'disclosure arrow + folder' glyph for collection groups.

    We draw the arrow ourselves (left) and a folder (right) into one icon so
    the tree needs no native branch indicators at all — which sidesteps the
    macOS selection-highlight square that QSS can't suppress on ::branch.
    """
    arrow = QColor(arrow_color)
    fold = QColor(folder_color)

    def draw(p: QPainter, s: int) -> None:
        from PyQt6.QtCore import QPointF, QRectF
        from PyQt6.QtGui import QPainterPath, QPolygonF

        # Arrow on the left.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(arrow)
        if expanded:
            w, h = s * 0.28, s * 0.18
            x = s * 0.04
            y = s * 0.40
            pts = [(x, y), (x + w, y), (x + w / 2, y + h)]
        else:
            w, h = s * 0.18, s * 0.28
            x = s * 0.08
            y = s * 0.36
            pts = [(x, y), (x + w, y + h / 2), (x, y + h)]
        p.drawPolygon(QPolygonF([QPointF(px, py) for px, py in pts]))

        # Folder on the right.
        p.setBrush(fold)
        fl = s * 0.40
        fr = s * 0.94
        ft = s * 0.30
        fb = s * 0.74
        radius = s * 0.06
        tab = QPainterPath()
        tab.addRoundedRect(QRectF(fl, ft - s * 0.07, (fr - fl) * 0.42, s * 0.16), radius, radius)
        p.drawPath(tab)
        body2 = QPainterPath()
        body2.addRoundedRect(QRectF(fl, ft, fr - fl, fb - ft), radius, radius)
        p.drawPath(body2)

    return _draw_icon(size, draw)


def file_doc(color: str = "#a6adc8", size: int = 14) -> QIcon:
    """A small document glyph for saved requests."""
    c = QColor(color)

    def draw(p: QPainter, s: int) -> None:
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QPainterPath
        pen = QPen(c, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        left = s * 0.26
        right = s * 0.74
        top = s * 0.16
        bottom = s * 0.84
        path = QPainterPath()
        path.addRoundedRect(QRectF(left, top, right - left, bottom - top), s * 0.06, s * 0.06)
        p.drawPath(path)
        # Two text lines.
        p.drawLine(int(left + s * 0.1), int(s * 0.42), int(right - s * 0.1), int(s * 0.42))
        p.drawLine(int(left + s * 0.1), int(s * 0.58), int(right - s * 0.1), int(s * 0.58))

    return _draw_icon(size, draw)


def _draw_pixmap(size: int, draw) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    draw(painter, size)
    painter.end()
    return pixmap


def _chevron_pixmap(direction: str, color: str, size: int) -> QPixmap:
    c = QColor(color)

    def draw(p: QPainter, s: int) -> None:
        from PyQt6.QtCore import QPointF
        from PyQt6.QtGui import QPolygonF
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        if direction == "right":
            w, h = s * 0.30, s * 0.46
            x = (s - w) / 2 + 0.5
            y = (s - h) / 2
            pts = [(x, y), (x + w, y + h / 2), (x, y + h)]
        else:  # down
            w, h = s * 0.46, s * 0.30
            x = (s - w) / 2
            y = (s - h) / 2 + 0.5
            pts = [(x, y), (x + w, y), (x + w / 2, y + h)]
        p.drawPolygon(QPolygonF([QPointF(px, py) for px, py in pts]))

    return _draw_pixmap(size, draw)


def ensure_tree_branch_icons() -> dict[str, str]:
    """Render small chevron PNGs used by the tree branches and combo arrow.

    QSS can't synthesize triangles from borders the way web CSS can, and a
    border-only rule renders as an ugly solid square. Qt styles these parts
    with real images instead, so we cache a few small PNGs under ~/.glimpse and
    hand their paths to the stylesheet via ``image: url(...)``. Paths are
    forward-slashed for QSS.

    Returns keys: ``closed`` (right), ``open`` (down), ``combo`` (down).
    """
    from pathlib import Path

    cache_dir = Path.home() / ".glimpse" / "icons"
    cache_dir.mkdir(parents=True, exist_ok=True)

    specs = {
        "closed": ("right", "#9399b2", 18),
        "open": ("down", "#bac2de", 18),
        "combo": ("down", "#a6adc8", 14),
    }
    paths: dict[str, str] = {}
    for name, (direction, color, size) in specs.items():
        path = cache_dir / f"{name}.png"
        # Re-render each launch — cheap, and survives palette tweaks.
        _chevron_pixmap(direction, color, size).save(str(path), "PNG")
        paths[name] = str(path).replace("\\", "/")
    return paths


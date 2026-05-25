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
        pad = s * 0.28
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

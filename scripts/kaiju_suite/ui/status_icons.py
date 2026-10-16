"""Small status icons drawn with QPainter: a check, a cross and a pause sign,
as coloured lines on a clear background (Builder's status column).

Each icon is drawn at several sizes, so it stays sharp under Maya's UI scaling.
Shapes are laid out on a 16x16 grid and scaled to the size drawn."""

from PySide6 import QtCore, QtGui

SIZES = (16, 20, 24, 32, 48, 64)
STROKE = 2.0

CHECK = ((3.4, 8.4), (6.7, 11.2), (12.8, 4.4))
CROSS = (((4.4, 4.4), (11.6, 11.6)), ((11.6, 4.4), (4.4, 11.6)))
# Two bars, each (x, y, width, height).
PAUSE = ((4.1, 3.8, 2.3, 8.4), (9.6, 3.8, 2.3, 8.4))


def _icon(color, draw):
    icon = QtGui.QIcon()
    for size in SIZES:
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.scale(size / 16.0, size / 16.0)
        draw(painter, QtGui.QColor(color))
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def _pen(color):
    pen = QtGui.QPen(color, STROKE)
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    return pen


def check(color):
    """A ``QIcon`` of a check mark in ``color``."""

    def draw(painter, color):
        painter.setPen(_pen(color))
        painter.drawPolyline([QtCore.QPointF(x, y) for x, y in CHECK])

    return _icon(color, draw)


def cross(color):
    """A ``QIcon`` of a cross in ``color``."""

    def draw(painter, color):
        painter.setPen(_pen(color))
        for (x1, y1), (x2, y2) in CROSS:
            painter.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))

    return _icon(color, draw)


def pause(color):
    """A ``QIcon`` of a pause sign (two bars) in ``color``."""

    def draw(painter, color):
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for x, y, w, h in PAUSE:
            painter.drawRoundedRect(QtCore.QRectF(x, y, w, h), 0.5, 0.5)

    return _icon(color, draw)

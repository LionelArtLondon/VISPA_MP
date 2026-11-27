"""Independent status and selection outlines shared by the two review views."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from vispa_mp.ui_tokens import ACCENT, APP_BG


STATUS_WIDTH = 3
SELECTION_WIDTH = 2
FRAME_INSET = 5
SELECTION_COLOUR = "#FFFFFF"
STATUS_COLOURS = {
    "Green": "#3c8c4a", "Blue": "#2f6fed", "Cyan": "#3ec2d6", "manual": "#8AA0A8",
}


def paint_review_frame(painter, rect, status_color, *, selected=False, preview=False, kept=False):
    """Keep the role colour inside a dark gap, with selection outside it."""
    box = QRectF(rect)
    if box.width() < 2 or box.height() < 2:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # A dark surround also separates the white outline from pale image content
    # and from the Board's paper. It is present in both selection states.
    painter.setPen(QPen(QColor(APP_BG), 6))
    painter.drawRect(box.adjusted(3, 3, -3, -3))
    inset = min(FRAME_INSET + 0.5, max(1.5, (min(box.width(), box.height()) - STATUS_WIDTH) / 2))
    status = box.adjusted(inset, inset, -inset, -inset)
    painter.setPen(QPen(QColor(status_color), STATUS_WIDTH))
    painter.drawRect(status)
    if selected or kept:
        width = SELECTION_WIDTH + int(kept)
        painter.setPen(QPen(QColor(SELECTION_COLOUR), width))
        painter.drawRect(box.adjusted(1.5, 1.5, -1.5, -1.5))
    if preview and status.width() > 8 and status.height() > 8:
        painter.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
        painter.drawRect(status.adjusted(4, 4, -4, -4))
    painter.restore()

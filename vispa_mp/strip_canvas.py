"""A fixed arrangement of review cards, viewed like a physical board."""

from functools import lru_cache

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from vispa_mp.preview import draw_preview, frame_ratio
from vispa_mp.ui_tokens import PANEL_BG


def balanced_columns(count, width, height, card_width=204, card_height=168, gap=8):
    """Prefer complete rows when they stay close to the most readable arrangement."""
    candidates = []
    for columns in range(1, max(1, count) + 1):
        rows = (count + columns - 1) // columns
        scale = min(max(1, width) / (columns * card_width + (columns - 1) * gap),
                    max(1, height) / max(1, rows * card_height + (rows - 1) * gap))
        candidates.append((scale, -rows, columns))
    best = max(candidates)
    complete = [candidate for candidate in candidates
                if count % candidate[2] == 0 and min(1.0, candidate[0]) >= min(1.0, best[0]) * 0.85]
    return max(complete or candidates)[2]


@lru_cache(maxsize=96)
def _source_pixmap(path):
    return QPixmap(path) if path else QPixmap()


class CanvasImage(QWidget):
    """Paint the source still at the view's resolution, including while zoomed."""

    def set_source(self, path, fallback):
        self.picture = _source_pixmap(path)
        self.fallback = QColor(fallback)
        self.update()

    def set_frame_format(self, format_name, custom_width=16, custom_height=9):
        self.frame_format = format_name
        self.frame_ratio = frame_ratio(format_name, custom_width, custom_height)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        picture = getattr(self, "picture", None)
        draw_preview(painter, picture, self.rect(), getattr(self, "fallback", QColor(PANEL_BG)),
                     crop=getattr(self, "frame_ratio", None) is not None)


class StripCanvasView(QGraphicsView):
    """A scene keeps card positions fixed; only the viewing transform changes."""

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundBrush(QColor(PANEL_BG))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._canvas = None
        self._content = QRectF()

    def setWidget(self, widget):
        self._canvas = widget
        self._proxy = self.scene().addWidget(widget)

    def widget(self):
        return self._canvas

    def set_content_size(self, width, height):
        content = QRectF(0, 0, width, height)
        if content == self._content:
            return
        self._content = content
        self._canvas.setFixedSize(int(width), int(height))
        # Room around the board permits pointer-anchored zoom and free panning,
        # even while the complete arrangement is smaller than the viewport.
        self.setSceneRect(content.adjusted(-10000, -10000, 10000, 10000))

    def set_scale(self, scale, anchor=None):
        point = anchor.toPoint() if isinstance(anchor, QPointF) else anchor
        before = self.mapToScene(point) if point is not None else None
        padding = max(10000, self.viewport().width() / scale * 2, self.viewport().height() / scale * 2)
        self.setSceneRect(self._content.adjusted(-padding, -padding, padding, padding))
        self.setTransform(QTransform.fromScale(scale, scale))
        if before is None:
            self.centerOn(self._content.center())
        else:
            after = self.mapToScene(point)
            centre = self.mapToScene(self.viewport().rect().center())
            self.centerOn(centre + before - after)

    def ensureWidgetVisible(self, widget):
        origin = widget.mapTo(self._canvas, QPoint(0, 0))
        self.ensureVisible(QRectF(origin.x(), origin.y(), widget.width(), widget.height()), 12, 12)

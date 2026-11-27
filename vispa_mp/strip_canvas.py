"""A fixed arrangement of review cards, viewed like a physical board."""

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from vispa_mp.preview import draw_preview, frame_ratio
from vispa_mp.preview_quality import PixmapCache, normalized_quality
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


_sources = PixmapCache()


def _source_pixmap(path):
    if not path:
        return QPixmap()
    cached = _sources.get(path)
    return cached if cached is not None else _sources.put(path, QPixmap(path))


class CanvasImage(QWidget):
    """Paint the source still at the view's resolution, including while zoomed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.preview_quality = "Medium"
        self._source_path = ""

    @property
    def picture(self):
        return _source_pixmap(getattr(self, "_source_path", ""))

    def set_source(self, path, fallback):
        self._source_path = path
        self.fallback = QColor(fallback)
        self.update()

    def set_preview_quality(self, quality):
        self.preview_quality = normalized_quality(quality)
        self.update()

    def set_frame_format(self, format_name, custom_width=16, custom_height=9):
        self.frame_format = format_name
        self.frame_ratio = frame_ratio(format_name, custom_width, custom_height)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        quality = getattr(self, "preview_quality", "Medium")
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, quality != "Low")
        picture = getattr(self, "picture", None)
        draw_preview(painter, picture, self.rect(), getattr(self, "fallback", QColor(PANEL_BG)),
                     crop=getattr(self, "frame_ratio", None) is not None, quality=quality)


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
        self.preview_quality = "Medium"
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._canvas = None
        self._content = QRectF()

    def set_preview_quality(self, quality):
        self.preview_quality = normalized_quality(quality)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.preview_quality != "Low")
        if self._canvas is not None:
            for picture in self._canvas.findChildren(CanvasImage):
                picture.set_preview_quality(self.preview_quality)
        self.viewport().update()

    def setWidget(self, widget):
        self._canvas = widget
        self._proxy = self.scene().addWidget(widget)
        self.set_preview_quality(getattr(self, "preview_quality", "Medium"))

    def widget(self):
        return self._canvas

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        # QGraphicsView scrolls viewport child widgets too; keep HUDs fixed.
        for widget in self.viewport().children():
            if isinstance(widget, QWidget) and widget.property("canvasOverlay"):
                widget.move(10, 10)
                widget.raise_()

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

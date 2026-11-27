"""A navigable timeline ruler whose view is independent of its playhead."""

from copy import deepcopy
import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygon
from PySide6.QtWidgets import QWidget

from vispa_mp.review_selection_style import STATUS_COLOURS
from vispa_mp.timebase import format_timecode
from vispa_mp.ui_tokens import APP_BG, BORDER_ROW, MONO_FAMILY, PANEL_BG, PLAYHEAD, TEXT_MUTED, TEXT_SECONDARY


class TimelineRuler(QWidget):
    """Page bands, marker pins and a playhead over a bounded, zoomable view.

    ``start`` and ``end`` are the complete source range, with an exclusive end.
    Navigation changes only ``view_start`` and ``view_end``; it neither selects
    marker proposals nor moves Resolve's playhead.
    """

    moved = Signal(int)
    chosen = Signal(int)
    context_requested = Signal(int, QPoint)
    PAD = 12
    PIN_REACH = 5
    HEIGHT = 94

    def __init__(self, parent=None):
        super().__init__(parent)
        self.start, self.end = 0, 1
        self.view_start, self.view_end = 0.0, 1.0
        self.markers, self.pages = [], []
        self.playhead = self.timebase = None
        self.compact = False
        self._source = None
        self._drag = False
        self._pan = None
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        self.setToolTip("Wheel: zoom · Middle-drag: pan · Double middle-click: fit · "
                        "Click or drag: playhead · Click a pin: select · Right-click: actions")

    def set_compact(self, compact):
        # Both workspaces keep readable timecodes and the same airy track.
        self.compact = bool(compact)
        self.update()

    def set_view(self, start, end, markers, playhead, timebase, pages=(), *, source_key=None):
        first, last = int(start), max(int(end), int(start) + 1)
        source = first, last, deepcopy(timebase), deepcopy(source_key)
        changed = source != self._source
        self.start, self.end = first, last
        self.markers = [(int(frame), color) for frame, color in markers]
        self.pages = [(int(first), int(last)) for first, last in pages]
        self.playhead = None if playhead is None else int(playhead)
        self.timebase = deepcopy(timebase)
        self._source = source
        if changed:
            self.fit_timeline()
        else:
            self.update()

    def set_playhead(self, frame):
        self.playhead = None if frame is None else int(frame)
        self.update()

    def fit_timeline(self):
        self.view_start, self.view_end = float(self.start), float(self.end)
        self._drag = False
        self._pan = None
        self.unsetCursor()
        self.update()

    def fit_view(self):
        self.fit_timeline()

    def _track_width(self):
        return max(1, self.width() - self.PAD * 2)

    def _ratio_at(self, x):
        return min(1.0, max(0.0, (float(x) - self.PAD) / self._track_width()))

    def _position_at(self, x):
        return self.view_start + self._ratio_at(x) * (self.view_end - self.view_start)

    def _x_of(self, frame):
        return self.PAD + (float(frame) - self.view_start) / (self.view_end - self.view_start) * self._track_width()

    def _frame_at(self, x):
        first = max(self.start, math.ceil(self.view_start))
        last = min(self.end - 1, math.ceil(self.view_end) - 1)
        return min(last, max(first, int(round(self._position_at(x)))))

    def _set_visible(self, first, span):
        span = min(float(self.end - self.start), max(1.0, float(span)))
        first = min(float(self.end) - span, max(float(self.start), float(first)))
        self.view_start, self.view_end = first, min(float(self.end), first + span)
        self.update()

    def _pin_at(self, x):
        near = [(abs(self._x_of(frame) - x), frame) for frame, _color in self.markers
                if self.start <= frame < self.end and self.view_start <= frame < self.view_end]
        near = [item for item in near if item[0] <= self.PIN_REACH]
        return min(near)[1] if near else None

    def _track(self):
        return 34, 24

    def _pin_at_point(self, point):
        top, height = self._track()
        return self._pin_at(point.x()) if top - 4 <= point.y() <= top + height + 4 else None

    def _move_playhead(self, frame):
        self.set_playhead(frame)
        self.moved.emit(frame)

    def wheelEvent(self, event):
        angle = event.angleDelta().y()
        pixels = event.pixelDelta().y()
        if not angle and not pixels:
            event.ignore()
            return
        steps = angle / 120.0 if angle else pixels / 40.0
        ratio = self._ratio_at(event.position().x())
        anchor = self._position_at(event.position().x())
        factor = math.exp(max(-700.0, min(700.0, -steps * math.log(1.25))))
        span = min(float(self.end - self.start), max(1.0, (self.view_end - self.view_start) * factor))
        self._set_visible(anchor - ratio * span, span)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._drag = False
            self._pan = event.position().x(), self.view_start, self.view_end
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        pin = self._pin_at_point(event.position())
        if pin is not None:
            self._move_playhead(pin)
            self.chosen.emit(pin)
        else:
            self._drag = True
            self._move_playhead(self._frame_at(event.position().x()))
        event.accept()

    def mouseMoveEvent(self, event):
        if self._pan is not None:
            x, first, last = self._pan
            delta = (event.position().x() - x) / self._track_width() * (last - first)
            self._set_visible(first - delta, last - first)
            event.accept()
            return
        if self._drag:
            self._move_playhead(self._frame_at(event.position().x()))
            event.accept()
            return
        over_pin = self._pin_at_point(event.position()) is not None
        self.setCursor(Qt.CursorShape.PointingHandCursor if over_pin else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan = None
            self.unsetCursor()
        elif event.button() == Qt.MouseButton.LeftButton:
            self._drag = False
        self.update()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if (event.button() == Qt.MouseButton.MiddleButton
                or event.button() == Qt.MouseButton.LeftButton and self._pin_at_point(event.position()) is None):
            self.fit_timeline()
            event.accept()
        else:
            event.ignore()

    def contextMenuEvent(self, event):
        pin = self._pin_at_point(event.pos())
        frame = self._frame_at(event.pos().x()) if pin is None else pin
        self._move_playhead(frame)
        self.context_requested.emit(frame, event.globalPos())
        event.accept()

    def _timecode(self, frame):
        return format_timecode(frame, self.timebase) if self.timebase else str(frame)

    @staticmethod
    def _font(bold=False):
        font = QFont(MONO_FAMILY)
        font.setPixelSize(TEXT_SECONDARY)
        font.setBold(bold)
        return font

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(PANEL_BG))
        top, height = self._track()
        painter.setPen(QColor(TEXT_MUTED))
        painter.setFont(self._font())
        previous_right = -1
        for index in range(5):
            x = self.PAD + self._track_width() * index / 4
            frame = self._frame_at(x)
            painter.drawLine(QPointF(x, 27), QPointF(x, top - 2))
            label = self._timecode(frame)
            width = painter.fontMetrics().horizontalAdvance(label)
            left = max(2.0, min(x + 3, self.width() - width - 2))
            if left > previous_right + 6 or index == 0:
                painter.drawText(QPointF(left, 22), label)
                previous_right = left + width
        track = QRectF(self.PAD, top, self._track_width(), height)
        painter.setPen(QPen(QColor(BORDER_ROW), 1))
        painter.setBrush(QColor(APP_BG))
        painter.drawRoundedRect(track, 3, 3)
        painter.save()
        painter.setClipRect(track.adjusted(1, 1, -1, -1))
        painter.setPen(Qt.PenStyle.NoPen)
        for index, (first, last) in enumerate(self.pages):
            first, last = max(first, self.view_start), min(last, self.view_end)
            if last <= first:
                continue
            left, right = self._x_of(first), self._x_of(last)
            painter.setBrush(QColor("#163644" if index % 2 == 0 else "#0f2a35"))
            painter.drawRect(QRectF(left, top + 1, max(1, right - left), height - 2))
        painter.restore()
        for frame, color in self.markers:
            if not self.start <= frame < self.end or not self.view_start <= frame < self.view_end:
                continue
            x = self._x_of(frame)
            shade = QColor(STATUS_COLOURS.get(color, STATUS_COLOURS["manual"]))
            painter.setPen(QPen(shade, 2))
            painter.drawLine(QPointF(x, top + 2), QPointF(x, top + height - 1))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shade)
            painter.drawRoundedRect(QRectF(x - 3, top - 3, 6, 6), 1.5, 1.5)
        if self.playhead is None or not self.view_start <= self.playhead < self.view_end:
            return
        x = self._x_of(self.playhead)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PLAYHEAD))
        painter.drawPolygon(QPolygon([QPoint(round(x) - 6, 2), QPoint(round(x) + 6, 2), QPoint(round(x), 12)]))
        painter.setPen(QPen(QColor(PLAYHEAD), 2))
        painter.drawLine(QPointF(x, 12), QPointF(x, top + height + 3))
        label = self._timecode(self.playhead)
        painter.setFont(self._font(bold=True))
        width = min(max(1, self.width() - 4), painter.fontMetrics().horizontalAdvance(label) + 12)
        left = max(2, min(x - width / 2, self.width() - width - 2))
        badge = QRectF(left, top + height + 9, width, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PLAYHEAD) if self._drag else QColor("#3a2a24"))
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(QColor("#1a0d08") if self._drag else QColor(PLAYHEAD))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)

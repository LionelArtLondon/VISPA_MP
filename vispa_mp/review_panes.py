"""Resizable review panes shared by Strip and Board."""

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QScrollArea, QSplitter, QSplitterHandle, QWidget

from vispa_mp.ui_tokens import ACCENT, BORDER_ROW, PANEL_BG, SEPARATOR


class WorkspaceSplitterHandle(QSplitterHandle):
    """A narrow visible divider with a wider native drag target."""

    def __init__(self, parent):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._hovered = False
        self._pressed = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.SplitHCursor)
        self.setAccessibleName("Resize workspace panels")
        self.setToolTip("Drag to resize panels")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(PANEL_BG))
        color = ACCENT if self._pressed else SEPARATOR if self._hovered else BORDER_ROW
        painter.fillRect((self.width() - 2) // 2, 0, 2, self.height(), QColor(color))

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._pressed:
            self._pressed = True
            self.update()
            self.splitter().resize_started.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._hovered = self.rect().contains(event.position().toPoint())
            self._finish_resize()

    def _finish_resize(self):
        if self._pressed:
            self._pressed = False
            self.update()
            self.splitter().resize_finished.emit()

    def event(self, event):
        if event.type() in (QEvent.Type.Hide, QEvent.Type.WindowDeactivate, QEvent.Type.UngrabMouse):
            self._hovered = False
            self._finish_resize()
        return super().event(event)


class WorkspaceSplitter(QSplitter):
    """Horizontal Pages / canvas / tools layout; only the canvas stretches."""

    resize_started = Signal()
    resize_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("workspaceSplitter")
        self.setChildrenCollapsible(False)
        self.setHandleWidth(8)
        self.setOpaqueResize(True)

    def createHandle(self):
        return WorkspaceSplitterHandle(self)


class ReviewSplitter(QSplitter):
    def __init__(self):
        super().__init__(Qt.Orientation.Vertical)
        self.setObjectName("reviewSplitter")
        self.setChildrenCollapsible(False)
        self.setHandleWidth(8)
        self.setStyleSheet("""
            QSplitter#reviewSplitter::handle:vertical {
                background: #1c3e4b;
                border-top: 1px solid #3c5b6b;
                border-bottom: 1px solid #081820;
            }
            QSplitter#reviewSplitter::handle:vertical:hover {
                background: #239ba8;
            }
        """)


class SuggestionArea(QScrollArea):
    viewport_resized = Signal()

    def __init__(self):
        super().__init__()
        self._pan_origin = None
        self._pan_scroll = 0
        self._pan_cursor = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self.viewport_resized)
        self.viewport().setMouseTracking(True)
        self.installEventFilter(self)
        self._watch_pan_children(self.viewport())

    def _watch_pan_children(self, parent):
        """Cards are recreated on selection; catch drags on their new images too."""
        parent.installEventFilter(self)
        for child in parent.children():
            self._watch_pan_children(child)

    def _inside_viewport(self, watched):
        return isinstance(watched, QWidget) and (
            watched is self.viewport() or self.viewport().isAncestorOf(watched))

    def _end_pan(self):
        if self._pan_origin is None:
            return
        self._pan_origin = None
        cursor, explicit = self._pan_cursor
        self._pan_cursor = None
        if explicit:
            self.viewport().setCursor(cursor)
        else:
            self.viewport().unsetCursor()
        if QWidget.mouseGrabber() is self.viewport():
            self.viewport().releaseMouse()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.ChildAdded:
            self._watch_pan_children(event.child())
        if watched is self.viewport() and kind == QEvent.Type.Resize:
            self._resize_timer.start(0)
        if watched in (self, self.viewport()) and kind in (
                QEvent.Type.Hide, QEvent.Type.WindowDeactivate, QEvent.Type.UngrabMouse):
            self._end_pan()
        if self._inside_viewport(watched):
            if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.MiddleButton:
                self._pan_origin = event.globalPosition()
                self._pan_scroll = self.horizontalScrollBar().value()
                self._pan_cursor = (self.viewport().cursor(),
                                    self.viewport().testAttribute(Qt.WidgetAttribute.WA_SetCursor))
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
                self.viewport().grabMouse()
                event.accept()
                return True
            if self._pan_origin is not None:
                if kind == QEvent.Type.MouseMove:
                    if not event.buttons() & Qt.MouseButton.MiddleButton:
                        self._end_pan()
                    else:
                        delta = event.globalPosition().x() - self._pan_origin.x()
                        self.horizontalScrollBar().setValue(self._pan_scroll - round(delta))
                        event.accept()
                        return True
                elif kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.MiddleButton:
                    self._end_pan()
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

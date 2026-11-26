"""Internal marker drags and page-list insertion targets for the review."""

import json

from PySide6.QtCore import QMimeData, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QFrame, QWidget

from vispa_mp.ui_tokens import ACCENT

MARKER_MIME = "application/x-vispa-mp-marker"


def _frame_number(value):
    return isinstance(value, int) and not isinstance(value, bool) and -(2 ** 31) <= value < 2 ** 31


def marker_mime(frame, token):
    if not _frame_number(frame) or not isinstance(token, str) or not token:
        raise ValueError("A marker drag needs a source frame and a review token.")
    mime = QMimeData()
    mime.setData(MARKER_MIME, json.dumps({"frame": frame, "token": token}).encode("utf-8"))
    return mime


def read_drag(mime, token):
    """Only accept frame IDs from this review's own drag payload."""
    if (not isinstance(mime, QMimeData) or not isinstance(token, str) or not token
            or not mime.hasFormat(MARKER_MIME)):
        return None
    raw = bytes(mime.data(MARKER_MIME))
    if len(raw) > 4096:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if (not isinstance(data, dict) or data.get("token") != token
            or not _frame_number(data.get("frame"))):
        return None
    return data["frame"]


def start_marker_drag(widget, frame, token, pixmap=None):
    drag = QDrag(widget)
    drag.setMimeData(marker_mime(frame, token))
    if pixmap is not None and not pixmap.isNull():
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
    return drag.exec(Qt.DropAction.MoveAction)


class MarkerDragCard(QFrame):
    clicked = Signal()
    opened = Signal()
    drag_requested = Signal(int)

    def __init__(self, frame, manual=False, parent=None):
        super().__init__(parent)
        if not _frame_number(frame):
            raise ValueError("A marker card needs an integer source frame.")
        self.frame = int(frame)
        self.manual = bool(manual)
        self._drag_origin = None
        self._drag_started = False

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        self._drag_origin = None if self.manual else event.globalPosition()
        self._drag_started = False
        self.clicked.emit()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            distance = (event.globalPosition() - self._drag_origin).manhattanLength()
            if not self._drag_started and distance >= QApplication.startDragDistance():
                self._drag_started = True
                self.drag_requested.emit(self.frame)
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            self._drag_started = False
            event.accept()
        else:
            event.ignore()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.opened.emit()
            event.accept()
        else:
            event.ignore()


class PagesDropMixin:
    """Drop targets on a page header or between expanded page images."""

    def _init_page_drop(self, owner):
        self._drop_owner = owner
        self._drop_frame = None
        self._drop_global = None
        self._drop_target_info = None
        self.setAcceptDrops(True)
        self._drop_indicator = QWidget(self)
        self._drop_indicator.setObjectName("pageDropIndicator")
        self._drop_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._drop_indicator.setStyleSheet(f"background: {ACCENT};")
        self._drop_indicator.hide()
        self._drop_scroll_timer = QTimer(self)
        self._drop_scroll_timer.setInterval(50)
        self._drop_scroll_timer.timeout.connect(self._scroll_drop_target)

    def _valid_drop_frame(self, mime):
        owner = self._drop_owner
        if owner.worker is not None:
            return None
        frame = read_drag(mime, getattr(owner, "_drag_token", None))
        if frame is None or owner._proposal(frame) is None:
            return None
        return frame

    def _drop_viewport(self):
        return self._drop_owner.pages_scroll.viewport()

    @staticmethod
    def _global_rect(widget):
        return QRect(widget.mapToGlobal(QPoint()), widget.size())

    def _page_drop_target(self, point):
        """Return (page ID, before-frame or None, indicator global Y)."""
        owner = self._drop_owner
        viewport = self._drop_viewport()
        if not self._global_rect(viewport).contains(point):
            return None
        for page in owner.pages:
            info = owner._rows.get(page["id"])
            if info is None or not any(not item["manual"] for item in page["items"]):
                continue
            row, children = info["row"], info["children"]
            if row.isVisible() and self._global_rect(row).contains(point):
                bottom = self._global_rect(children).bottom() if children.isVisible() else self._global_rect(row).bottom()
                return page["id"], None, bottom
            if not children.isVisible() or not self._global_rect(children).contains(point):
                continue
            layout = children.layout()
            for index, item in enumerate(page["items"]):
                entry = layout.itemAt(index)
                if entry is None or entry.widget() is None:
                    continue
                child_rect = self._global_rect(entry.widget())
                if point.y() > child_rect.bottom():
                    continue
                after = point.y() >= child_rect.center().y()
                insert_index = index + int(after)
                before = next((int(later["proposal"]["frame"]) for later in page["items"][insert_index:]
                               if not later["manual"]), None)
                return page["id"], before, child_rect.bottom() if after else child_rect.top()
            return page["id"], None, self._global_rect(children).bottom()
        return None

    def _clear_page_drop(self):
        self._drop_scroll_timer.stop()
        self._drop_indicator.hide()
        self._drop_frame = self._drop_global = self._drop_target_info = None

    def _update_page_drop(self, point):
        self._drop_global = point
        self._drop_target_info = self._page_drop_target(point)
        if self._drop_target_info is None:
            self._drop_indicator.hide()
            return False
        _page_id, _before_frame, global_y = self._drop_target_info
        viewport = self._drop_viewport()
        view_rect = self._global_rect(viewport)
        global_y = max(view_rect.top(), min(global_y, view_rect.bottom() - 1))
        top_left = self.mapFromGlobal(QPoint(view_rect.left() + 4, global_y))
        self._drop_indicator.setGeometry(top_left.x(), top_left.y(), max(1, view_rect.width() - 8), 2)
        self._drop_indicator.show()
        self._drop_indicator.raise_()
        return True

    def _accept_page_drag(self, event):
        frame = self._valid_drop_frame(event.mimeData())
        if frame is None or not event.possibleActions() & Qt.DropAction.MoveAction:
            self._clear_page_drop()
            event.ignore()
            return
        self._drop_frame = frame
        point = self.mapToGlobal(event.position().toPoint())
        self._update_page_drop(point)
        self._drop_scroll_timer.start()
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    def dragEnterEvent(self, event):
        self._accept_page_drag(event)

    def dragMoveEvent(self, event):
        self._accept_page_drag(event)

    def dragLeaveEvent(self, event):
        self._clear_page_drop()
        event.accept()

    def hideEvent(self, event):
        if hasattr(self, "_drop_scroll_timer"):
            self._clear_page_drop()
        super().hideEvent(event)

    def dropEvent(self, event):
        frame = self._valid_drop_frame(event.mimeData())
        point = self.mapToGlobal(event.position().toPoint())
        target = self._page_drop_target(point) if frame is not None else None
        self._clear_page_drop()
        if target is None or not event.possibleActions() & Qt.DropAction.MoveAction:
            event.ignore()
            return
        page_id, before_frame, _line = target
        if self._drop_owner._move_marker_to_page(frame, page_id, before_frame):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def _scroll_drop_target(self):
        if self._drop_global is None or self._drop_frame is None:
            self._clear_page_drop()
            return
        owner = self._drop_owner
        if owner.worker is not None or owner._proposal(self._drop_frame) is None:
            self._clear_page_drop()
            return
        viewport = self._drop_viewport()
        rect = self._global_rect(viewport)
        point = self._drop_global
        if not rect.contains(point):
            return
        if point.y() < rect.top() + 24:
            step = -12
        elif point.y() > rect.bottom() - 24:
            step = 12
        else:
            return
        bar = owner.pages_scroll.verticalScrollBar()
        bar.setValue(bar.value() + step)
        self._update_page_drop(point)

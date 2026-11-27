"""Internal marker drags and page-list insertion targets for the review."""

import json

from PySide6.QtCore import QEvent, QMimeData, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QDrag, QPainter
from PySide6.QtWidgets import QApplication, QFrame, QWidget
from shiboken6 import isValid

from vispa_mp.ui_tokens import ACCENT
from vispa_mp.review_selection_style import STATUS_COLOURS, paint_review_frame

MARKER_MIME = "application/x-vispa-mp-marker"
MAX_DRAG_FRAMES = 4096
MAX_DRAG_BYTES = 65536
PAGE_EXPAND_DELAY_MS = 650


def _frame_number(value):
    return isinstance(value, int) and not isinstance(value, bool) and -(2 ** 31) <= value < 2 ** 31


def _valid_frames(frames, anchor):
    return (isinstance(frames, (list, tuple)) and 0 < len(frames) <= MAX_DRAG_FRAMES
            and all(_frame_number(frame) for frame in frames)
            and len(set(frames)) == len(frames) and anchor in frames)


def marker_mime(frame, token, frames=None):
    if not _frame_number(frame) or not isinstance(token, str) or not token:
        raise ValueError("A marker drag needs a source frame and a review token.")
    payload = {"frame": frame, "token": token}
    if frames is not None:
        if not _valid_frames(frames, frame):
            raise ValueError("A marker group needs unique integer frames including its source image.")
        payload["frames"] = list(frames)
    raw = json.dumps(payload).encode("utf-8")
    if len(raw) > MAX_DRAG_BYTES:
        raise ValueError("The marker drag is too large.")
    mime = QMimeData()
    mime.setData(MARKER_MIME, raw)
    return mime


def _read_drag_payload(mime, token):
    if (not isinstance(mime, QMimeData) or not isinstance(token, str) or not token
            or not mime.hasFormat(MARKER_MIME)):
        return None
    raw = bytes(mime.data(MARKER_MIME))
    if len(raw) > MAX_DRAG_BYTES:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if (not isinstance(data, dict) or data.get("token") != token
            or not _frame_number(data.get("frame"))):
        return None
    if "frames" in data and not _valid_frames(data["frames"], data["frame"]):
        return None
    return data


def read_drag(mime, token):
    """Read the original source image, including from a valid group payload."""
    data = _read_drag_payload(mime, token)
    if data is None:
        return None
    return data["frame"]


def read_drag_frames(mime, token):
    """Only accept bounded, unique image IDs from this review's own drag."""
    data = _read_drag_payload(mime, token)
    if data is None:
        return None
    return list(data.get("frames", [data["frame"]]))


def start_marker_drag(widget, frame, token, pixmap=None, frames=None):
    drag = QDrag(widget)
    drag.setMimeData(marker_mime(frame, token, frames))
    if pixmap is not None and not pixmap.isNull():
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
    return drag.exec(Qt.DropAction.MoveAction)


class MarkerDragCard(QFrame):
    clicked = Signal()
    additive_clicked = Signal()
    range_clicked = Signal(bool)
    opened = Signal()
    drag_requested = Signal(int)

    def __init__(self, frame, manual=False, parent=None):
        super().__init__(parent)
        if not _frame_number(frame):
            raise ValueError("A marker card needs an integer source frame.")
        self.frame = int(frame)
        self.manual = bool(manual)
        self.setProperty("reviewCard", True)
        self._drag_origin = None
        self._drag_started = False
        self._deferred_click = False

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        additive = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        extending = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self._drag_origin = None if self.manual or additive or extending else event.globalPosition()
        self._drag_started = False
        self._deferred_click = (not self.manual and not additive and not extending
                                and self.property("multiSelected") in (True, "true"))
        if extending:
            self.range_clicked.emit(additive)
        elif additive:
            self.additive_clicked.emit()
        elif not self._deferred_click:
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
            clicked = self._deferred_click and not self._drag_started
            self._drag_origin = None
            self._drag_started = False
            self._deferred_click = False
            if clicked:
                self.clicked.emit()
            event.accept()
        else:
            event.ignore()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                self.opened.emit()
            event.accept()
        else:
            event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.property("role") != "reviewCard":
            return
        painter = QPainter(self)
        paint_review_frame(
            painter, self.rect(), STATUS_COLOURS.get(self.property("kind"), STATUS_COLOURS["manual"]),
            selected=self.property("selected") in (True, "true"),
            preview=self.property("state") == "preview", kept=self.property("state") == "kept")


class PageMarkerRow(QWidget):
    """Let a sidebar marker row drag without stealing its button's click."""

    drag_requested = Signal(int)

    def __init__(self, frame, manual=False, parent=None):
        super().__init__(parent)
        if not _frame_number(frame):
            raise ValueError("A marker row needs an integer source frame.")
        self.frame = int(frame)
        self.manual = bool(manual)
        self._drag_origin = None
        self._drag_started = False
        self.watch_drag(self)

    def watch_drag(self, widget):
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                selecting = bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                                      | Qt.KeyboardModifier.ShiftModifier))
                self._drag_origin = None if self.manual or selecting else event.globalPosition()
                self._drag_started = False
        elif event.type() == QEvent.Type.MouseMove:
            if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
                distance = (event.globalPosition() - self._drag_origin).manhattanLength()
                if not self._drag_started and distance >= QApplication.startDragDistance():
                    self._drag_started = True
                    if hasattr(watched, "setDown"):
                        watched.setDown(False)
                    self.drag_requested.emit(self.frame)
                if self._drag_started:
                    event.accept()
                    return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                dragged = self._drag_started
                self._drag_origin = None
                self._drag_started = False
                if dragged:
                    event.accept()
                    return True
        return super().eventFilter(watched, event)


class PagesDropMixin:
    """Drop targets on a page header or between expanded page images."""

    def _init_page_drop(self, owner):
        self._drop_owner = owner
        self._drop_frame = None
        self._drop_frames = None
        self._drop_global = None
        self._drop_target_info = None
        self._drop_header_row = None
        self.setAcceptDrops(True)
        self._drop_indicator = QWidget(self)
        self._drop_indicator.setObjectName("pageDropIndicator")
        self._drop_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._drop_indicator.setStyleSheet(f"background: {ACCENT};")
        self._drop_indicator.hide()
        self._drop_scroll_timer = QTimer(self)
        self._drop_scroll_timer.setInterval(50)
        self._drop_scroll_timer.timeout.connect(self._scroll_drop_target)
        self._drop_expand_page_id = None
        self._drop_expand_timer = QTimer(self)
        self._drop_expand_timer.setSingleShot(True)
        self._drop_expand_timer.setInterval(PAGE_EXPAND_DELAY_MS)
        self._drop_expand_timer.timeout.connect(self._expand_hovered_page)

    def _valid_drop_frames(self, mime):
        owner = self._drop_owner
        if owner.worker is not None or getattr(owner, "_learning_job_busy", False):
            return None
        frames = read_drag_frames(mime, getattr(owner, "_drag_token", None))
        if frames is None or any(owner._proposal(frame) is None for frame in frames):
            return None
        if len(frames) > 1 and not callable(getattr(owner, "_move_markers_to_page", None)):
            return None
        return frames

    def _valid_drop_frame(self, mime):
        """Retain the old single-image validation helper for callers."""
        frames = self._valid_drop_frames(mime)
        return read_drag(mime, getattr(self._drop_owner, "_drag_token", None)) if frames else None

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
        self._cancel_page_expand()
        self._drop_indicator.hide()
        self._set_page_drop_header(None)
        self._drop_frame = self._drop_global = self._drop_target_info = None
        self._drop_frames = None

    def _cancel_page_expand(self):
        self._drop_expand_timer.stop()
        self._drop_expand_page_id = None

    def _schedule_page_expand(self, page_id):
        owner = self._drop_owner
        info = owner._rows.get(page_id)
        if (not self._drop_frames or info is None or not info["children"].isHidden()
                or not callable(getattr(owner, "_toggle_page", None))):
            self._cancel_page_expand()
            return
        if self._drop_expand_page_id != page_id:
            self._drop_expand_page_id = page_id
            self._drop_expand_timer.start()

    def _expand_hovered_page(self):
        page_id = self._drop_expand_page_id
        self._cancel_page_expand()
        owner = self._drop_owner
        if page_id is None or self._drop_global is None or not self._drop_frames:
            return
        if (owner.worker is not None or getattr(owner, "_learning_job_busy", False)
                or any(owner._proposal(frame) is None for frame in self._drop_frames)):
            self._clear_page_drop()
            return
        target = self._page_drop_target(self._drop_global)
        info = owner._rows.get(page_id)
        if (target is None or target[0] != page_id or info is None
                or not isValid(info["row"]) or self._drop_header_row is not info["row"]
                or not self._global_rect(info["row"]).contains(self._drop_global)
                or not info["children"].isHidden()):
            return
        # This is navigation only: keep the selected images and review intact.
        owner._toggle_page(page_id)
        self._update_page_drop(self._drop_global)

    def _set_page_drop_header(self, row):
        if row is self._drop_header_row:
            return
        previous, self._drop_header_row = self._drop_header_row, row
        for widget, active in ((previous, False), (row, True)):
            if widget is None or not isValid(widget):
                continue
            widget.setProperty("dropTarget", active)
            hint = getattr(widget, "_drop_hint", None)
            if hint is not None:
                hint.setVisible(active)
            for child in (widget, *widget.findChildren(QWidget)):
                child.style().unpolish(child)
                child.style().polish(child)
                child.update()

    def _update_page_drop(self, point):
        self._drop_global = point
        self._drop_target_info = self._page_drop_target(point)
        if self._drop_target_info is None:
            self._drop_indicator.hide()
            self._set_page_drop_header(None)
            self._cancel_page_expand()
            return False
        page_id, _before_frame, global_y = self._drop_target_info
        row = self._drop_owner._rows[page_id]["row"]
        if row.isVisible() and self._global_rect(row).contains(point):
            self._set_page_drop_header(row)
            self._schedule_page_expand(page_id)
            self._drop_indicator.hide()
            return True
        self._set_page_drop_header(None)
        self._cancel_page_expand()
        viewport = self._drop_viewport()
        view_rect = self._global_rect(viewport)
        global_y = max(view_rect.top(), min(global_y, view_rect.bottom() - 1))
        top_left = self.mapFromGlobal(QPoint(view_rect.left() + 4, global_y))
        self._drop_indicator.setGeometry(top_left.x(), top_left.y(), max(1, view_rect.width() - 8), 2)
        self._drop_indicator.show()
        self._drop_indicator.raise_()
        return True

    def _accept_page_drag(self, event):
        frames = self._valid_drop_frames(event.mimeData())
        if frames is None or not event.possibleActions() & Qt.DropAction.MoveAction:
            self._clear_page_drop()
            event.ignore()
            return
        self._drop_frames = frames
        self._drop_frame = read_drag(event.mimeData(), getattr(self._drop_owner, "_drag_token", None))
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
        frames = self._valid_drop_frames(event.mimeData())
        point = self.mapToGlobal(event.position().toPoint())
        target = self._page_drop_target(point) if frames is not None else None
        self._clear_page_drop()
        if target is None or not event.possibleActions() & Qt.DropAction.MoveAction:
            event.ignore()
            return
        page_id, before_frame, _line = target
        move_group = getattr(self._drop_owner, "_move_markers_to_page", None)
        moved = (move_group(frames, page_id, before_frame) if callable(move_group)
                 else self._drop_owner._move_marker_to_page(frames[0], page_id, before_frame))
        if moved:
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def _scroll_drop_target(self):
        if self._drop_global is None or not self._drop_frames:
            self._clear_page_drop()
            return
        owner = self._drop_owner
        if (owner.worker is not None or getattr(owner, "_learning_job_busy", False)
                or any(owner._proposal(frame) is None for frame in self._drop_frames)):
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

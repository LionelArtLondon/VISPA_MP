"""Internal drags preserve source IDs and show exact page-list insertions."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from vispa_mp.review_drag import (MARKER_MIME, MAX_DRAG_BYTES, MAX_DRAG_FRAMES,
                                 MarkerDragCard, PageMarkerRow, PagesDropMixin,
                                 marker_mime, read_drag, read_drag_frames, start_marker_drag)


def test_marker_mime_is_scoped_to_the_current_review(qapp):
    mime = marker_mime(123, "this-review")
    assert read_drag(mime, "this-review") == 123
    assert read_drag(mime, "another-review") is None
    assert read_drag(QMimeData(), "this-review") is None
    assert read_drag(None, "this-review") is None


@pytest.mark.parametrize("data", [
    b"not json", b"\xff", b"[]", b"null", b"x" * 4097,
    json.dumps({"frame": True, "token": "review"}).encode(),
    json.dumps({"frame": 1.5, "token": "review"}).encode(),
    json.dumps({"frame": "1", "token": "review"}).encode(),
    json.dumps({"frame": 2 ** 31, "token": "review"}).encode(),
    json.dumps({"frame": 1, "token": None}).encode(),
])
def test_invalid_marker_drag_payloads_are_rejected(qapp, data):
    mime = QMimeData()
    mime.setData(MARKER_MIME, data)
    assert read_drag(mime, "review") is None


def _move(card, start, delta, buttons=Qt.MouseButton.LeftButton):
    point = start + delta
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point), QPointF(card.mapToGlobal(point)),
                        Qt.MouseButton.NoButton, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(card, event)


def test_card_selects_on_click_but_starts_one_drag_only_after_the_threshold(qapp):
    card = MarkerDragCard(123)
    card.resize(200, 100)
    card.show()
    qapp.processEvents()
    clicks, drags, opens = [], [], []
    card.clicked.connect(lambda: clicks.append(True))
    card.drag_requested.connect(drags.append)
    card.opened.connect(lambda: opens.append(True))
    point = QPoint(20, 20)
    QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=point)
    assert clicks == [True]
    _move(card, point, QPoint(1, 1))
    assert drags == []
    _move(card, point, QPoint(QApplication.startDragDistance() + 2, 0))
    _move(card, point, QPoint(QApplication.startDragDistance() + 20, 0))
    assert drags == [123]
    QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(card, Qt.MouseButton.LeftButton, pos=point)
    assert opens == [True]


@pytest.mark.parametrize("button", [Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton])
def test_middle_and_right_gestures_do_not_select_or_drag(qapp, button):
    card = MarkerDragCard(123)
    card.resize(200, 100)
    card.show()
    clicks, drags = [], []
    card.clicked.connect(lambda: clicks.append(True))
    card.drag_requested.connect(drags.append)
    QTest.mousePress(card, button, pos=QPoint(10, 10))
    _move(card, QPoint(10, 10), QPoint(50, 0), buttons=button)
    QTest.mouseRelease(card, button, pos=QPoint(60, 10))
    assert clicks == drags == []


def test_a_manual_card_can_be_selected_but_never_dragged(qapp):
    card = MarkerDragCard(123, manual=True)
    card.resize(200, 100)
    clicks, drags = [], []
    card.clicked.connect(lambda: clicks.append(True))
    card.drag_requested.connect(drags.append)
    QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    _move(card, QPoint(10, 10), QPoint(50, 0))
    QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(60, 10))
    assert clicks == [True]
    assert drags == []


def test_start_drag_uses_move_action_and_the_review_mime(qapp, monkeypatch):
    created = []

    class Drag:
        def __init__(self, widget):
            self.widget = widget
            created.append(self)

        def setMimeData(self, mime):
            self.mime = mime

        def exec(self, action):
            self.action = action
            return Qt.DropAction.IgnoreAction

    monkeypatch.setattr("vispa_mp.review_drag.QDrag", Drag)
    widget = QWidget()
    assert start_marker_drag(widget, 123, "review") == Qt.DropAction.IgnoreAction
    assert created[0].widget is widget
    assert read_drag(created[0].mime, "review") == 123
    assert created[0].action == Qt.DropAction.MoveAction


class DropPanel(PagesDropMixin, QWidget):
    def __init__(self, owner):
        super().__init__()
        self._init_page_drop(owner)


def _panel(qapp, many=False):
    moves = []
    owner = SimpleNamespace(worker=None, _drag_token="review", pages=[], _rows={})
    owner._proposal = lambda frame: {"frame": frame} if frame == 99 else None
    owner._move_marker_to_page = lambda *args: moves.append(args) or True
    panel = DropPanel(owner)
    layout = QVBoxLayout(panel)
    owner.pages_scroll = QScrollArea()
    owner.pages_scroll.setWidgetResizable(True)
    host = QWidget()
    pages = QVBoxLayout(host)
    pages.setContentsMargins(0, 0, 0, 0)
    pages.setSpacing(0)
    for index in range(12 if many else 3):
        page_id = 100 + index
        items = ([{"manual": True, "frame": 70}] if index == 2 else [
            {"manual": False, "proposal": {"frame": index * 30 + 10}},
            {"manual": True, "frame": index * 30 + 15},
            {"manual": False, "proposal": {"frame": index * 30 + 20}},
        ])
        row = QLabel(f"Page {index}")
        row.setFixedHeight(28)
        children = QWidget()
        child_layout = QVBoxLayout(children)
        child_layout.setContentsMargins(0, 0, 0, 0)
        child_layout.setSpacing(0)
        for item in items:
            label = QLabel(str(item))
            label.setFixedHeight(30)
            child_layout.addWidget(label)
        pages.addWidget(row)
        pages.addWidget(children)
        if index == 0:
            children.hide()
        owner.pages.append({"id": page_id, "items": items})
        owner._rows[page_id] = {"row": row, "children": children}
    pages.addStretch(1)
    owner.pages_scroll.setWidget(host)
    layout.addWidget(owner.pages_scroll)
    panel.resize(300, 280)
    panel.show()
    qapp.processEvents()
    return panel, owner, moves


def _point(panel, widget, y=None):
    point = QPoint(12, widget.height() // 2 if y is None else y)
    return panel.mapFromGlobal(widget.mapToGlobal(point))


def _enter(panel, point, token="review"):
    mime = marker_mime(99, token)
    event = QDragEnterEvent(point, Qt.DropAction.MoveAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    event._test_mime = mime
    QApplication.sendEvent(panel, event)
    return event


def _drop(panel, point, token="review"):
    mime = marker_mime(99, token)
    event = QDropEvent(QPointF(point), Qt.DropAction.MoveAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    event._test_mime = mime
    QApplication.sendEvent(panel, event)
    return event


def _drag_move(panel, point, token="review"):
    mime = marker_mime(99, token)
    event = QDragMoveEvent(point, Qt.DropAction.MoveAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    event._test_mime = mime
    QApplication.sendEvent(panel, event)
    return event


def test_drop_on_a_collapsed_page_appends_without_opening_it(qapp):
    panel, owner, moves = _panel(qapp)
    point = _point(panel, owner._rows[100]["row"])
    assert _enter(panel, point).isAccepted()
    assert panel._drop_indicator.isHidden()
    assert owner._rows[100]["row"].property("dropTarget") is True
    assert panel._drop_target_info[:2] == (100, None)
    assert _drop(panel, point).isAccepted()
    assert moves == [(99, 100, None)]
    assert owner._rows[100]["children"].isHidden()
    assert panel._drop_indicator.isHidden()
    assert not owner._rows[100]["row"].property("dropTarget")
    assert not panel._drop_scroll_timer.isActive()


@pytest.mark.parametrize("index,y,before", [(0, 2, 40), (0, 28, 50), (1, 2, 50), (2, 2, 50), (2, 28, None)])
def test_expanded_page_drop_indicates_exact_insertion_around_images(qapp, index, y, before):
    panel, owner, moves = _panel(qapp)
    child = owner._rows[101]["children"].layout().itemAt(index).widget()
    point = _point(panel, child, y)
    assert _enter(panel, point).isAccepted()
    assert panel._drop_target_info[:2] == (101, before)
    assert panel._drop_indicator.isVisible()
    assert _drop(panel, point).isAccepted()
    assert moves == [(99, 101, before)]


def test_other_reviews_busy_work_and_manual_only_pages_cannot_receive_a_drop(qapp):
    panel, owner, moves = _panel(qapp)
    point = _point(panel, owner._rows[100]["row"])
    assert not _enter(panel, point, token="another-review").isAccepted()
    assert moves == []
    owner.worker = object()
    assert not _enter(panel, point).isAccepted()
    owner.worker = None
    point = _point(panel, owner._rows[102]["row"])
    _enter(panel, point)
    assert not _drop(panel, point).isAccepted()
    assert moves == []


def test_leaving_the_list_clears_the_indicator_and_autoscroll(qapp):
    panel, owner, _moves = _panel(qapp)
    point = _point(panel, owner._rows[100]["row"])
    _enter(panel, point)
    assert owner._rows[100]["row"].property("dropTarget") is True
    assert panel._drop_scroll_timer.isActive()
    QApplication.sendEvent(panel, QDragLeaveEvent())
    assert panel._drop_indicator.isHidden()
    assert not owner._rows[100]["row"].property("dropTarget")
    assert not panel._drop_scroll_timer.isActive()
    assert panel._drop_frame is None


def test_drag_move_updates_the_line_and_hiding_the_panel_cleans_up(qapp):
    panel, owner, moves = _panel(qapp)
    _enter(panel, _point(panel, owner._rows[100]["row"]))
    child = owner._rows[101]["children"].layout().itemAt(0).widget()
    point = _point(panel, child, 2)
    mime = marker_mime(99, "review")
    event = QDragMoveEvent(point, Qt.DropAction.MoveAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(panel, event)
    assert event.isAccepted()
    assert panel._drop_target_info[:2] == (101, 40)
    assert panel._drop_indicator.isVisible()
    assert not owner._rows[100]["row"].property("dropTarget")
    assert not owner._rows[101]["row"].property("dropTarget")
    assert moves == []
    panel.hide()
    assert panel._drop_indicator.isHidden()
    assert not panel._drop_scroll_timer.isActive()


def test_header_hover_highlights_only_the_current_page_without_mutating_the_review(qapp):
    panel, owner, moves = _panel(qapp)
    before = deepcopy(owner.pages)
    first, second = owner._rows[100]["row"], owner._rows[101]["row"]
    try:
        assert _enter(panel, _point(panel, first)).isAccepted()
        assert first.property("dropTarget") is True
        assert not second.property("dropTarget")
        assert panel._drop_indicator.isHidden()
        assert _drag_move(panel, _point(panel, second)).isAccepted()
        assert not first.property("dropTarget")
        assert second.property("dropTarget") is True
        assert panel._drop_indicator.isHidden()
        assert panel._drop_target_info[:2] == (101, None)
        assert owner.pages == before
        assert moves == []
        assert owner._rows[100]["children"].isHidden()
        assert owner._rows[101]["children"].isVisible()
    finally:
        panel.close()


@pytest.mark.parametrize("cleanup", ["foreign", "manual", "outside", "hide", "worker"])
def test_header_highlight_is_cleared_when_the_target_or_drag_becomes_invalid(qapp, cleanup):
    panel, owner, moves = _panel(qapp)
    row = owner._rows[100]["row"]
    try:
        assert _enter(panel, _point(panel, row)).isAccepted()
        assert row.property("dropTarget") is True
        if cleanup == "foreign":
            assert not _drag_move(panel, _point(panel, row), token="foreign").isAccepted()
        elif cleanup == "manual":
            _drag_move(panel, _point(panel, owner._rows[102]["row"]))
        elif cleanup == "outside":
            _drag_move(panel, QPoint(-20, -20))
        elif cleanup == "hide":
            panel.hide()
        else:
            owner.worker = object()
            panel._scroll_drop_target()
        assert not any(info["row"].property("dropTarget") for info in owner._rows.values())
        assert panel._drop_indicator.isHidden()
        assert moves == []
    finally:
        panel.close()


def test_drag_near_viewport_edge_scrolls_the_list_and_updates_the_target(qapp):
    panel, owner, _moves = _panel(qapp, many=True)
    viewport = owner.pages_scroll.viewport()
    point = panel.mapFromGlobal(viewport.mapToGlobal(QPoint(20, viewport.height() - 3)))
    _enter(panel, point)
    bar = owner.pages_scroll.verticalScrollBar()
    assert bar.maximum() > 0
    before = bar.value()
    panel._scroll_drop_target()
    assert bar.value() > before
    owner.worker = object()
    panel._scroll_drop_target()
    assert panel._drop_frame is None
    assert not panel._drop_scroll_timer.isActive()


def test_group_mime_preserves_the_anchor_and_rejects_foreign_reviews(qapp):
    mime = marker_mime(20, "review", frames=[30, 20, 10])
    assert read_drag(mime, "review") == 20
    assert read_drag_frames(mime, "review") == [30, 20, 10]
    assert read_drag_frames(mime, "foreign") is None
    assert read_drag_frames(marker_mime(20, "review"), "review") == [20]
    assert read_drag_frames(None, "review") is None


@pytest.mark.parametrize("frames", [
    [], [1, 1], [True], [1, False], [1, 2.0], [1, "2"], [1, []],
    [2, 3], [1, 2 ** 31], "1", None, list(range(MAX_DRAG_FRAMES + 1)),
])
def test_group_payload_is_atomic_and_strictly_validated(qapp, frames):
    mime = QMimeData()
    mime.setData(MARKER_MIME, json.dumps({"frame": 1, "frames": frames, "token": "review"}).encode())
    assert read_drag_frames(mime, "review") is None
    assert read_drag(mime, "review") is None
    if frames is not None:
        with pytest.raises(ValueError):
            marker_mime(1, "review", frames=frames)


def test_valid_json_payload_still_obeys_the_byte_limit(qapp):
    mime = QMimeData()
    payload = {"frame": 1, "frames": [1], "token": "review", "padding": "x" * MAX_DRAG_BYTES}
    mime.setData(MARKER_MIME, json.dumps(payload).encode())
    assert read_drag_frames(mime, "review") is None


def test_start_drag_can_transport_the_entire_selection(qapp, monkeypatch):
    created = []

    class Drag:
        def __init__(self, widget):
            created.append(self)

        def setMimeData(self, mime):
            self.mime = mime

        def exec(self, action):
            return Qt.DropAction.MoveAction

    monkeypatch.setattr("vispa_mp.review_drag.QDrag", Drag)
    widget = QWidget()
    assert start_marker_drag(widget, 20, "review", frames=[10, 20]) == Qt.DropAction.MoveAction
    assert read_drag_frames(created[0].mime, "review") == [10, 20]


def test_selected_group_is_preserved_until_drag_but_a_plain_click_selects_on_release(qapp):
    card = MarkerDragCard(123)
    card.setProperty("multiSelected", True)
    card.resize(200, 100)
    card.show()
    clicks, drags = [], []
    card.clicked.connect(lambda: clicks.append(True))
    card.drag_requested.connect(drags.append)
    point = QPoint(20, 20)
    QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=point)
    assert clicks == []
    QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=point)
    assert clicks == [True]
    clicks.clear()
    QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=point)
    _move(card, point, QPoint(QApplication.startDragDistance() + 2, 0))
    QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=point)
    assert clicks == []
    assert drags == [123]


def test_ctrl_click_in_a_selected_group_never_starts_a_drag(qapp):
    card = MarkerDragCard(123)
    card.setProperty("multiSelected", True)
    card.resize(200, 100)
    clicks, additive, drags = [], [], []
    card.clicked.connect(lambda: clicks.append(True))
    card.additive_clicked.connect(lambda: additive.append(True))
    card.drag_requested.connect(drags.append)
    point = QPoint(10, 10)
    QTest.mousePress(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, pos=point)
    _move(card, point, QPoint(50, 0))
    QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=point)
    assert clicks == drags == []
    assert additive == [True]


@pytest.mark.parametrize("source", ["row", "button", "label"])
def test_sidebar_row_and_children_share_one_threshold_drag_without_button_click(qapp, source):
    row = PageMarkerRow(123)
    layout = QVBoxLayout(row)
    button, label = QPushButton("Marker"), QLabel("Core")
    for child in (button, label):
        layout.addWidget(child)
        row.watch_drag(child)
    row.resize(200, 100)
    row.show()
    qapp.processEvents()
    watched = {"row": row, "button": button, "label": label}[source]
    clicks, drags = [], []
    button.clicked.connect(lambda: clicks.append(True))
    row.drag_requested.connect(drags.append)
    point = QPoint(10, 10)
    QTest.mousePress(watched, Qt.MouseButton.LeftButton, pos=point)
    _move(watched, point, QPoint(1, 1))
    assert drags == []
    _move(watched, point, QPoint(QApplication.startDragDistance() + 2, 0))
    _move(watched, point, QPoint(60, 0))
    QTest.mouseRelease(watched, Qt.MouseButton.LeftButton, pos=point)
    assert drags == [123]
    assert clicks == []
    row.close()


@pytest.mark.parametrize("manual,modifiers,button", [
    (False, Qt.KeyboardModifier.NoModifier, Qt.MouseButton.LeftButton),
    (True, Qt.KeyboardModifier.NoModifier, Qt.MouseButton.LeftButton),
    (False, Qt.KeyboardModifier.ControlModifier, Qt.MouseButton.LeftButton),
    (False, Qt.KeyboardModifier.NoModifier, Qt.MouseButton.RightButton),
    (False, Qt.KeyboardModifier.NoModifier, Qt.MouseButton.MiddleButton),
])
def test_sidebar_button_keeps_clicks_and_manual_ctrl_or_other_buttons_cannot_drag(qapp, manual, modifiers, button):
    row = PageMarkerRow(123, manual=manual)
    layout = QVBoxLayout(row)
    child = QPushButton("Marker")
    layout.addWidget(child)
    row.watch_drag(child)
    row.resize(200, 100)
    row.show()
    qapp.processEvents()
    clicks, drags = [], []
    child.clicked.connect(lambda: clicks.append(True))
    row.drag_requested.connect(drags.append)
    point = QPoint(10, 10)
    QTest.mouseClick(child, button, modifiers, pos=point)
    assert clicks == ([True] if button == Qt.MouseButton.LeftButton else [])
    if manual or modifiers or button != Qt.MouseButton.LeftButton:
        QTest.mousePress(child, button, modifiers, pos=point)
        _move(child, point, QPoint(60, 0), buttons=button)
        QTest.mouseRelease(child, button, pos=point)
        assert drags == []
    row.close()


def _group_event(panel, point, kind, frames):
    mime = marker_mime(99, "review", frames=frames)
    if kind == "enter":
        event = QDragEnterEvent(point, Qt.DropAction.MoveAction, mime,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    else:
        event = QDropEvent(QPointF(point), Qt.DropAction.MoveAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    event._test_mime = mime
    QApplication.sendEvent(panel, event)
    return event


def test_page_drop_passes_all_frames_to_one_batch_operation_and_keeps_insertion_line(qapp):
    panel, owner, moves = _panel(qapp)
    owner._proposal = lambda frame: {"frame": frame} if frame in (99, 98) else None
    owner._move_markers_to_page = lambda *args: moves.append(args) or True
    child = owner._rows[101]["children"].layout().itemAt(0).widget()
    point = _point(panel, child, 2)
    assert _group_event(panel, point, "enter", [98, 99]).isAccepted()
    assert panel._drop_target_info[:2] == (101, 40)
    assert panel._drop_frames == [98, 99]
    assert panel._drop_indicator.isVisible()
    assert _group_event(panel, point, "drop", [98, 99]).isAccepted()
    assert moves == [([98, 99], 101, 40)]
    assert panel._drop_frames is None
    assert not panel._drop_scroll_timer.isActive()
    panel.close()


def test_a_stale_group_member_aborts_drop_and_autoscroll_without_partial_move(qapp):
    panel, owner, moves = _panel(qapp, many=True)
    owner._proposal = lambda frame: {"frame": frame} if frame in (99, 98) else None
    owner._move_markers_to_page = lambda *args: moves.append(args) or True
    point = _point(panel, owner._rows[100]["row"])
    assert _group_event(panel, point, "enter", [99, 98]).isAccepted()
    owner._proposal = lambda frame: {"frame": frame} if frame == 99 else None
    panel._scroll_drop_target()
    assert panel._drop_frames is None
    assert not panel._drop_scroll_timer.isActive()
    assert not _group_event(panel, point, "drop", [99, 98]).isAccepted()
    assert moves == []
    panel.close()


def test_legacy_single_only_owner_never_silently_moves_part_of_a_group(qapp):
    panel, owner, moves = _panel(qapp)
    owner._proposal = lambda frame: {"frame": frame}
    point = _point(panel, owner._rows[100]["row"])
    assert not _group_event(panel, point, "enter", [99, 98]).isAccepted()
    assert not _group_event(panel, point, "drop", [99, 98]).isAccepted()
    assert moves == []
    panel.close()

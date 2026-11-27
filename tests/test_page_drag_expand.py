"""A sustained marker drag can open a page without selecting or editing it."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from tests.test_page_reorder_ui import _reading_order, _window
from vispa_mp.review_drag import marker_mime


def settle(qapp):
    for _ in range(6):
        qapp.processEvents()


@pytest.fixture
def review(qapp):
    windows = []

    def create(mode="strip"):
        window = _window(mode, manual=True)
        windows.append(window)
        window.resize(1600, 1000)
        window.show()
        window._choose_frame(50, False)
        window._toggle_frame_selection(60, False)
        window._resolve_timer.stop()
        settle(qapp)
        window.pages_panel._drop_expand_timer.setInterval(40)
        window._project_dirty = False
        assert window.open_pages == set()
        return window

    yield create
    for window in windows:
        window.worker = None
        window._learning_job_busy = False
        window._project_dirty = False
        window._resolve_timer.stop()
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def point_for(window, widget, y=None):
    local = QPoint(widget.width() // 2, widget.height() // 2 if y is None else y)
    return window.pages_panel.mapFromGlobal(widget.mapToGlobal(local))


def send_drag(window, kind, point, *, token=None):
    mime = marker_mime(50, token or window._drag_token, frames=[50, 60])
    if kind == "enter":
        event = QDragEnterEvent(point, Qt.DropAction.MoveAction, mime,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    elif kind == "move":
        event = QDragMoveEvent(point, Qt.DropAction.MoveAction, mime,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    else:
        event = QDropEvent(QPointF(point), Qt.DropAction.MoveAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    event._test_mime = mime
    QApplication.sendEvent(window.pages_panel, event)
    return event


def state_without_open_pages(window):
    return deepcopy((window.proposals, window.snapshot, window.analysis["manual_frames"],
                     window._page_layout, window._selected_keys, window.selected_frame,
                     window.selected_manual, window.selected_page_id, window._project_dirty,
                     window.undo_stack.count(), window.undo_stack.index()))


def hover_header(window, page_id=10):
    point = point_for(window, window._rows[page_id]["row"])
    assert send_drag(window, "enter", point).isAccepted()
    assert window.pages_panel._drop_expand_timer.isActive()
    assert window.pages_panel._drop_expand_page_id == page_id
    return point


def test_a_closed_page_opens_only_after_the_hover_delay_without_editing_or_selecting(qapp, review):
    window = review()
    before = state_without_open_pages(window)
    hover_header(window)
    QTest.qWait(10)
    assert 10 not in window.open_pages
    assert window._rows[10]["children"].isHidden()
    QTest.qWait(80)
    assert 10 in window.open_pages
    assert window._rows[10]["children"].isVisible()
    assert window._rows[10]["row"].property("dropTarget") is True
    assert window.pages_panel._drop_indicator.isHidden()
    assert not window.pages_panel._drop_expand_timer.isActive()
    assert state_without_open_pages(window) == before


def test_small_moves_over_the_same_header_do_not_restart_the_expansion_delay(qapp, review):
    window = review()
    panel = window.pages_panel
    panel._drop_expand_timer.setInterval(60)
    point = hover_header(window)
    QTest.qWait(20)
    remaining = panel._drop_expand_timer.remainingTime()
    assert remaining > 0
    assert send_drag(window, "move", point + QPoint(2, 0)).isAccepted()
    assert panel._drop_expand_timer.remainingTime() <= remaining + 2
    QTest.qWait(remaining + 25)
    assert 10 in window.open_pages


def test_moving_to_another_closed_header_restarts_the_delay_for_that_page_only(qapp, review):
    window = review()
    panel = window.pages_panel
    panel._drop_expand_timer.setInterval(60)
    before = state_without_open_pages(window)
    hover_header(window)
    QTest.qWait(20)
    assert send_drag(window, "move", point_for(window, window._rows[40]["row"])).isAccepted()
    assert panel._drop_expand_page_id == 40
    assert panel._drop_expand_timer.remainingTime() > 40
    QTest.qWait(20)
    assert window.open_pages == set()
    QTest.qWait(70)
    assert window.open_pages == {40}
    assert state_without_open_pages(window) == before


@pytest.mark.parametrize("cancel", ["leave", "hide", "child", "foreign", "outside", "busy", "learning", "stale"])
def test_cancelled_hover_never_opens_the_old_target(qapp, review, cancel):
    window = review()
    panel = window.pages_panel
    if cancel == "child":
        window._toggle_page(40)
        settle(qapp)
    hover_header(window)
    if cancel == "leave":
        QApplication.sendEvent(panel, QDragLeaveEvent())
    elif cancel == "hide":
        panel.hide()
    elif cancel == "child":
        child = window.findChild(QPushButton, "marker-40").parentWidget()
        assert send_drag(window, "move", point_for(window, child, 2)).isAccepted()
        assert panel._drop_indicator.isVisible()
    elif cancel == "foreign":
        assert not send_drag(window, "move", point_for(window, window._rows[10]["row"]),
                             token="another-review").isAccepted()
    elif cancel == "outside":
        send_drag(window, "move", QPoint(-20, -20))
    elif cancel == "busy":
        window.worker = object()
    elif cancel == "learning":
        window._learning_job_busy = True
    else:
        window.proposals = [proposal for proposal in window.proposals if proposal["frame"] != 60]
    before = state_without_open_pages(window)
    QTest.qWait(90)
    assert 10 not in window.open_pages
    assert window._rows[10]["children"].isHidden()
    assert not panel._drop_expand_timer.isActive()
    assert panel._drop_expand_page_id is None
    assert state_without_open_pages(window) == before


def test_an_already_open_page_is_not_toggled_closed_by_a_long_hover(qapp, review, monkeypatch):
    window = review()
    window._toggle_page(10)
    settle(qapp)
    before = state_without_open_pages(window)
    calls = []
    original_toggle = window._toggle_page
    monkeypatch.setattr(window, "_toggle_page", lambda page_id:
                        calls.append(page_id) or original_toggle(page_id))
    point = point_for(window, window._rows[10]["row"])
    assert send_drag(window, "enter", point).isAccepted()
    QTest.qWait(90)
    assert 10 in window.open_pages
    assert window._rows[10]["children"].isVisible()
    assert calls == []
    assert not window.pages_panel._drop_expand_timer.isActive()
    assert state_without_open_pages(window) == before


def test_a_drop_before_the_delay_keeps_the_destination_collapsed(qapp, review):
    window = review()
    point = hover_header(window)
    assert send_drag(window, "drop", point).isAccepted()
    QTest.qWait(90)
    assert 10 not in window.open_pages
    assert _reading_order(window) == [(10, [10, 20, 30, 50, 60]), (40, [40])]
    assert not window.pages_panel._drop_expand_timer.isActive()
    assert window.pages_panel._drop_expand_page_id is None
    assert window.undo_stack.count() == 1


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_a_hover_opened_page_accepts_a_precise_group_insertion(qapp, review, mode):
    window = review(mode)
    before = state_without_open_pages(window)
    hover_header(window)
    QTest.qWait(90)
    assert 10 in window.open_pages
    assert state_without_open_pages(window) == before
    target = window.findChild(QPushButton, "marker-20").parentWidget()
    point = point_for(window, target, 2)
    assert send_drag(window, "move", point).isAccepted()
    assert window.pages_panel._drop_target_info[:2] == (10, 20)
    assert window.pages_panel._drop_indicator.isVisible()
    assert not window._rows[10]["row"].property("dropTarget")
    assert send_drag(window, "drop", point).isAccepted()
    assert _reading_order(window) == [(10, [10, 50, 60, 20, 30]), (40, [40])]
    assert window._selected_keys == {(50, False), (60, False)}
    assert window.analysis["manual_frames"] == [15]
    assert window.undo_stack.count() == 1
    assert not window.pages_panel._drop_expand_timer.isActive()
    assert window.pages_panel._drop_expand_page_id is None

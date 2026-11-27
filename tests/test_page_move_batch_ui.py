"""Move a selected reading-order block through the real review drag gestures."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from tests.test_page_reorder_ui import _reading_order, _send_move, _source_point, _window
from vispa_mp.project import load_project
from vispa_mp.review_drag import marker_mime
from vispa_mp.ui import item_frame


def settle(qapp):
    for _ in range(8):
        qapp.processEvents()


@pytest.fixture
def review(qapp):
    windows = []

    def create(mode="strip", *, manual=False):
        window = _window(mode, manual=manual)
        windows.append(window)
        window.resize(1600, 1000)
        window.show()
        window.activateWindow()
        settle(qapp)
        return window

    yield create
    for window in windows:
        window.worker = None
        window._project_dirty = False
        window._resolve_timer.stop()
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


@pytest.mark.parametrize("mode", ["strip", "board"])
@pytest.mark.parametrize("before,expected", [
    (None, [10, 20, 30, 50, 60]),
    (20, [10, 50, 60, 20, 30]),
])
def test_move_a_batch_appends_or_inserts_and_refreshes_the_central_view(qapp, review, mode, before, expected):
    window = review(mode, manual=True)
    window._choose_frame(60, False)
    window._toggle_frame_selection(50, False)
    proposals, snapshot, payload = deepcopy((window.proposals, window.snapshot, window.resolve_payload()))

    assert window._move_markers_to_page([60, 50], 10, before)
    settle(qapp)

    assert _reading_order(window) == [(10, expected), (40, [40])]
    assert window.selected_page_id == 10
    assert window._selected_keys == {(50, False), (60, False)}
    assert window.proposals == proposals
    assert window.snapshot == snapshot
    assert window.analysis["manual_frames"] == [15]
    assert window.resolve_payload() == payload
    assert all(15 not in group["frames"] for group in window._page_layout)
    if mode == "strip":
        cards = [window.thumb_layout.itemAt(index).widget()
                 for index in range(window.thumb_layout.count())]
        assert [card.frame for card in cards if not card.manual] == expected
    else:
        window.board.grab()
        assert [item_frame(item) for _rect, item in window.board._hits if not item["manual"]] == expected


def test_same_page_batch_reorder_keeps_the_selected_images_in_reading_order(qapp, review):
    window = review()
    assert window._move_markers_to_page([20, 10], 10)
    assert _reading_order(window) == [(10, [30, 10, 20]), (40, [40, 50, 60])]


def test_a_batch_uses_manual_reading_order_instead_of_frame_or_click_order(qapp, review):
    window = review()
    window._page_layout = [{"id": 10, "frames": [30, 10, 20]}, {"id": 40, "frames": [40, 50, 60]}]
    window._fill()
    assert window._move_markers_to_page([20, 30], 40, before_frame=50)
    assert _reading_order(window) == [(10, [10]), (40, [40, 30, 20, 50, 60])]


def test_inserting_before_an_image_in_the_batch_keeps_the_original_insertion_position(qapp, review):
    window = review()
    assert window._move_markers_to_page([50, 20], 10, before_frame=20)
    assert _reading_order(window) == [(10, [10, 20, 50, 30]), (40, [40, 60])]


def test_dropping_an_existing_block_at_its_own_position_is_a_noop(qapp, review):
    window = review()
    before = _reading_order(window)
    count = window.undo_stack.count()
    assert not window._move_markers_to_page([30, 20], 10, before_frame=20)
    assert _reading_order(window) == before
    assert window._page_layout is None
    assert window.undo_stack.count() == count
    assert window._project_dirty is False


def test_batch_move_is_one_undo_action_and_redo_restores_the_whole_block(qapp, review):
    window = review(manual=True)
    window._choose_frame(50, False)
    window._toggle_frame_selection(60, False)
    before = _reading_order(window)
    proposals, snapshot, payload = deepcopy((window.proposals, window.snapshot, window.resolve_payload()))
    count = window.undo_stack.count()
    assert window._move_markers_to_page([60, 50], 10, before_frame=20)
    moved = _reading_order(window)
    assert window.undo_stack.count() == count + 1
    window._undo_review()
    assert _reading_order(window) == before
    assert window._page_layout is None
    assert window._selected_keys == {(50, False), (60, False)}
    window._redo_review()
    assert _reading_order(window) == moved
    assert window.undo_stack.count() == count + 1
    assert window._selected_keys == {(50, False), (60, False)}
    assert window.proposals == proposals
    assert window.snapshot == snapshot
    assert window.resolve_payload() == payload


def test_saved_batch_arrangement_reloads_without_reanalysis_or_moving_resolve_markers(qapp, review, tmp_path, monkeypatch):
    original = review("board", manual=True)
    assert original._move_markers_to_page([60, 50], 10, before_frame=20)
    order, payload = _reading_order(original), original.resolve_payload()
    path = tmp_path / "batch-arrangement.vispamp"
    assert original.save_project_file(path)
    project = load_project(path, tmp_path / "restored-cache")
    restored = review()
    monkeypatch.setattr(restored, "recompute", lambda:
                        pytest.fail("A saved reading-order block must be restored without recalculation"))
    restored._restore_project(project, deepcopy(original.snapshot), None, path)
    assert _reading_order(restored) == order
    assert restored.resolve_payload() == payload
    assert restored.analysis["manual_frames"] == [15]
    assert restored.mode == "board"
    assert restored._project_dirty is False


def select_nonchronological_group(qapp, window):
    window._page_layout = [{"id": 10, "frames": [10, 20, 30]}, {"id": 40, "frames": [60, 40, 50]}]
    window._fill()
    window._choose_frame(60, False)
    window._toggle_frame_selection(50, False)
    settle(qapp)
    assert window._selected_keys == {(60, False), (50, False)}


def drag_to_first_page(qapp, window, monkeypatch):
    calls, keepalive = [], []

    def perform_drop(widget, frame, token, pixmap=None, *, frames=None):
        calls.append((frame, list(frames or [])))
        assert widget is window and token == window._drag_token
        assert frame == 50 and frames == [60, 50]
        header = window._rows[10]["row"]
        point = window.pages_panel.mapFromGlobal(header.mapToGlobal(header.rect().center()))
        mime = marker_mime(frame, token, frames=frames)
        keepalive.append(mime)
        before_hover = deepcopy((window.proposals, window._page_layout, window._selected_keys,
                                 window.selected_frame, window.selected_page_id))
        enter = QDragEnterEvent(point, Qt.DropAction.MoveAction, mime,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(window.pages_panel, enter)
        assert enter.isAccepted()
        assert window.pages_panel._drop_target_info[:2] == (10, None)
        assert window.pages_panel._drop_indicator.isHidden()
        assert header.property("dropTarget") is True
        hint = header.findChild(QLabel, "page-drop-hint-10")
        assert hint is not None and hint.isVisible()
        assert (window.proposals, window._page_layout, window._selected_keys,
                window.selected_frame, window.selected_page_id) == before_hover
        drop = QDropEvent(QPointF(point), Qt.DropAction.MoveAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(window.pages_panel, drop)
        assert drop.isAccepted()
        assert not header.property("dropTarget")
        assert hint.isHidden()
        return Qt.DropAction.MoveAction

    monkeypatch.setattr("vispa_mp.ui.start_marker_drag", perform_drop)
    return calls


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_dragging_a_selected_central_image_keeps_the_batch_until_drop(qapp, review, monkeypatch, mode):
    window = review(mode)
    select_nonchronological_group(qapp, window)
    calls = drag_to_first_page(qapp, window, monkeypatch)
    source, point = _source_point(window, 50)
    assert source.rect().contains(point)
    QTest.mousePress(source, Qt.MouseButton.LeftButton, pos=point)
    assert window._selected_keys == {(60, False), (50, False)}
    _send_move(source, point + QPoint(QApplication.startDragDistance() + 18, 0), Qt.MouseButton.LeftButton)
    QTest.mouseRelease(source, Qt.MouseButton.LeftButton, pos=point)
    settle(qapp)
    assert calls == [(50, [60, 50])]
    assert _reading_order(window) == [(10, [10, 20, 30, 60, 50]), (40, [40])]
    assert window._selected_keys == {(60, False), (50, False)}


@pytest.mark.parametrize("source_part", ["row", "button"])
def test_sidebar_row_and_name_start_one_group_drag_only_after_the_threshold(qapp, review, monkeypatch, source_part):
    window = review()
    select_nonchronological_group(qapp, window)
    if 40 not in window.open_pages:
        window._toggle_page(40)
    settle(qapp)
    button = window.findChild(QPushButton, "marker-50")
    assert button is not None and button.isVisible()
    source = button if source_part == "button" else button.parentWidget()
    window.pages_scroll.ensureWidgetVisible(source)
    settle(qapp)
    calls = drag_to_first_page(qapp, window, monkeypatch)
    point = source.rect().center()
    QTest.mousePress(source, Qt.MouseButton.LeftButton, pos=point)
    assert window._selected_keys == {(60, False), (50, False)}
    _send_move(source, point + QPoint(max(1, QApplication.startDragDistance() // 2), 0), Qt.MouseButton.LeftButton)
    assert calls == []
    _send_move(source, point + QPoint(QApplication.startDragDistance() + 18, 0), Qt.MouseButton.LeftButton)
    QTest.mouseRelease(source, Qt.MouseButton.LeftButton, pos=point)
    settle(qapp)
    assert calls == [(50, [60, 50])]
    assert _reading_order(window) == [(10, [10, 20, 30, 60, 50]), (40, [40])]
    assert window._selected_keys == {(60, False), (50, False)}


def test_manual_selection_is_not_included_in_a_proposal_drag(qapp, review, monkeypatch):
    window = review(manual=True)
    window._choose_frame(50, False)
    window._toggle_frame_selection(15, True)
    original = deepcopy((window.snapshot, window.analysis["manual_frames"]))
    calls = []
    monkeypatch.setattr("vispa_mp.ui.start_marker_drag",
                        lambda _widget, frame, _token, _pixmap=None, *, frames=None:
                        calls.append((frame, frames)) or Qt.DropAction.IgnoreAction)
    window._begin_marker_drag(50)
    assert calls == [(50, [50])]
    assert (window.snapshot, window.analysis["manual_frames"]) == original


def test_click_without_drag_still_replaces_a_previous_batch_selection(qapp, review):
    window = review()
    select_nonchronological_group(qapp, window)
    source, point = _source_point(window, 50)
    QTest.mouseClick(source, Qt.MouseButton.LeftButton, pos=point)
    settle(qapp)
    assert window._selected_keys == {(50, False)}

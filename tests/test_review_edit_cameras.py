"""Suggestion edits preserve the viewed region of the same comic page."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest

from tests.test_page_reorder_ui import _window
from tests.test_review_cameras import _assert_camera, _pan_strip, _settle
from vispa_mp.markers import CORE, EXTRA, PAGE


@pytest.fixture
def review(qapp):
    windows = []

    def create():
        window = _window(mode="board", manual=True)
        windows.append(window)
        frames = window.analysis["shots"][0]["frames"]
        frames.extend({"frame": number, "sharpness": 100, "image": "", "open_mouth": 0.2,
                       "closed_mouth": 0.5} for number in (12, 14, 22, 27, 35))
        frames.sort(key=lambda frame: frame["frame"])
        window._fill()
        window.resize(1500, 1000)
        window.show()
        window.activateWindow()
        _settle(qapp)
        window._open_suggestions(20, False)
        window.set_suggestions_height(280)
        _settle(qapp)
        return window

    yield create
    for window in windows:
        window._project_dirty = False
        window._resolve_timer.stop()
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def zoom_pan_board(window, qapp):
    point = QPointF(window.board.rect().center())
    window.board.wheelEvent(QWheelEvent(point, point, QPoint(), QPoint(0, 360),
                                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                       Qt.ScrollPhase.NoScrollPhase, False))
    point = window.board.rect().center()
    QTest.mousePress(window.board, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(window.board, point + QPoint(-79, 47))
    QTest.mouseRelease(window.board, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier,
                       point + QPoint(-79, 47))
    _settle(qapp)
    camera = window.get_review_cameras()["board"]
    assert camera["zoom"] > 1
    assert window.board.offset != QPointF()
    return camera


def assert_board_camera(window, expected, qapp):
    _assert_camera(window._capture_review_camera("board"), expected)
    _settle(qapp)
    _assert_camera(window.get_review_cameras()["board"], expected)
    assert window._review_camera_edit is None


def test_preview_selection_keeps_the_board_zoom_and_pan(qapp, review):
    window = review()
    expected = zoom_pan_board(window, qapp)
    window._select_suggestion(25)
    assert window._preview == 25
    assert_board_camera(window, expected, qapp)
    window._select_suggestion(12)
    assert_board_camera(window, expected, qapp)


def test_replacement_preserves_camera_immediately_and_after_the_flash_timer(qapp, review):
    window = review()
    expected = zoom_pan_board(window, qapp)
    original_source = deepcopy(window.snapshot)
    window._use_suggestion(25)
    assert window.selected_frame == 25
    assert_board_camera(window, expected, qapp)
    QTest.qWait(750)
    assert window._flash is None
    assert_board_camera(window, expected, qapp)
    assert window.snapshot == original_source


@pytest.mark.parametrize("color", [CORE, EXTRA])
@pytest.mark.parametrize("numbers", [[25], [22, 25, 27]])
def test_single_and_batch_additions_preserve_the_same_page_camera(qapp, review, color, numbers):
    window = review()
    expected = zoom_pan_board(window, qapp)
    assert window._add_suggestion_markers(numbers, color) == len(numbers)
    assert window.selected_frame == 20 and window.selected_page_id == 10
    assert_board_camera(window, expected, qapp)
    assert all(window._proposal(number)["color"] == color for number in numbers)


def test_repeated_replacement_of_the_page_start_retains_its_logical_page_camera(qapp, review):
    window = review()
    window._open_suggestions(10, False)
    _settle(qapp)
    expected = zoom_pan_board(window, qapp)

    for replacement in (12, 14):
        window._use_suggestion(replacement)
        assert window.selected_page_id == replacement
        assert window._proposal(replacement)["origin_frame"] == 10
        assert_board_camera(window, expected, qapp)
        window._end_flash()
        assert_board_camera(window, expected, qapp)


@pytest.mark.parametrize("active_mode", ["strip", "board"])
def test_edit_keeps_both_the_active_and_hidden_view_cameras(qapp, review, active_mode):
    window = review()
    board = zoom_pan_board(window, qapp)
    window._set_mode("strip")
    _settle(qapp)
    window._zoom_thumbs(4)
    _pan_strip(window)
    _settle(qapp)
    strip = window.get_review_cameras()["strip"]
    window._set_mode(active_mode)
    _settle(qapp)

    assert window._add_suggestion_markers([25], EXTRA) == 1
    _settle(qapp)
    cameras = window.get_review_cameras()
    _assert_camera(cameras["strip"], strip)
    _assert_camera(cameras["board"], board)
    for mode, expected in (("board", board), ("strip", strip)):
        window._set_mode(mode)
        _settle(qapp)
        _assert_camera(window.get_review_cameras()[mode], expected)


def test_undo_and_redo_preserve_the_current_view_instead_of_an_old_saved_camera(qapp, review):
    window = review()
    zoom_pan_board(window, qapp)
    window._open_suggestions(10, False)
    window._use_suggestion(12)
    _settle(qapp)
    expected = zoom_pan_board(window, qapp)

    assert window._undo_review()
    assert window.selected_page_id == 10
    assert_board_camera(window, expected, qapp)
    assert window._redo_review()
    assert window.selected_page_id == 12
    assert_board_camera(window, expected, qapp)


@pytest.mark.parametrize("change", ["page", "filter", "analysis"])
def test_another_page_filter_or_analysis_keeps_normal_fit_behavior(qapp, review, change):
    window = review()
    zoom_pan_board(window, qapp)

    if change == "page":
        window._choose_frame(50, False)
    elif change == "filter":
        window._set_filter("core")
    elif change == "analysis":
        window.show_analysis(deepcopy(window.analysis))
    _settle(qapp)

    assert window.board.zoom == 1.0
    assert window.board.offset == QPointF()
    assert window._review_camera_edit is None


@pytest.mark.parametrize("view_filter,color", [("core", EXTRA), ("starts", EXTRA), ("starts", CORE)])
def test_an_additions_automatic_filter_change_keeps_the_viewed_region(qapp, review, view_filter, color):
    window = review()
    window._set_filter(view_filter)
    _settle(qapp)
    expected = zoom_pan_board(window, qapp)
    assert window._add_suggestion_markers([25], color) == 1
    assert window.view_filter == "all"
    assert_board_camera(window, expected, qapp)


def test_starting_a_different_page_does_not_inherit_the_old_page_camera(qapp, review):
    window = review()
    zoom_pan_board(window, qapp)
    assert window._add_suggestion_markers([12], PAGE) == 1
    assert window.selected_page_id == 12
    _settle(qapp)
    assert window.board.zoom == 1.0
    assert window.board.offset == QPointF()

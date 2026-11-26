"""Each view keeps its own focus, including while the other view is resized."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest

from tests.test_strip_canvas import _review
from tests.test_project_ui import _client, _review as _project_review, _worker_inline
from vispa_mp.ui import MainWindow, Message


def _settle(qapp):
    for _ in range(5):
        qapp.processEvents()


def _board_wheel(window, steps=2):
    point = QPointF(window.board.rect().center())
    window.board.wheelEvent(QWheelEvent(point, point, QPoint(), QPoint(0, 120 * steps),
                                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                       Qt.ScrollPhase.NoScrollPhase, False))


def _pan_strip(window):
    viewport = window.thumb_area.viewport()
    point = viewport.rect().center()
    QTest.mousePress(viewport, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(viewport, point + QPoint(63, 41))
    QTest.mouseRelease(viewport, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, point + QPoint(63, 41))


def _assert_camera(actual, expected, tolerance=0.01):
    assert actual["zoom"] == pytest.approx(expected["zoom"]) if expected["zoom"] is not None else actual["zoom"] is None
    assert actual["center"] == pytest.approx(expected["center"], abs=tolerance)
    if "columns" in expected:
        assert actual["columns"] == expected["columns"]


def test_switching_modes_keeps_each_zoom_and_focus_independently(qapp):
    window = _review(qapp)
    _settle(qapp)
    window._zoom_thumbs(4)
    _pan_strip(window)
    strip = window.get_review_cameras()["strip"]
    proposals = deepcopy(window.proposals)
    window._set_mode("board")
    _settle(qapp)
    _board_wheel(window, 3)
    point = window.board.rect().center()
    QTest.mousePress(window.board, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(window.board, point + QPoint(-45, 38))
    QTest.mouseRelease(window.board, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, point + QPoint(-45, 38))
    board = window.get_review_cameras()["board"]
    for _ in range(4):
        window._set_mode("strip")
        _settle(qapp)
        _assert_camera(window.get_review_cameras()["strip"], strip)
        window._set_mode("board")
        _settle(qapp)
        _assert_camera(window.get_review_cameras()["board"], board)
    assert window.proposals == proposals


def test_resizing_the_other_mode_does_not_replace_the_hidden_camera(qapp):
    window = _review(qapp)
    _settle(qapp)
    window._zoom_thumbs(4)
    _pan_strip(window)
    strip = window.get_review_cameras()["strip"]
    window._set_mode("board")
    _settle(qapp)
    _board_wheel(window)
    board = window.get_review_cameras()["board"]
    window._open_suggestions(30, False)
    window.set_suggestions_height(350)
    window.resize(1800, 750)
    _settle(qapp)
    _assert_camera(window.get_review_cameras()["board"], board)
    window._set_mode("strip")
    _settle(qapp)
    _assert_camera(window.get_review_cameras()["strip"], strip)


def test_an_immediate_zoom_is_not_undone_by_a_pending_mode_restore(qapp):
    window = _review(qapp)
    _settle(qapp)
    window._zoom_thumbs(3)
    saved = window._thumb_zoom
    window._set_mode("board")
    _settle(qapp)
    window._set_mode("strip")
    window._zoom_thumbs(2)
    expected = saved * 1.15 ** 2
    _settle(qapp)
    assert window._thumb_zoom == pytest.approx(expected)
    window._set_mode("board")
    _board_wheel(window, 2)
    _settle(qapp)
    assert window.board.zoom == pytest.approx(1.2 ** 2)


def test_fit_mode_remembers_a_pan_and_only_user_navigation_marks_the_project_dirty(qapp):
    window = _review(qapp)
    _settle(qapp)
    window._project_dirty = False
    _pan_strip(window)
    assert window._project_dirty
    strip = window.get_review_cameras()["strip"]
    assert strip["zoom"] is None
    window._project_dirty = False
    window._set_mode("board")
    _settle(qapp)
    window._set_mode("strip")
    _settle(qapp)
    _assert_camera(window.get_review_cameras()["strip"], strip)
    assert window._project_dirty is False


def test_a_later_project_camera_replaces_an_older_pending_restore(qapp):
    window = _review(qapp)
    _settle(qapp)
    first = {"strip": {"zoom": 260.0, "center": [0.1, 0.2], "columns": 4}, "board": None}
    last = {"strip": {"zoom": 330.0, "center": [0.6, 0.7], "columns": 3}, "board": None}
    window.set_review_cameras(first)
    window.set_review_cameras(last)
    _settle(qapp)
    _assert_camera(window.get_review_cameras()["strip"], last["strip"])


@pytest.mark.parametrize("active_mode", ["strip", "board"])
def test_project_cameras_survive_loading_before_the_window_is_shown(qapp, tmp_path, monkeypatch, active_mode):
    original = _project_review(qapp, tmp_path)
    original.resize(1600, 900)
    original.show()
    _settle(qapp)
    original.set_review_cameras({"strip": {"zoom": 310.0, "center": [0.2, 0.8], "columns": 1},
                                 "board": {"zoom": 2.6, "center": [-0.1, 0.7]}})
    for mode in ("board", "strip", active_mode):
        original._set_mode(mode)
        _settle(qapp)
    expected = original.get_review_cameras()
    path = tmp_path / "hidden-load.vispamp"
    assert original.save_project_file(path)
    restored = MainWindow(client=_client(original.snapshot))
    restored.resize(1700, 800)
    _worker_inline(restored, monkeypatch)
    monkeypatch.setattr(restored, "_cache_dir", lambda: tmp_path / "reloaded-cache")
    monkeypatch.setattr(Message, "tell", lambda *args: pytest.fail(str(args[1:])))
    restored.open_project_file(path)
    _settle(qapp)
    assert not restored.isVisible()
    for mode in ("strip", "board"):
        _assert_camera(restored.get_review_cameras()[mode], expected[mode])
    restored.show()
    _settle(qapp)
    for mode in ("strip", "board", active_mode):
        restored._set_mode(mode)
        _settle(qapp)
        _assert_camera(restored.get_review_cameras()[mode], expected[mode])

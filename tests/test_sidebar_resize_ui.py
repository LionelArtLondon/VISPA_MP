"""The two sidebars resize independently without changing the marker review."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest

from tests.test_page_reorder_ui import _window
from tests.test_review_cameras import _assert_camera, _pan_strip, _settle
from tests.test_review_edit_cameras import zoom_pan_board
from tests.test_review_workspace_layout import layout_fonts
from vispa_mp.preset import load_user


@pytest.fixture
def review(qapp, layout_fonts):
    windows = []

    def create():
        window = _window(mode="board", manual=True)
        windows.append(window)
        window.resize(1500, 1000)
        window.show()
        window.activateWindow()
        _settle(qapp)
        return window

    yield create
    for window in windows:
        window._project_dirty = False
        window._resolve_timer.stop()
        window._save_timer.stop()
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def drag_handle(window, index, delta, qapp):
    handle = window.workspace_splitter.handle(index)
    point = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(handle, point + QPoint(delta, 0))
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, handle.rect().center())
    _settle(qapp)


@pytest.mark.parametrize("index,delta", [(1, 75), (2, -65)])
def test_native_sidebar_drag_preserves_review_and_default_widths(qapp, review, index, delta):
    window = review()
    assert window.workspace_splitter.count() == 3
    assert window.pages_panel.width() == window.review_adjust.width() == 280
    window._choose_frame(10, False)
    window._toggle_frame_selection(20, False)
    selected = set(window._selected_keys)
    proposals = deepcopy(window.proposals)
    before = window.workspace_splitter.sizes()
    history = window.undo_stack.index()
    drag_handle(window, index, delta, qapp)
    after = window.workspace_splitter.sizes()
    side = 0 if index == 1 else 2
    assert after[side] > before[side] + 40
    assert after[1] < before[1] - 40
    assert window.proposals == proposals
    assert window._selected_keys == selected
    assert window.undo_stack.index() == history
    assert not window._project_dirty
    window.strip_button.click()
    _settle(qapp)
    assert window.workspace_splitter.sizes() == after


def test_both_sidebars_can_shrink_and_right_controls_reflow_without_clipping(qapp, review):
    window = review()
    window._choose_format("Custom")
    window.frame_format_box.setCurrentText("Custom")
    window.selection_profile_panel.sidebar_toggle.click()
    window.workspace_splitter.moveSplitter(window.workspace_splitter.width() - 248, 2)
    window.workspace_splitter.moveSplitter(180, 1)
    _settle(qapp)
    assert window.workspace_splitter.sizes()[0] == 180
    assert window.workspace_splitter.sizes()[2] == 240
    assert window.review_tool_controls.width() <= window.review_tools_scroll.viewport().width()
    controls = [*window.filter_buttons.values(), *window.format_buttons.values(), window.width_box,
                window.height_box, window.frame_format_box, window.frame_width_box, window.frame_height_box]
    for control in controls:
        window.review_tools_scroll.ensureWidgetVisible(control, 0, 0)
        _settle(qapp)
        origin = control.mapTo(window.review_tools_scroll.viewport(), QPoint())
        assert origin.x() >= 0
        assert origin.x() + control.width() <= window.review_tools_scroll.viewport().width()
    window.workspace_splitter.moveSplitter(0, 1)
    window.workspace_splitter.moveSplitter(window.workspace_splitter.width(), 2)
    assert all(size > 0 for size in window.workspace_splitter.sizes())


def test_sidebar_widths_return_after_restart_without_becoming_project_edits(qapp, review):
    window = review()
    drag_handle(window, 1, 70, qapp)
    drag_handle(window, 2, -60, qapp)
    expected = window.pages_panel.width(), window.review_adjust.width()
    window.save_settings()
    _settings, preferences = load_user()
    assert (preferences["pages_panel_width"], preferences["review_tools_width"]) == expected
    again = review()
    assert (again.pages_panel.width(), again.review_adjust.width()) == expected
    assert not window._project_dirty and not again._project_dirty


def test_resizing_preserves_both_zoomed_and_panned_view_cameras(qapp, review):
    window = review()
    zoom_pan_board(window, qapp)
    window.strip_button.click()
    _settle(qapp)
    window._zoom_thumbs(4)
    _pan_strip(window)
    _settle(qapp)
    window.board_button.click()
    _settle(qapp)
    cameras = deepcopy(window.get_review_cameras())
    window._project_dirty = False
    drag_handle(window, 1, 70, qapp)
    drag_handle(window, 2, -60, qapp)
    _assert_camera(window.get_review_cameras()["board"], cameras["board"])
    window.strip_button.click()
    _settle(qapp)
    _assert_camera(window.get_review_cameras()["strip"], cameras["strip"])
    assert not window._project_dirty

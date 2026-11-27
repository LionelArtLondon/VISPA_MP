"""Workspace dividers have a clear drag state without a narrow hit target."""

import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from vispa_mp.preset import load, load_user, save_user
from vispa_mp.review_panes import WorkspaceSplitter, WorkspaceSplitterHandle
from vispa_mp.ui_tokens import ACCENT, BORDER_ROW, PANEL_BG, SEPARATOR


@pytest.fixture
def workspace(qapp):
    splitter = WorkspaceSplitter()
    for width in (180, 320, 240):
        pane = QWidget()
        pane.setMinimumWidth(width)
        splitter.addWidget(pane)
    for index, stretch in enumerate((0, 1, 0)):
        splitter.setStretchFactor(index, stretch)
    splitter.resize(1200, 400)
    splitter.setSizes([280, 624, 280])
    splitter.show()
    qapp.processEvents()
    yield splitter
    splitter.close()
    splitter.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def _line_pixels(handle):
    image = handle.grab().toImage()
    return [image.pixelColor(x, image.height() // 2) for x in range(image.width())]


def test_handle_has_an_eight_pixel_target_but_only_a_two_pixel_visible_line(qapp, workspace):
    for index in (1, 2):
        handle = workspace.handle(index)
        assert isinstance(handle, WorkspaceSplitterHandle)
        assert handle.width() == 8
        assert handle.cursor().shape() == Qt.CursorShape.SplitHCursor
        QCoreApplication.sendEvent(handle, QEvent(QEvent.Type.Leave))
        colors = _line_pixels(handle)
        assert colors.count(QColor(BORDER_ROW)) == 2
        assert colors.count(QColor(PANEL_BG)) == 6
    assert not workspace.childrenCollapsible()


def test_handle_hover_and_press_change_the_line_then_release_restores_hover(qapp, workspace):
    handle = workspace.handle(1)
    point = handle.rect().center()
    location = QPointF(point)
    entered = QEnterEvent(location, location, QPointF(handle.mapToGlobal(point)))
    QCoreApplication.sendEvent(handle, entered)
    assert _line_pixels(handle).count(QColor(SEPARATOR)) == 2
    seen = []
    workspace.resize_started.connect(lambda: seen.append("start"))
    workspace.resize_finished.connect(lambda: seen.append("finish"))
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    assert _line_pixels(handle).count(QColor(ACCENT)) == 2
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    assert _line_pixels(handle).count(QColor(SEPARATOR)) == 2
    assert seen == ["start", "finish"]


@pytest.mark.parametrize("handle_index,delta", [(1, 65), (2, -65)])
def test_native_drag_changes_the_adjacent_sidebar_and_keeps_all_panes_open(qapp, workspace, handle_index, delta):
    handle = workspace.handle(handle_index)
    point = handle.rect().center()
    before = workspace.sizes()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(handle, point + QPoint(delta, 0))
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, handle.rect().center())
    qapp.processEvents()
    after = workspace.sizes()
    assert after[0 if handle_index == 1 else 2] > before[0 if handle_index == 1 else 2] + 40
    assert after[1] < before[1] - 40
    assert all(after[index] >= workspace.widget(index).minimumWidth() for index in range(3))
    assert sum(after) == sum(before)


def test_hiding_a_pressed_handle_clears_the_active_state_once(qapp, workspace):
    handle = workspace.handle(1)
    seen = []
    workspace.resize_started.connect(lambda: seen.append("start"))
    workspace.resize_finished.connect(lambda: seen.append("finish"))
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, handle.rect().center())
    workspace.hide()
    qapp.processEvents()
    assert seen == ["start", "finish"]
    assert not handle._pressed


def test_workspace_width_preferences_round_trip_as_local_view_values(user_settings):
    settings, view = load_user()
    assert view["pages_panel_width"] == view["review_tools_width"] == 280
    view.update(pages_panel_width=320, review_tools_width=360)
    save_user(settings, view)
    stored = json.loads(user_settings.read_text(encoding="utf-8"))
    assert stored == {"pages_panel_width": 320, "review_tools_width": 360}
    restored_settings, restored = load_user()
    assert restored_settings == load()
    assert restored["pages_panel_width"] == 320 and restored["review_tools_width"] == 360


@pytest.mark.parametrize("value", [True, False, 0, -280, 159, 2001, 280.5, "320", None])
def test_invalid_workspace_width_preferences_are_ignored_on_load_and_save(user_settings, value):
    user_settings.write_text(json.dumps({"pages_panel_width": value, "review_tools_width": value}), encoding="utf-8")
    settings, view = load_user()
    assert view["pages_panel_width"] == view["review_tools_width"] == 280
    save_user(settings, {"pages_panel_width": value, "review_tools_width": value})
    assert not user_settings.exists()

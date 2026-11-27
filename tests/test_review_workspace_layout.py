"""Review tools use the sidebar while the canvases keep the available height."""

from copy import deepcopy
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QLabel

from tests.test_page_reorder_ui import _window
from tests.test_review_cameras import _assert_camera, _settle
from tests.test_review_edit_cameras import zoom_pan_board


@pytest.fixture
def layout_fonts(qapp):
    """Windows offscreen Qt can start without fonts and invent monospace widths."""
    loaded = []
    if not QFontDatabase.families():
        folder = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "seguisb.ttf", "segoeuib.ttf"):
            path = folder / name
            if path.is_file():
                identifier = QFontDatabase.addApplicationFont(str(path))
                if identifier >= 0:
                    loaded.append(identifier)
        if not QFontDatabase.families():
            pytest.skip("Workspace geometry needs a real font rather than Qt's missing-font metrics.")
    yield
    for identifier in reversed(loaded):
        QFontDatabase.removeApplicationFont(identifier)


@pytest.fixture
def review(qapp, layout_fonts):
    windows = []

    def create(size=(1600, 1000), mode="board"):
        window = _window(mode=mode, manual=True)
        windows.append(window)
        window.resize(*size)
        window.show()
        window.activateWindow()
        _settle(qapp)
        return window

    yield create
    for window in windows:
        window.worker = None
        window._learning_job_busy = False
        window._project_dirty = False
        window._resolve_timer.stop()
        window._save_timer.stop()
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def rectangle_in(widget, parent):
    return QRect(widget.mapTo(parent, QPoint()), widget.size())


@pytest.mark.parametrize("size", [(1600, 1000), (1280, 800)])
def test_board_uses_the_height_under_the_ruler_without_widening_the_window(review, size):
    window = review(size)
    board = rectangle_in(window.board_scroll.viewport(), window)
    assert window.width() == size[0] and window.height() == size[1]
    assert window.review_adjust.width() == 280
    assert window.pages_panel.width() == 280
    assert board.top() < 250, board
    assert board.height() > window.height() - 290, board
    assert board.width() >= window.width() - 650, board
    assert window.review_center.layout().count() == 2
    assert window.timeline_panel.isAncestorOf(window.ruler)
    assert window.ruler.height() == 94
    assert not window.review_center.isAncestorOf(window.selection_profile_panel)
    assert not window.review_center.isAncestorOf(window.mode_switches)


@pytest.mark.parametrize("size", [(1600, 1000), (1280, 800)])
def test_view_tools_belong_to_the_right_sidebar_and_need_no_horizontal_scrolling(qapp, review, size):
    window = review(size)
    sidebar, tools, scroll = window.review_adjust, window.review_tool_controls, window.review_tools_scroll
    assert sidebar.isAncestorOf(window.selection_profile_panel)
    assert sidebar.isAncestorOf(scroll) and scroll.widget() is tools
    controls = [window.strip_button, window.board_button, *window.filter_buttons.values(),
                *window.format_buttons.values(), *window.orientation_buttons.values(), window.width_box,
                window.height_box, window.frame_format_box, window.board_labels_check,
                window.preview_quality_box, window.suggestions_button, window.automatic_order_button,
                window.review_report_button]
    assert all(tools.isAncestorOf(control) for control in controls)
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert scroll.horizontalScrollBar().maximum() == 0
    assert tools.width() <= scroll.viewport().width(), (
        tools.width(), scroll.viewport().width(), tools.minimumSizeHint())
    assert window._move_marker_to_page(30, 10, before_frame=20)
    window.frame_format_box.setCurrentText("Custom")
    _settle(qapp)
    controls += [window.frame_width_box, window.frame_height_box]
    for control in controls:
        assert control.isVisible(), control.objectName()
        scroll.ensureWidgetVisible(control, 0, 0)
        _settle(qapp)
        rect = rectangle_in(control, scroll.viewport())
        assert scroll.viewport().rect().contains(rect), (
            control.objectName() or getattr(control, "text", lambda: type(control).__name__)(),
            rect, scroll.viewport().rect())


@pytest.mark.parametrize("size", [(1600, 1000), (1280, 800)])
def test_adjust_stays_below_scrolling_tools_with_small_tightly_captioned_swatches(review, size):
    window = review(size)
    scroll = rectangle_in(window.review_tools_scroll, window.review_adjust)
    sharpness = rectangle_in(window.widgets["sharpness_floor"], window.review_adjust)
    assert sharpness.top() > scroll.bottom()
    assert window.recalculate_button.isVisible()
    assert window.review_adjust.rect().contains(rectangle_in(window.recalculate_button, window.review_adjust))
    for button in window.color_buttons.values():
        assert 18 <= button.width() <= 20 and 18 <= button.height() <= 20
        box = button.parentWidget().layout()
        # The swatch's vertical box is nested in its parent's form layout.
        caption = next(label for label in button.parentWidget().findChildren(QLabel)
                       if label.text() == button.toolTip())
        gap = caption.mapTo(window.review_adjust, QPoint()).y() - (
            button.mapTo(window.review_adjust, QPoint()).y() + button.height())
        assert 0 <= gap <= 6, (button.toolTip(), gap, box)


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_panel_counters_overlay_the_canvas_without_reserving_a_row(review, mode):
    window = review(mode=mode)
    counter = window.strip_panel_counter if mode == "strip" else window.board_panel_counter
    canvas = window.thumb_area.viewport() if mode == "strip" else window.board
    assert counter.parentWidget() is canvas
    assert counter.isVisible()
    assert counter.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert counter.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert canvas.rect().contains(counter.geometry())
    assert counter.pos() == QPoint(10, 10)


def test_sidebar_expansion_scrolling_and_noop_controls_keep_the_review_camera(qapp, review):
    window = review()
    expected = zoom_pan_board(window, qapp)
    proposals = deepcopy(window.proposals)
    selection = window.selected_frame, window.selected_page_id, set(window._selected_keys)
    canvas = rectangle_in(window.board_scroll.viewport(), window)

    for _ in range(2):
        window.selection_profile_panel.sidebar_toggle.click()
        _settle(qapp)
        assert rectangle_in(window.board_scroll.viewport(), window) == canvas
    scroll = window.review_tools_scroll
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    window._set_filter(window.view_filter)
    window._choose_format(window.page_format)
    window._set_preview_quality(window.preview_quality)
    window.strip_button.click()
    _settle(qapp)
    window.board_button.click()
    _settle(qapp)

    _assert_camera(window.get_review_cameras()["board"], expected)
    assert window.proposals == proposals
    assert (window.selected_frame, window.selected_page_id, window._selected_keys) == selection

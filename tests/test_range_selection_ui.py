"""Shift selects source-time ranges consistently across the review surfaces."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from tests.test_page_reorder_ui import _window
from tests.test_ui import action_analysis
from vispa_mp.markers import CORE, EXTRA
from vispa_mp.review_drag import MarkerDragCard
from vispa_mp.ui import item_frame


SHIFT = Qt.KeyboardModifier.ShiftModifier
CTRL = Qt.KeyboardModifier.ControlModifier
NONE = Qt.KeyboardModifier.NoModifier


@pytest.fixture
def review(qapp):
    windows = []

    def create(surface="strip", *, manual=False):
        window = _window("board" if surface == "board" else "strip", manual=manual)
        windows.append(window)
        window.resize(1500, 950)
        window.show()
        window.activateWindow()
        qapp.processEvents()
        return window

    yield create
    for window in windows:
        window._project_dirty = False
        window._resolve_timer.stop()
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def click(qapp, window, surface, frame, *, manual=False, modifiers=NONE):
    if surface == "pages":
        page_id, _, _ = window._find(frame, manual)
        if page_id not in window.open_pages:
            window._toggle_page(page_id)
        button = window.findChild(QPushButton, f"manual-{frame}" if manual else f"marker-{frame}")
        assert button is not None
        window.pages_scroll.ensureWidgetVisible(button)
        qapp.processEvents()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton, modifiers, button.rect().center())
    elif surface == "strip":
        card = window.thumb_area.widget().findChild(MarkerDragCard, f"thumb-{frame}-{'m' if manual else 'a'}")
        assert card is not None
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, modifiers, QPoint(8, 8))
    else:
        window.board.grab()
        rect = next(rect for rect, item in window.board._hits
                    if item_frame(item) == frame and bool(item["manual"]) == manual)
        QTest.mouseClick(window.board, Qt.MouseButton.LeftButton, modifiers, rect.center())
    qapp.processEvents()


@pytest.mark.parametrize("surface", ["strip", "board", "pages"])
def test_shift_range_reverses_and_repeats_from_the_original_anchor(qapp, review, surface):
    window = review(surface)
    click(qapp, window, surface, 20)
    click(qapp, window, surface, 30, modifiers=SHIFT)
    assert window._selected_keys == {(20, False), (30, False)}
    assert window._range_anchor_key == (20, False)
    click(qapp, window, surface, 10, modifiers=SHIFT)
    assert window._selected_keys == {(10, False), (20, False)}
    assert window._range_anchor_key == (20, False)
    click(qapp, window, surface, 30, modifiers=SHIFT)
    assert window._selected_keys == {(20, False), (30, False)}


@pytest.mark.parametrize("surface", ["strip", "board", "pages"])
def test_ctrl_shift_adds_a_range_and_shift_replaces_the_selection(qapp, review, surface):
    window = review(surface)
    click(qapp, window, surface, 10)
    click(qapp, window, surface, 30, modifiers=CTRL)
    assert window._range_anchor_key == (30, False)
    click(qapp, window, surface, 20, modifiers=CTRL | SHIFT)
    assert window._selected_keys == {(10, False), (20, False), (30, False)}
    click(qapp, window, surface, 20, modifiers=SHIFT)
    assert window._selected_keys == {(20, False), (30, False)}


@pytest.mark.parametrize("surface", ["strip", "board", "pages"])
def test_manual_markers_are_included_but_bulk_edits_keep_them_read_only(qapp, review, surface):
    window = review(surface, manual=True)
    snapshot = deepcopy(window.snapshot)
    click(qapp, window, surface, 10)
    click(qapp, window, surface, 30, modifiers=SHIFT)
    assert window._selected_keys == {(10, False), (15, True), (20, False), (30, False)}
    window._set_marker_color(EXTRA)
    assert all(window._proposal(frame)["color"] == EXTRA for frame in (10, 20, 30))
    assert window.analysis["manual_frames"] == [15]
    assert window.snapshot == snapshot


@pytest.mark.parametrize("surface", ["strip", "board", "pages"])
def test_ranges_follow_source_time_after_editorial_reordering(qapp, review, surface):
    window = review(surface)
    assert window._move_marker_to_page(50, 10, before_frame=20)
    click(qapp, window, surface, 10)
    click(qapp, window, surface, 30, modifiers=SHIFT)
    assert window._selected_keys == {(10, False), (20, False), (30, False)}
    click(qapp, window, surface, 30)
    click(qapp, window, surface, 50, modifiers=SHIFT)
    assert window._selected_keys == {(30, False), (40, False), (50, False)}


@pytest.mark.parametrize("surface", ["strip", "board"])
def test_page_start_filter_selects_only_chronological_page_starts(qapp, review, surface):
    window = review(surface, manual=True)
    window._set_filter("starts")
    qapp.processEvents()
    click(qapp, window, surface, 10)
    click(qapp, window, surface, 40, modifiers=SHIFT)
    assert window._selected_keys == {(10, False), (40, False)}


def test_core_preview_range_excludes_extras_and_manual_markers_across_pages(qapp, review):
    window = review(manual=True)
    window._set_filter("core")
    window._choose_frame(10, False)
    window._select_frame_range(50, False)
    assert window._selected_keys == {(10, False), (20, False), (40, False), (50, False)}


def test_pages_tree_range_includes_visible_rows_independent_of_preview_filter(qapp, review):
    window = review(manual=True)
    window._set_filter("core")
    click(qapp, window, "pages", 30)
    click(qapp, window, "pages", 15, manual=True, modifiers=SHIFT)
    assert window._selected_keys == {(15, True), (20, False), (30, False)}
    assert window.view_filter == "core"


def test_shift_page_header_targets_its_first_image_and_arrow_only_expands(qapp, review):
    window = review(manual=True)
    click(qapp, window, "pages", 20)
    header = window.findChild(QPushButton, "page-name-40")
    QTest.mouseClick(header, Qt.MouseButton.LeftButton, SHIFT, header.rect().center())
    qapp.processEvents()
    assert window._selected_keys == {(20, False), (30, False), (40, False)}
    before = (set(window._selected_keys), window._range_anchor_key)
    arrow = window._rows[40]["arrow"]
    QTest.mouseClick(arrow, Qt.MouseButton.LeftButton, SHIFT, arrow.rect().center())
    qapp.processEvents()
    assert (window._selected_keys, window._range_anchor_key) == before


@pytest.mark.parametrize("surface", ["strip", "board"])
def test_filtered_out_anchor_restarts_at_the_clicked_image(qapp, review, surface):
    window = review(surface)
    click(qapp, window, surface, 30)
    window._set_filter("core")
    qapp.processEvents()
    click(qapp, window, surface, 20, modifiers=SHIFT)
    assert window._selected_keys == {(20, False)}
    assert window._range_anchor_key == (20, False)


def test_ctrl_deselected_image_remains_the_next_range_anchor(qapp, review):
    window = review()
    click(qapp, window, "strip", 10)
    click(qapp, window, "strip", 30, modifiers=CTRL)
    click(qapp, window, "strip", 30, modifiers=CTRL)
    assert window._selected_keys == {(10, False)}
    click(qapp, window, "strip", 20, modifiers=SHIFT)
    assert window._selected_keys == {(20, False), (30, False)}


def test_range_selection_preserves_redo_and_does_not_dirty_the_project(qapp, review):
    window = review()
    window._set_proposal_color(20, EXTRA)
    assert window._undo_review()
    assert window.undo_stack.canRedo()
    before = (window.undo_stack.count(), window.undo_stack.index())
    window._project_dirty = False
    click(qapp, window, "strip", 10)
    click(qapp, window, "strip", 30, modifiers=SHIFT)
    assert (window.undo_stack.count(), window.undo_stack.index()) == before
    assert window.undo_stack.canRedo()
    assert window._project_dirty is False


def test_undo_restores_the_range_anchor_for_the_next_shift_click(qapp, review):
    window = review()
    click(qapp, window, "strip", 20)
    click(qapp, window, "strip", 30, modifiers=SHIFT)
    window._set_marker_color(CORE)
    click(qapp, window, "strip", 10)
    assert window._range_anchor_key == (10, False)
    assert window._undo_review()
    assert window._range_anchor_key == (20, False)
    click(qapp, window, "strip", 10, modifiers=SHIFT)
    assert window._selected_keys == {(10, False), (20, False)}


def test_new_analysis_resets_the_previous_range_anchor(qapp, review):
    window = review()
    click(qapp, window, "strip", 30)
    window.show_analysis(action_analysis())
    assert window._range_anchor_key == (22, False)

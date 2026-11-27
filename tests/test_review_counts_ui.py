"""The two canvas overlays follow review edits, filters and undo immediately."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt

from tests.test_page_reorder_ui import _window
from vispa_mp.markers import CORE, EXTRA
from vispa_mp.review_counts import PanelCounter


def settle(qapp):
    for _ in range(5):
        qapp.processEvents()


@pytest.fixture
def review(qapp):
    windows = []

    def create(mode="strip", manual=True):
        window = _window(mode, manual=manual)
        windows.append(window)
        window.resize(1600, 1000)
        window.show()
        settle(qapp)
        window._project_dirty = False
        return window

    yield create
    for window in windows:
        window.worker = None
        window._project_dirty = False
        window._resolve_timer.stop()
        window._save_timer.stop()
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def assert_counts(window, primary, secondary):
    for counter in (window.strip_panel_counter, window.board_panel_counter):
        assert counter.primary.text() == primary
        assert counter.secondary.text() == secondary


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_count_is_a_mouse_transparent_canvas_overlay_without_an_extra_layout_row(review, mode):
    window = review(mode)
    assert isinstance(window.strip_panel_counter, PanelCounter)
    assert isinstance(window.board_panel_counter, PanelCounter)
    assert window.strip_panel_counter.parentWidget() is window.thumb_area.viewport()
    assert window.board_panel_counter.parentWidget() is window.board
    active = window.strip_panel_counter if mode == "strip" else window.board_panel_counter
    assert active.isVisible()
    assert active.pos().x() == active.pos().y() == 10
    assert active.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert active.parentWidget().layout() is None
    assert_counts(window, "4 panels", "2 Core")


def test_strip_counter_stays_in_the_viewport_corner_while_zooming_and_panning(qapp, review):
    window = review()
    counter = window.strip_panel_counter
    window._zoom_thumbs(4)
    settle(qapp)
    assert counter.pos().x() == counter.pos().y() == 10
    for bar in (window.thumb_area.horizontalScrollBar(), window.thumb_area.verticalScrollBar()):
        bar.setValue(bar.value() + 75)
    settle(qapp)
    assert counter.pos().x() == counter.pos().y() == 10
    assert counter.isVisible()
    assert_counts(window, "4 panels", "2 Core")


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_filters_and_page_selection_show_visible_counts_with_global_starts_core_total(qapp, review, mode):
    window = review(mode)
    assert_counts(window, "4 panels", "2 Core")
    window._set_filter("core")
    assert_counts(window, "2 Core", "4 incl. Extras")
    window._set_filter("starts")
    assert_counts(window, "2 Page starts", "4 Core")
    assert "All panels: 7" in window.board_panel_counter.toolTip()
    assert "Manual Resolve markers: 1" in window.board_panel_counter.toolTip()
    window._set_filter("all")
    window._choose_frame(50, False)
    settle(qapp)
    assert_counts(window, "3 panels", "2 Core")
    window._set_mode("board" if mode == "strip" else "strip")
    settle(qapp)
    assert_counts(window, "3 panels", "2 Core")


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_counts_follow_add_delete_and_undo_redo_while_manual_markers_stay_in_all(review, mode):
    window = review(mode)
    window._choose_frame(20, False)
    assert_counts(window, "4 panels", "2 Core")
    assert window._add_suggestion_marker(25, EXTRA)
    assert_counts(window, "5 panels", "2 Core")
    window._undo_review()
    assert_counts(window, "4 panels", "2 Core")
    window._delete_marker_proposal(30)
    assert_counts(window, "3 panels", "2 Core")
    window._undo_review()
    assert_counts(window, "4 panels", "2 Core")
    window._redo_review()
    assert_counts(window, "3 panels", "2 Core")
    assert "Manual Resolve markers: 1" in window.strip_panel_counter.toolTip()


def test_role_and_page_order_edits_refresh_counters_as_one_undoable_action(review):
    window = review()
    window._choose_frame(20, False)
    assert window._move_markers_to_page([50, 60], 10)
    assert_counts(window, "6 panels", "3 Core")
    window._undo_review()
    assert_counts(window, "4 panels", "2 Core")
    window._set_proposal_color(30, CORE)
    assert_counts(window, "4 panels", "3 Core")
    window._undo_review()
    assert_counts(window, "4 panels", "2 Core")
    window._set_filter("starts")
    window._set_proposal_color(40, CORE)
    assert_counts(window, "1 Page starts", "4 Core")
    window._undo_review()
    assert_counts(window, "2 Page starts", "4 Core")


def test_refreshing_counts_only_reads_the_review_and_preserves_sources_selection_and_cameras(
        qapp, review, monkeypatch):
    window = review()
    window.set_review_cameras({"strip": {"zoom": 310.0, "center": [0.3, 0.7], "columns": 2},
                               "board": {"zoom": 2.1, "center": [0.4, 0.6]}})
    settle(qapp)
    before = deepcopy((window.analysis, window.proposals, window.resolve_payload(),
                       window.get_review_cameras(), window._selected_keys, window._project_dirty))

    def forbidden(*_args, **_kwargs):
        pytest.fail("Updating panel counts must not recalculate or rebuild the review")

    for name in ("recompute", "run_analysis", "_fill", "_refresh_center"):
        monkeypatch.setattr(window, name, forbidden)
    monkeypatch.setattr("vispa_mp.ui.analyze", forbidden)
    window._update_panel_counts()
    assert_counts(window, "4 panels", "2 Core")
    assert (window.analysis, window.proposals, window.resolve_payload(), window.get_review_cameras(),
            window._selected_keys, window._project_dirty) == before


def test_clearing_the_review_resets_both_counter_overlays_to_zero(review):
    window = review()
    assert_counts(window, "4 panels", "2 Core")
    window.show_analysis(None)
    assert_counts(window, "0 panels", "0 Core")

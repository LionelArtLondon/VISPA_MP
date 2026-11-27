"""The diagnostic report is a live read-only view of the current preparation."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QScrollArea

from tests.test_page_reorder_ui import _window
from vispa_mp.ui import MainWindow


def settle(qapp):
    for _ in range(6):
        qapp.processEvents()


@pytest.fixture
def review(qapp):
    windows = []

    def create(*, prepared=True):
        window = _window() if prepared else MainWindow(client=None)
        windows.append(window)
        window._ready = False
        window.set_setting("global_markers_enabled", False)
        window._ready = True
        window._update_global_marker_budget_summary()
        window._show_warnings()
        window.resize(1600, 1000)
        window.show()
        window._resolve_timer.stop()
        settle(qapp)
        window._project_dirty = False
        return window

    yield create
    for window in windows:
        window.worker = None
        window._project_dirty = False
        window.review_report_dialog.close()
        window._resolve_timer.stop()
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def preparation_state(window):
    return deepcopy((window.snapshot, window.analysis, window.proposals, window.settings(),
                     window._selected_keys, window.selected_frame, window.selected_page_id,
                     window.playhead_frame, window._page_layout, window._project_dirty,
                     window.undo_stack.count(), window.undo_stack.index()))


def forbid_work(window, monkeypatch):
    def fail(*_args, **_kwargs):
        pytest.fail("Opening or refreshing the report must not read, analyze or write Resolve")

    for name in ("read_timeline", "run_analysis", "write_markers", "recompute", "_start"):
        monkeypatch.setattr(window, name, fail)


def test_report_button_opens_one_nonmodal_dialog_and_never_edits_the_preparation(qapp, review, monkeypatch):
    window = review()
    assert window.review_report_button.text() == "Analysis details"
    assert not window.review_report_button.property("hasWarnings")
    dialog = window.review_report_dialog
    assert dialog.isAncestorOf(window.warnings)
    assert dialog.isAncestorOf(window.marker_budget_summary)
    assert not window.warnings.isVisible() and not window.marker_budget_summary.isVisible()
    before = preparation_state(window)
    forbid_work(window, monkeypatch)
    window.review_report_button.click()
    settle(qapp)
    assert dialog.isVisible() and not dialog.isModal()
    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert window.marker_budget_summary.isVisible()
    assert window.review_report_empty.isVisible()
    assert preparation_state(window) == before
    dialog.close()
    settle(qapp)
    assert not window.marker_budget_summary.isVisible()
    window.review_report_button.click()
    assert window.review_report_dialog is dialog
    assert preparation_state(window) == before


def test_report_is_available_before_analysis_without_starting_an_operation(qapp, review, monkeypatch):
    window = review(prepared=False)
    forbid_work(window, monkeypatch)
    window.review_report_button.click()
    settle(qapp)
    assert window.review_report_dialog.isVisible()
    assert "waiting" in window.marker_budget_summary.text().lower()
    assert window.analysis is None and window.proposals == []
    assert not window._project_dirty


def test_full_warning_details_keep_each_page_diagnostic_without_changing_the_folded_label(qapp, review):
    window = review()
    detailed = [f"Page at frame {frame}: 1 Core images, 1 in all, below the minimum."
                for frame in (10, 20, 30)]
    window.rule_warnings = detailed
    window.analysis["warnings"] = ["A <source> & its media are offline."]
    window._show_warnings()
    folded, tooltip = window.warnings.text(), window.warnings.toolTip()
    assert window.review_report_button.property("warningCount") == 4
    assert window.review_report_button.property("hasWarnings") is True
    assert window.review_report_button.text() == "Analysis details (4)"
    assert not window.warnings.isVisible()
    before = preparation_state(window)
    window.review_report_button.click()
    settle(qapp)
    assert window.warnings.text() == folded and window.warnings.toolTip() == tooltip
    assert window.review_report_warning_details.isVisible()
    assert window.review_report_warning_details.textFormat() == Qt.TextFormat.PlainText
    for line in [*detailed, *window.analysis["warnings"]]:
        assert line in window.review_report_warning_details.text()
    assert preparation_state(window) == before


def test_open_report_updates_from_current_warnings_and_budget_without_reopening(qapp, review, monkeypatch):
    window = review()
    window.review_report_button.click()
    dialog = window.review_report_dialog
    forbid_work(window, monkeypatch)
    window.analysis["warnings"] = ["The linked source is offline."]
    window._show_warnings()
    window.marker_budget_summary.setText("Markers: 12 · target about 30 (12–45)")
    window.marker_budget_review_warnings = ["18 below the target."]
    window.marker_budget_summary.setToolTip("18 below the target.")
    before = preparation_state(window)
    window._sync_review_report()
    settle(qapp)
    assert window.review_report_dialog is dialog and dialog.isVisible()
    assert window.marker_budget_summary.text() == "Markers: 12 · target about 30 (12–45)"
    assert window.review_report_warning_details.text().splitlines() == [
        "The linked source is offline.", "18 below the target."]
    assert window.review_report_button.property("warningCount") == 2
    assert "Markers: 12" in window.review_report_button.toolTip()
    assert preparation_state(window) == before
    window.analysis["warnings"] = []
    window.marker_budget_review_warnings = []
    window.marker_budget_summary.setToolTip("")
    window._show_warnings()
    assert window.review_report_button.text() == "Analysis details"
    assert not window.review_report_button.property("hasWarnings")
    assert window.review_report_empty.isVisible()
    assert not window.review_report_warning_details.isVisible()


def test_report_context_tracks_the_current_source_and_close_keeps_diagnostics(qapp, review):
    window = review()
    window.analysis["project_name"] = "New Resolve project"
    window.analysis["timeline_name"] = "Personal Learning"
    window.analysis["warnings"] = ["Keep this diagnostic available."]
    window._show_warnings()
    window.review_report_button.click()
    settle(qapp)
    assert window.review_report_source.text() == "New Resolve project · Personal Learning"
    original = window.warnings.text(), window.warnings.toolTip()
    window.review_report_dialog.close()
    settle(qapp)
    assert not window.warnings.isVisible()
    assert (window.warnings.text(), window.warnings.toolTip()) == original
    assert window.review_report_button.property("warningCount") == 1
    assert not window._project_dirty


def test_many_diagnostics_stay_in_a_scrollable_report_and_the_button_stays_compact(qapp, review):
    window = review()
    lines = [f"Source diagnostic {index}: linked image metadata requires review." for index in range(100)]
    window.analysis["warnings"] = lines
    window._show_warnings()
    window.review_report_button.click()
    settle(qapp)
    assert window.review_report_button.text() == "Analysis details (100)"
    assert len(window.review_report_button.text()) < 30
    assert window.warnings.text().splitlines() == lines
    scroll = window.review_report_dialog.findChild(QScrollArea)
    assert scroll is not None and scroll.verticalScrollBar().maximum() > 0
    assert window.warnings.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse

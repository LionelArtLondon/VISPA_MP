"""Detached suggestions remain the same editing pane, with optional auto-open."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from tests.test_ui import action_analysis, item_frame, three_page_analysis
from vispa_mp.markers import EXTRA
from vispa_mp.ui import MainWindow


def settle(qapp):
    for _ in range(5):
        qapp.processEvents()


@pytest.fixture
def suggestions_review(qapp):
    window = MainWindow(client=None)
    window.set_setting("action_extras", 0)
    window.set_setting("episode_minutes", 0)
    window.show_analysis(action_analysis())
    window.resize(1400, 860)
    window.show()
    settle(qapp)
    window._project_dirty = False
    yield window
    window.worker = None
    window._project_dirty = False
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_default_keeps_single_selection_closed_and_double_click_opens(suggestions_review, qapp):
    window = suggestions_review
    assert not window.suggestions_auto_open
    assert not window.suggestions_auto_check.isChecked()
    window._choose_frame(22, False)
    assert not window._suggestions_open and window.suggestion_area.isHidden()
    window._open_suggestions(22, False)
    settle(qapp)
    assert window._suggestions_open and window.suggestion_area.isVisible()
    assert set(window._suggestion_cards) == {2, 12, 22}


def test_restoring_a_project_reopens_live_detached_suggestions_without_recomputing(qapp, tmp_path, monkeypatch):
    from tests.test_project_ui import _review
    monkeypatch.setattr("vispa_mp.project_location.LOCATION_PATH", tmp_path / "locations.json")
    source = _review(qapp, tmp_path)
    source._set_suggestions_auto_open(True)
    source._detach_suggestions()
    project = {"snapshot": deepcopy(source.snapshot), "analysis": deepcopy(source.analysis),
               "proposals": deepcopy(source.proposals), "settings": source.settings(), "view": source._project_view()}
    restored = MainWindow()
    monkeypatch.setattr(restored, "recompute", lambda: pytest.fail("Restoring display preferences must keep reviewed markers"))
    try:
        restored._restore_project(project, project["snapshot"], None, tmp_path / "review.vispamp")
        settle(qapp)
        assert restored.suggestions_auto_open and restored.suggestions_detached
        assert restored.suggestions_window.centralWidget() is restored.suggestion_panel
        assert restored.suggestions_window.isVisible() and restored._suggestion_cards
        assert restored.selected_frame == source.selected_frame
        assert restored.proposals == source.proposals
    finally:
        for window in (source, restored):
            window._project_dirty = False
            window.close()
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_automatic_open_follows_selected_images_and_pages(suggestions_review, qapp, mode):
    window = suggestions_review
    window.show_analysis(three_page_analysis())
    window._set_mode(mode)
    window._set_suggestions_auto_open(True)
    assert window.suggestions_auto_open and window.suggestions_auto_check.isChecked()
    proposals = [item for page in window.pages for item in page["items"] if not item["manual"]]
    first = proposals[0]
    window._choose_frame(item_frame(first), False)
    settle(qapp)
    assert window._suggestions_open and window.suggestion_area.isVisible()
    initial = set(window._suggestion_cards)
    other = next(item for item in proposals if item_frame(item) >= 200)
    window._choose_frame(item_frame(other), False)
    settle(qapp)
    assert window._suggestions_open and set(window._suggestion_cards) != initial
    assert set(window._suggestion_cards) == {frame["frame"] for frame in window._suggestion_frames()}
    window._select_page(window.pages[-1]["id"])
    settle(qapp)
    assert window._suggestions_open
    assert set(window._suggestion_cards) == {frame["frame"] for frame in window._suggestion_frames()}


def test_auto_open_does_not_invent_suggestions_for_manual_markers(suggestions_review, qapp):
    window = suggestions_review
    window.show_analysis(three_page_analysis())
    window._set_suggestions_auto_open(True)
    proposal = next(item for page in window.pages for item in page["items"] if not item["manual"])
    window._choose_frame(item_frame(proposal), False)
    assert window._suggestions_open
    window._choose_frame(190, True)
    settle(qapp)
    assert window.selected_manual and window._suggestion_frames() == []
    assert not window._suggestions_open


def test_detached_auto_window_stays_visible_with_an_explanation_for_manual_markers(suggestions_review, qapp):
    window = suggestions_review
    window.show_analysis(three_page_analysis())
    window._set_suggestions_auto_open(True)
    proposal = next(item for page in window.pages for item in page["items"] if not item["manual"])
    window._choose_frame(item_frame(proposal), False)
    window._detach_suggestions()
    window._choose_frame(190, True)
    settle(qapp)
    assert window.suggestions_window.isVisible()
    assert window.suggestion_area.isVisible() and window._suggestion_cards == {}
    assert not window._suggestions_open
    assert any("hand-placed marker" in label.text().lower() for label in window.suggestion_area.findChildren(QLabel))


def test_detaching_moves_one_shared_panel_and_close_redocks_it(suggestions_review, qapp):
    window = suggestions_review
    window._open_suggestions(22, False)
    window.set_suggestions_height(290)
    settle(qapp)
    height = window.get_suggestions_height()
    panel, area, layout = window.suggestion_panel, window.suggestion_area, window.suggestion_layout
    before = deepcopy((window.analysis, window.proposals, window.selected_frame))
    window._detach_suggestions()
    settle(qapp)
    floating = window.suggestions_window
    assert window.suggestions_detached and floating.isVisible()
    assert floating.centralWidget() is panel
    assert window.suggestion_area is area and window.suggestion_layout is layout
    assert window.review_splitter.indexOf(panel) == -1
    assert (window.analysis, window.proposals, window.selected_frame) == before
    floating.close()
    settle(qapp)
    assert not window.suggestions_detached and not floating.isVisible()
    assert window.review_splitter.indexOf(panel) == 1
    assert abs(window.get_suggestions_height() - height) <= 3
    window._detach_suggestions()
    settle(qapp)
    assert window.suggestions_window is floating and floating.isVisible()


def test_detached_window_height_grows_previews_without_recreating_cards(suggestions_review, qapp):
    window = suggestions_review
    window._open_suggestions(22, False)
    window._detach_suggestions()
    floating = window.suggestions_window
    floating.resize(1100, 450)
    settle(qapp)
    cards = dict(window._suggestion_cards)
    picture = next(iter(cards.values()))._suggestion_picture
    before = picture.height()
    floating.resize(1100, 700)
    settle(qapp)
    assert picture.height() > before + 150
    assert window._suggestion_cards == cards
    assert window.suggestion_area.horizontalScrollBar().maximum() > 0


def test_detached_suggestions_still_replace_and_add_markers_locally(suggestions_review, monkeypatch, qapp):
    window = suggestions_review

    def forbidden(*_args, **_kwargs):
        pytest.fail("Using already extracted suggestions must not contact Resolve or run image analysis")

    monkeypatch.setattr("vispa_mp.client.open_client", forbidden)
    monkeypatch.setattr("vispa_mp.ui.open_client", forbidden)
    monkeypatch.setattr(window, "run_analysis", forbidden)
    window._open_suggestions(22, False)
    window._detach_suggestions()
    settle(qapp)
    measured = deepcopy(window.analysis)
    window._use_suggestion(12)
    assert window._proposal(12) is not None and window._proposal(22) is None
    menu = window._suggestion_menu(2)
    next(action for action in menu.actions() if action.text() == "Add Extra marker").trigger()
    assert window._proposal(2)["color"] == EXTRA and window._proposal(12) is not None
    assert window.analysis == measured and window.client is None
    assert window.suggestions_window.isVisible() and window.suggestions_detached


def test_detached_keyboard_previews_and_keeps_the_same_selection(suggestions_review, qapp):
    window = suggestions_review
    window._open_suggestions(22, False)
    window._detach_suggestions()
    floating = window.suggestions_window
    floating.activateWindow()
    floating.raise_()
    QTest.qWait(20)
    qapp.setActiveWindow(floating)
    QTest.keyClick(floating, Qt.Key.Key_Left)
    settle(qapp)
    assert window._preview == 12 and window._proposal(22) is not None
    QTest.keyClick(floating, Qt.Key.Key_Return)
    settle(qapp)
    assert window.selected_frame == 12 and window._proposal(12) is not None
    assert window._proposal(22) is None


def test_fullscreen_escape_keeps_the_detached_panel_and_pending_preview(suggestions_review, qapp):
    window = suggestions_review
    window._open_suggestions(22, False)
    window._detach_suggestions()
    floating = window.suggestions_window
    window._preview = 12
    floating.toggle_fullscreen()
    floating.activateWindow()
    QTest.qWait(20)
    qapp.setActiveWindow(floating)
    assert floating.isFullScreen()
    QTest.keyClick(floating, Qt.Key.Key_Escape)
    settle(qapp)
    assert not floating.isFullScreen()
    assert window.suggestions_detached and floating.centralWidget() is window.suggestion_panel
    assert window._preview == 12


def test_floating_editing_is_disabled_while_the_source_is_busy(suggestions_review, qapp):
    window = suggestions_review
    window._open_suggestions(22, False)
    window._detach_suggestions()
    floating = window.suggestions_window
    floating.activateWindow()
    floating.raise_()
    QTest.qWait(20)
    qapp.setActiveWindow(floating)
    window._preview = 12
    proposals = deepcopy(window.proposals)
    window.worker = object()
    window._set_review_busy(True)
    assert not window.suggestion_panel.isEnabled()
    QTest.keyClick(floating, Qt.Key.Key_Return)
    assert window.proposals == proposals
    window.worker = None
    window._set_review_busy(False)
    assert window.suggestion_panel.isEnabled()

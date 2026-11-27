"""Comparison windows inspect frozen selections without changing the live review."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QPushButton
from shiboken6 import isValid

from tests.test_learning_profile_panel import choose, saved_profile
from tests.test_learning_ui import inline, local_learning, notices, prepared_window


@pytest.fixture
def comparison_source(qapp, local_learning, notices):
    window = prepared_window(qapp)
    yield window
    for child in list(getattr(window, "_comparison_windows", [])):
        child.close()
        child.deleteLater()
    window.worker = None
    window._project_dirty = False
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def staged_profile(window, local_learning):
    profile, key = saved_profile(local_learning, name="Avatar comparison choices")
    window._refresh_learning_lists()
    choose(window.selection_profile_panel, key)
    return profile, key


def review_state(window):
    return deepcopy((window.snapshot, window.analysis, window.proposals, window._stored_settings,
                     window._learning_profile, window._learning_profile_path, window._excluded_frames,
                     window._page_layout, window.project_path, window._project_dirty))


def test_compare_requires_measured_analysis_a_profile_and_an_idle_source(comparison_source, local_learning):
    window = comparison_source
    panel = window.selection_profile_panel
    assert not panel.compare.isEnabled()
    staged_profile(window, local_learning)
    assert panel.compare.isEnabled()
    window.worker = object()
    window._sync_selection_profile_panels()
    assert not panel.compare.isEnabled()
    window.worker = None
    window._set_learning_busy(True)
    assert not panel.compare.isEnabled()
    window._set_learning_busy(False)
    assert panel.compare.isEnabled()
    window.show_analysis(None)
    assert not panel.compare.isEnabled()


def test_pending_profile_opens_two_frozen_read_only_views_without_applying_it(
        qapp, comparison_source, local_learning, monkeypatch, user_settings):
    window = comparison_source
    profile, _key = staged_profile(window, local_learning)
    before = review_state(window)
    preferences = user_settings.read_bytes() if user_settings.is_file() else None

    def forbidden(*_args, **_kwargs):
        pytest.fail("A visual comparison must not contact Resolve, run image analysis or save preferences")

    monkeypatch.setattr("vispa_mp.client.open_client", forbidden)
    monkeypatch.setattr("vispa_mp.project_ui.open_client", forbidden)
    monkeypatch.setattr("vispa_mp.learning_ui.open_client", forbidden)
    monkeypatch.setattr("vispa_mp.analyze.Live", forbidden)
    monkeypatch.setattr("vispa_mp.ui.save_user", forbidden)
    inline(window, monkeypatch)
    window._show_profile_comparison(window.selection_profile_panel)
    qapp.processEvents()
    children = list(window._comparison_windows)
    assert len(children) == 2
    assert {child.variant["name"] for child in children} == {"MP standard rules", profile["name"]}
    assert {child.variant["profile"] is None for child in children} == {False, True}
    assert all(child.isVisible() for child in children)
    assert review_state(window) == before
    assert window._learning_profile is None
    assert (user_settings.read_bytes() if user_settings.is_file() else None) == preferences

    # Later edits in the source do not change this comparison snapshot.
    original_sharpness = children[0].analysis["shots"][0]["frames"][0]["sharpness"]
    window.analysis["shots"][0]["frames"][0]["sharpness"] = -1
    assert children[0].analysis["shots"][0]["frames"][0]["sharpness"] == original_sharpness
    assert children[1].analysis["shots"][0]["frames"][0]["sharpness"] == original_sharpness


def test_comparison_uses_clean_automatic_choices_and_keeps_source_manual_edits(
        comparison_source, local_learning, monkeypatch):
    window = comparison_source
    staged_profile(window, local_learning)
    assert window.proposals
    window.proposals[0]["rule"] = "user"
    window.proposals[0]["user_role"] = True
    window._excluded_frames = {12}
    before = review_state(window)
    inline(window, monkeypatch)
    window._show_profile_comparison(window.selection_profile_panel)
    assert len(window._comparison_windows) == 2
    assert all(not item.get("user_role") and item.get("rule") != "user"
               for child in window._comparison_windows for item in child.variant["proposals"])
    assert review_state(window) == before


def test_comparison_can_use_the_active_profile_while_standard_is_selected(
        comparison_source, local_learning, monkeypatch):
    window = comparison_source
    profile, _key = staged_profile(window, local_learning)
    window.selection_profile_panel.apply.click()
    choose(window.selection_profile_panel, "")
    assert window._learning_profile == profile
    before = review_state(window)
    inline(window, monkeypatch)
    window._show_profile_comparison(window.selection_profile_panel)
    assert len(window._comparison_windows) == 2
    assert any(child.variant["profile"] == profile for child in window._comparison_windows)
    assert review_state(window) == before


def test_comparison_failure_preserves_the_review_and_does_not_open_partial_views(
        comparison_source, local_learning, notices, monkeypatch):
    window = comparison_source
    staged_profile(window, local_learning)
    before = review_state(window)

    def broken(*_args, **_kwargs):
        raise ValueError("The comparison could not be calculated")

    monkeypatch.setattr("vispa_mp.comparison.build_comparison", broken)
    inline(window, monkeypatch)
    window._show_profile_comparison(window.selection_profile_panel)
    assert not getattr(window, "_comparison_windows", [])
    assert review_state(window) == before
    assert notices[0]


def test_comparison_navigation_has_no_live_project_or_edit_actions(
        qapp, comparison_source, local_learning, monkeypatch):
    window = comparison_source
    staged_profile(window, local_learning)
    inline(window, monkeypatch)
    window._show_profile_comparison(window.selection_profile_panel)
    before = review_state(window)
    forbidden = {"Analyze", "Read timeline", "Place markers", "Recalculate", "Use selection"}
    for child in window._comparison_windows:
        assert not any(button.text() in forbidden for button in child.findChildren(QPushButton))
        proposals = deepcopy(child.variant["proposals"])
        child.set_mode("board")
        child.select_page(0)
        child.set_mode("strip")
        qapp.processEvents()
        assert child.variant["proposals"] == proposals
    assert review_state(window) == before


def test_reopening_comparison_replaces_the_pair_and_source_close_closes_it(
        comparison_source, local_learning, monkeypatch):
    window = comparison_source
    staged_profile(window, local_learning)
    inline(window, monkeypatch)
    window._show_profile_comparison(window.selection_profile_panel)
    previous = list(window._comparison_windows)
    window._show_profile_comparison(window.selection_profile_panel)
    current = list(window._comparison_windows)
    assert len(previous) == len(current) == 2
    assert not any(child in previous for child in current)
    assert all(not isValid(child) or not child.isVisible() for child in previous)
    window._project_dirty = False
    window.close()
    assert all(not isValid(child) or not child.isVisible() for child in current)

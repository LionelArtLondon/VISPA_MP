"""Visible profile controls describe what is applied, not merely inspected."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QFileDialog

from tests.test_learning_ui import inline, local_learning, notices, prepared_window, reference
from vispa_mp.learning_model import save_profile, train_profile
from vispa_mp.ui import MainWindow


@pytest.fixture
def profile_window(qapp, local_learning, notices):
    window = prepared_window(qapp)
    yield window
    window.worker = None
    window._project_dirty = False
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def saved_profile(local_learning, name="Avatar personal choices", filename="avatar.json"):
    profile = train_profile([reference()], name=name)
    path = local_learning.PROFILES_DIR / filename
    save_profile(profile, path)
    return profile, str(path.resolve())


def choose(panel, key):
    index = panel.profiles.findData(key)
    assert index >= 0, f"Missing profile choice: {key}"
    panel.profiles.setCurrentIndex(index)


def test_default_mode_is_visible_before_any_analysis(qapp, local_learning):
    window = MainWindow()
    try:
        panel = window.selection_profile_panel
        assert "standard" in panel.active.text().lower()
        assert panel.profiles.currentData() == ""
        assert not panel.apply.isEnabled()
        assert window._learning_profile is None
        assert "standard" in window.settings_profile_panel.active.text().lower()
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_choosing_a_profile_does_not_activate_it_or_replace_the_review(profile_window, local_learning):
    window = profile_window
    _profile, key = saved_profile(local_learning)
    window._refresh_learning_lists()
    before = deepcopy((window.snapshot, window.analysis, window.proposals, window._stored_settings))
    panel = window.selection_profile_panel
    choose(panel, key)
    assert window._learning_profile is None
    assert "standard" in panel.active.text().lower()
    assert "Avatar personal choices" not in panel.active.text()
    assert panel.apply.isEnabled()
    assert (window.snapshot, window.analysis, window.proposals, window._stored_settings) == before


def test_apply_recomputes_from_the_same_analysis_and_standard_is_reversible(profile_window, local_learning, monkeypatch):
    window = profile_window
    profile, key = saved_profile(local_learning)
    window._refresh_learning_lists()
    before = deepcopy((window.snapshot, window.analysis))
    marker_settings = {key: value for key, value in window.settings().items() if key != "learning_profile"}
    recomputes = []
    monkeypatch.setattr(window, "recompute", lambda: recomputes.append(True))
    monkeypatch.setattr(window, "run_analysis", lambda: pytest.fail("Switching preferences must not run image analysis"))
    panel = window.selection_profile_panel
    choose(panel, key)
    panel.apply.click()
    assert window._learning_profile == profile
    assert window._stored_settings["learning_profile"] == key
    assert profile["name"] in panel.active.text()
    assert profile["name"] in window.settings_profile_panel.active.text()
    assert recomputes == [True] and not panel.apply.isEnabled()
    assert (window.snapshot, window.analysis) == before
    assert {key: value for key, value in window.settings().items() if key != "learning_profile"} == marker_settings
    choose(panel, "")
    assert window._learning_profile == profile and profile["name"] in panel.active.text()
    panel.apply.click()
    assert window._learning_profile is None
    assert window._stored_settings["learning_profile"] == ""
    assert "standard" in panel.active.text().lower()
    assert recomputes == [True, True]
    assert {key: value for key, value in window.settings().items() if key != "learning_profile"} == marker_settings


def test_loading_an_external_profile_stages_it_without_activation(profile_window, notices, monkeypatch, tmp_path):
    window = profile_window
    profile = train_profile([reference()], name="External imported choices")
    path = tmp_path / "external-profile.json"
    save_profile(profile, path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(path), ""))
    before = deepcopy((window.analysis, window.proposals, window._stored_settings))
    panel = window.selection_profile_panel
    panel.load.click()
    assert panel.profiles.currentData() == str(path.resolve())
    assert window._learning_profile is None and "standard" in panel.active.text().lower()
    assert panel.apply.isEnabled()
    assert (window.analysis, window.proposals, window._stored_settings) == before
    assert notices[0] == []


def test_activation_from_learning_updates_both_visible_statuses(profile_window, local_learning):
    window = profile_window
    profile, key = saved_profile(local_learning)
    window._refresh_learning_lists()
    dialog = window.learning_dialog
    dialog.profiles.setCurrentIndex(dialog.profiles.findData(key))
    window._activate_learning_profile()
    assert window._learning_profile == profile
    for panel in (window.selection_profile_panel, window.settings_profile_panel):
        assert profile["name"] in panel.active.text()
    dialog.profiles.setCurrentIndex(0)
    window._activate_learning_profile()
    for panel in (window.selection_profile_panel, window.settings_profile_panel):
        assert "standard" in panel.active.text().lower()


def test_settings_panel_applies_the_same_profile_as_main_panel(profile_window, local_learning):
    window = profile_window
    profile, key = saved_profile(local_learning)
    window._refresh_learning_lists()
    choose(window.settings_profile_panel, key)
    assert window._learning_profile is None
    window.settings_profile_panel.apply.click()
    assert window._learning_profile == profile
    assert profile["name"] in window.selection_profile_panel.active.text()


def test_embedded_profile_restoration_is_visible_without_recomputing(profile_window, monkeypatch):
    window = profile_window
    profile = train_profile([reference()], name="Profile saved in the project")
    before = deepcopy(window.proposals)
    monkeypatch.setattr(window, "recompute", lambda: pytest.fail("Restoring a project must retain its reviewed choices"))
    window._restore_learning_profile(profile)
    window._refresh_learning_lists()
    for panel in (window.selection_profile_panel, window.settings_profile_panel):
        assert profile["name"] in panel.active.text()
        assert panel.profiles.findData("embedded") >= 0
    assert window._learning_profile == profile and window.proposals == before


def test_disappearing_staged_profile_keeps_the_applied_profile(profile_window, local_learning, notices):
    window = profile_window
    first, first_key = saved_profile(local_learning, "Keep active", "first.json")
    _second, second_key = saved_profile(local_learning, "Missing choice", "second.json")
    window._refresh_learning_lists()
    panel = window.selection_profile_panel
    choose(panel, first_key)
    panel.apply.click()
    choose(panel, second_key)
    from pathlib import Path
    Path(second_key).unlink()
    panel.apply.click()
    assert window._learning_profile == first
    assert first["name"] in panel.active.text()
    assert notices[0]


def test_missing_startup_profile_clears_both_active_indicators(profile_window, notices, tmp_path):
    window = profile_window
    profile = train_profile([reference()], name="Previously applied")
    window._restore_learning_profile(profile)
    window._stored_settings["learning_profile"] = str(tmp_path / "no-longer-available.json")
    window._load_selected_learning_profile()
    assert window._learning_profile is None
    for panel in (window.selection_profile_panel, window.settings_profile_panel):
        assert "standard" in panel.active.text().lower()
        assert profile["name"] not in panel.active.text()
    assert notices[0] == []


def test_profile_actions_are_disabled_during_jobs(profile_window, local_learning):
    window = profile_window
    _profile, key = saved_profile(local_learning)
    window._refresh_learning_lists()
    choose(window.selection_profile_panel, key)
    window._set_learning_busy(True, "Importing chapters…")
    for panel in (window.selection_profile_panel, window.settings_profile_panel):
        assert not panel.profiles.isEnabled()
        assert not panel.apply.isEnabled()
        assert not panel.load.isEnabled()
    window._set_learning_busy(False)
    assert window.selection_profile_panel.profiles.isEnabled()
    assert window.selection_profile_panel.apply.isEnabled()
    window.worker = object()
    window._sync_selection_profile_panels()
    assert not window.selection_profile_panel.profiles.isEnabled()
    assert not window.selection_profile_panel.load.isEnabled()
    window.worker = None


def test_training_adds_a_profile_choice_but_keeps_standard_active(profile_window, local_learning, monkeypatch):
    window = profile_window
    local_learning.save_reference(reference())
    window._refresh_learning_lists()
    window.learning_dialog.profile_name.setText("New trained preferences")
    inline(window, monkeypatch)
    window._train_learning_profile()
    assert window._learning_profile is None
    for panel in (window.selection_profile_panel, window.settings_profile_panel):
        assert "standard" in panel.active.text().lower()
        assert panel.profiles.findText("New trained preferences") >= 0

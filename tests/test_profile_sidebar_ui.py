"""The sidebar keeps the active profile visible and folds its optional actions."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel

from tests.test_learning_profile_panel import choose, saved_profile
from tests.test_learning_ui import local_learning, notices, prepared_window
from vispa_mp.learning_profile_ui import LearningProfilePanel
from vispa_mp.ui_tokens import px


@pytest.fixture
def sidebar_window(qapp, local_learning, notices):
    window = prepared_window(qapp)
    window.resize(1450, 1000)
    window.show()
    qapp.processEvents()
    yield window
    window.worker = None
    window._learning_job_busy = False
    window._project_dirty = False
    window._resolve_timer.stop()
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_default_summary_is_small_and_active_profile_remains_visible(sidebar_window):
    window = sidebar_window
    panel = window.selection_profile_panel
    assert panel.sidebar
    assert panel.isVisible() and panel.active.isVisible()
    assert "standard" in panel.active.text().lower()
    assert panel.sidebar_controls.isHidden()
    assert not panel.sidebar_toggle.isChecked()
    assert panel.detail.isHidden()
    assert panel.width() <= px(280)
    assert panel.minimumSizeHint().width() <= px(280)
    assert panel.height() <= px(90)


def test_staged_choice_is_visible_when_folded_and_apply_keeps_its_meaning(
        qapp, sidebar_window, local_learning, monkeypatch):
    window = sidebar_window
    profile, key = saved_profile(local_learning, name="Avatar Selection 1")
    window._refresh_learning_profile_choices()
    panel = window.selection_profile_panel
    before = deepcopy(window.proposals)
    choose(panel, key)

    assert panel.sidebar_controls.isHidden()
    assert panel.detail.isVisible()
    assert "not applied" in panel.detail.text()
    assert "standard" in panel.active.text().lower()
    assert window.proposals == before and window._learning_profile is None
    monkeypatch.setattr(window, "recompute", lambda: None)
    panel.sidebar_toggle.click()
    qapp.processEvents()
    assert panel.sidebar_controls.isVisible()
    assert all(control.isVisible() for control in (panel.profiles, panel.apply, panel.load, panel.manage, panel.compare))
    panel.apply.click()
    panel.sidebar_toggle.click()
    qapp.processEvents()

    assert profile["name"] in panel.active.text()
    assert profile["name"] in window.settings_profile_panel.active.text()
    assert panel.active.isVisible() and panel.sidebar_controls.isHidden()
    assert panel.detail.isHidden()


def test_sidebar_preserves_all_actions_and_busy_state(sidebar_window):
    window = sidebar_window
    panel = window.selection_profile_panel
    assert panel.sidebar_toggle in panel.controls
    panel.sidebar_toggle.click()
    window._set_learning_busy(True, "Importing chapters…")

    assert panel.active.isVisible()
    assert not any(control.isEnabled() for control in panel.controls)
    window._set_learning_busy(False)
    assert panel.sidebar_toggle.isEnabled()
    assert panel.profiles.isEnabled() and panel.load.isEnabled() and panel.manage.isEnabled()
    panel.sidebar_toggle.click()
    assert panel.sidebar_controls.isHidden()


def test_sidebar_wraps_the_active_name_and_its_controls_fit_the_column(
        qapp, sidebar_window, local_learning, monkeypatch):
    window = sidebar_window
    profile, key = saved_profile(local_learning, name="Avatar Selection 1 - Reviewed chapter choices")
    window._refresh_learning_profile_choices()
    panel = window.selection_profile_panel
    choose(panel, key)
    monkeypatch.setattr(window, "recompute", lambda: None)
    panel.apply.click()
    qapp.processEvents()

    assert panel.active.wordWrap()
    assert profile["name"] in panel.active.text()
    assert profile["name"] in panel.active.toolTip()
    assert panel.width() <= px(280)
    panel.sidebar_toggle.click()
    qapp.processEvents()
    for control in (panel.profiles, panel.apply, panel.load, panel.manage, panel.compare):
        assert control.width() <= panel.width() - px(24)
        left = control.mapTo(panel, control.rect().topLeft()).x()
        right = control.mapTo(panel, control.rect().topRight()).x()
        assert left >= 0 and right < panel.width()


def test_existing_full_settings_and_compact_variants_keep_their_controls(sidebar_window):
    window = sidebar_window
    full = window.settings_profile_panel
    assert not full.sidebar and not full.compact
    assert not hasattr(full, "sidebar_toggle")
    assert any(label.property("profileRole") == "explanation" for label in full.findChildren(QLabel))
    compact = LearningProfilePanel(window, compact=True)
    try:
        assert compact.compact and not compact.sidebar
        assert isinstance(compact.layout().itemAt(0).layout(), QHBoxLayout)
        assert not hasattr(compact, "sidebar_toggle")
        assert compact.controls == (compact.profiles, compact.apply, compact.load, compact.manage, compact.compare)
    finally:
        compact.deleteLater()

"""Inspecting imported examples never changes the edit or the active model."""

from copy import deepcopy

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from tests.test_learning_ui import local_learning, notices, prepared_window, reference
from vispa_mp.learning_model import train_profile
from vispa_mp.ui import MainWindow


def test_reference_inspection_is_enabled_for_one_selection_and_disabled_while_busy(qapp, local_learning):
    local_learning.save_reference(reference())
    local_learning.save_reference(reference("chapter-b"))
    window = MainWindow()
    window._refresh_learning_lists()
    dialog = window.learning_dialog
    assert not dialog.inspect_reference.isEnabled()
    first, second = (dialog.references.topLevelItem(index) for index in (0, 1))
    first.setSelected(True)
    assert dialog.inspect_reference.isEnabled()
    second.setSelected(True)
    assert not dialog.inspect_reference.isEnabled()
    second.setSelected(False)
    window._set_learning_busy(True)
    assert not dialog.inspect_reference.isEnabled()
    window._inspect_learning_reference()
    assert not getattr(window, "learning_reference_dialog", None)
    window._set_learning_busy(False)
    assert dialog.inspect_reference.isEnabled()


def test_inspecting_an_excluded_chapter_preserves_live_review_and_active_profile(qapp, local_learning, notices, monkeypatch):
    import vispa_mp.learning_ui as learning_ui
    imported = reference()
    imported["enabled"] = False
    local_learning.save_reference(imported)
    window = prepared_window(qapp)
    window._restore_learning_profile(train_profile([reference()], name="Keep active model"))
    window._refresh_learning_lists()
    original = deepcopy((window.snapshot, window.analysis, window.proposals, window._learning_profile,
                         window._stored_settings, window._learning_refs))
    monkeypatch.setattr(learning_ui, "open_client", lambda: pytest.fail("Inspection must not connect to Resolve"))
    window.learning_dialog.references.topLevelItem(0).setSelected(True)
    QTest.mouseClick(window.learning_dialog.inspect_reference, Qt.MouseButton.LeftButton)
    assert window.learning_reference_dialog.isVisible()
    assert (window.snapshot, window.analysis, window.proposals, window._learning_profile,
            window._stored_settings, window._learning_refs) == original
    assert not window._project_dirty
    assert notices[0] == []
    assert local_learning.list_references()[0]["enabled"] is False


def test_double_click_inspects_the_clicked_chapter_and_replaces_only_previous_inspector(qapp, local_learning):
    local_learning.save_reference(reference("chapter-a", "First chapter"))
    local_learning.save_reference(reference("chapter-b", "Second chapter"))
    window = MainWindow()
    window._refresh_learning_lists()
    dialog = window.learning_dialog
    first, second = (dialog.references.topLevelItem(index) for index in (0, 1))
    first.setSelected(True)
    window._inspect_learning_reference()
    previous = window.learning_reference_dialog
    dialog.references.itemDoubleClicked.emit(second, 0)
    assert window.learning_reference_dialog is not previous
    assert not previous.isVisible()
    assert window.learning_reference_dialog.reference["id"] == "chapter-b"
    assert window._learning_profile is None
    assert not local_learning.PROFILES_DIR.exists()


def test_stale_reference_row_produces_an_actionable_message(qapp, local_learning, notices):
    local_learning.save_reference(reference())
    window = MainWindow()
    window._refresh_learning_lists()
    item = window.learning_dialog.references.topLevelItem(0)
    window._learning_refs = []
    window._inspect_learning_reference(item)
    assert "Reopen Learning" in notices[0][-1][2]
    assert not getattr(window, "learning_reference_dialog", None)

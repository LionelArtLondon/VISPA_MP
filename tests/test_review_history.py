"""Local review edits have a bounded history without restoring Resolve state."""

from copy import deepcopy
from types import MethodType

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit

from tests.test_page_reorder_ui import _window
from tests.test_ui import action_analysis
from vispa_mp.markers import CORE, EXTRA
from vispa_mp.review_history import review_edit


@pytest.fixture
def review(qapp):
    windows = []

    def create(*, manual=False):
        window = _window(manual=manual)
        windows.append(window)
        window.resize(1400, 950)
        window.show()
        window.activateWindow()
        qapp.processEvents()
        return window

    yield create
    for window in windows:
        window.worker = None
        window._learning_job_busy = False
        window._project_dirty = False
        window._resolve_timer.stop()
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def content(window):
    return deepcopy(window._capture_review_history()["edit"])


def test_batch_role_delete_and_restore_keep_manual_source_markers(review):
    window = review(manual=True)
    window._choose_frame(20, False)
    window._toggle_frame_selection(30, False)
    window._toggle_frame_selection(15, True)
    window._proposal(30)["origin_frame"] = 25
    window.open_pages = {10}
    window._move_playhead(27)
    original = window._capture_review_history()
    analysis, snapshot = window.analysis, window.snapshot
    window._set_proposal_colors([20, 30, 15], CORE)
    recoloured = content(window)
    window._delete_marker_proposals([20, 30, 15])
    deleted = content(window)

    assert window.undo_stack.count() == 2
    assert window._excluded_frames == {20, 25, 30}
    assert window._undo_review()
    assert content(window) == recoloured
    assert window._undo_review()
    assert window._capture_review_history() == original
    assert window.analysis is analysis and window.snapshot is snapshot
    assert analysis["manual_frames"] == [15]
    assert snapshot["markers"] == [{"frame": 15, "automatic": False}]
    assert window._project_dirty
    assert window._redo_review() and content(window) == recoloured
    assert window._redo_review() and content(window) == deleted


def test_added_candidates_and_replacement_undo_as_separate_actions(review):
    window = review()
    window._open_suggestions(20, False)
    original = content(window)
    window._use_suggestion(25)
    replaced = content(window)
    assert window._proposal(25)["origin_frame"] == 20
    assert window._add_suggestion_markers([20], EXTRA) == 1
    added = content(window)

    assert window.undo_stack.count() == 2
    assert window._undo_review() and content(window) == replaced
    assert window._undo_review() and content(window) == original
    assert window._redo_review() and content(window) == replaced
    assert window._redo_review() and content(window) == added


def test_nested_edits_are_one_atomic_command(review):
    window = review()
    original = content(window)

    @review_edit("edit a batch")
    def combined(self):
        self._set_proposal_colors([20, 30], EXTRA)
        self._delete_marker_proposals([50])

    window.combined = MethodType(combined, window)
    window.combined()
    edited = content(window)
    assert window.undo_stack.count() == 1
    assert window.undo_stack.undoText() == "edit a batch"
    assert window._undo_review() and content(window) == original
    assert window._redo_review() and content(window) == edited


def test_page_group_move_and_automatic_reset_each_undo_as_one_action(review):
    window = review(manual=True)
    window._choose_frame(50, False)
    window._toggle_frame_selection(20, False)
    window.open_pages = {10, 40}
    original = window._capture_review_history()
    source = deepcopy(window.resolve_payload())

    assert window._move_markers_to_page([50, 20], 10, before_frame=30)
    moved = window._capture_review_history()
    assert moved["edit"]["page_layout"] == [
        {"id": 10, "frames": [10, 20, 50, 30]}, {"id": 40, "frames": [40, 60]}]
    window._reset_page_layout()
    assert window._page_layout is None
    assert window.undo_stack.count() == 2
    assert window._undo_review() and window._capture_review_history() == moved
    assert window._undo_review() and window._capture_review_history() == original
    assert window.resolve_payload() == source
    assert window._redo_review() and window._capture_review_history() == moved


def test_undo_uses_current_manual_markers_without_restoring_source_data(review):
    window = review(manual=True)
    window._set_proposal_colors([20], EXTRA)
    # A later source read may refresh its read-only manual-marker list.
    window.analysis["manual_frames"].append(55)
    window.snapshot["markers"].append({"frame": 55, "automatic": False})
    analysis, snapshot = deepcopy(window.analysis), deepcopy(window.snapshot)

    assert window._undo_review()
    assert window.analysis == analysis
    assert window.snapshot == snapshot
    assert {item["frame"] for page in window.pages for item in page["items"] if item["manual"]} == {15, 55}


def test_failed_nested_edit_rolls_back_without_discarding_redo(review):
    window = review()
    original = content(window)
    window._set_proposal_colors([20], EXTRA)
    window._undo_review()

    @review_edit("failed batch")
    def failing(self):
        self._set_proposal_colors([30], CORE)
        raise ValueError("cancelled local edit")

    with pytest.raises(ValueError, match="cancelled local edit"):
        failing(window)
    assert content(window) == original
    assert window.undo_stack.count() == 1 and window.undo_stack.canRedo()


def test_noop_and_selection_only_changes_preserve_redo(review):
    window = review()
    window._set_proposal_colors([20], EXTRA)
    assert window._undo_review()
    window._choose_frame(50, False)
    window._set_proposal_colors([20], CORE)
    window._delete_marker_proposals([999])
    window._add_suggestion_markers([999], EXTRA)

    assert window.undo_stack.count() == 1
    assert window.undo_stack.canRedo()
    assert window.selected_frame == 50
    assert window._redo_review()
    assert window._proposal(20)["color"] == EXTRA


def test_history_keeps_the_last_twenty_edits(review):
    window = review()
    states = [content(window)]
    for index in range(25):
        window._set_proposal_colors([20], EXTRA if index % 2 == 0 else CORE)
        states.append(content(window))

    assert window.undo_stack.undoLimit() == 20
    assert window.undo_stack.count() == 20
    for _ in range(20):
        assert window._undo_review()
    assert content(window) == states[5]
    assert not window._undo_review()
    for _ in range(20):
        assert window._redo_review()
    assert content(window) == states[-1]


def test_restoring_an_empty_selection_does_not_select_a_fallback(review):
    window = review()
    window.selected_frame = window.selected_page_id = None
    window._selected_keys.clear()
    window.open_pages = {10}
    window.playhead_frame = None
    original = window._capture_review_history()["context"]
    window._set_proposal_colors([30], CORE)

    assert window._undo_review()
    assert window._capture_review_history()["context"] == original
    assert all(not button.isEnabled() for button in window.color_buttons.values())
    assert window.playhead_label.text() == ""


@pytest.mark.parametrize("busy_attribute", ["worker", "_learning_job_busy"])
def test_undo_redo_and_edits_are_blocked_while_busy(review, busy_attribute):
    window = review()
    window._set_proposal_colors([20], EXTRA)
    window._move_markers_to_page([20], 40, before_frame=50)
    before = content(window)
    setattr(window, busy_attribute, object() if busy_attribute == "worker" else True)
    window._sync_review_history_actions()
    assert not window.undo_action.isEnabled()
    assert not window._undo_review()
    window._set_proposal_colors([30], CORE)
    window._delete_marker_proposals([20])
    window._move_markers_to_page([30], 40)
    window._reset_page_layout()
    window._open_suggestions(20, False)
    window._use_suggestion(25)
    assert content(window) == before
    setattr(window, busy_attribute, None if busy_attribute == "worker" else False)
    window._sync_review_history_actions()
    assert window.undo_action.isEnabled() and window._undo_review()
    setattr(window, busy_attribute, object() if busy_attribute == "worker" else True)
    window._sync_review_history_actions()
    assert not window.redo_action.isEnabled()
    assert not window._redo_review()


def test_new_analysis_clears_history_and_never_restores_an_older_source(review):
    window = review()
    window._set_proposal_colors([20], EXTRA)
    window.show_analysis(action_analysis())
    current = content(window)
    assert window.undo_stack.count() == 0
    assert not window._undo_review()
    assert content(window) == current


def test_source_identity_guard_rejects_history_if_an_analysis_is_replaced(review):
    window = review()
    window._set_proposal_colors([20], EXTRA)
    window.analysis = deepcopy(window.analysis)
    current = content(window)
    assert not window._undo_review()
    assert window.undo_stack.count() == 0
    assert content(window) == current


def test_project_restore_clears_history(review, tmp_path):
    window = review()
    window._set_proposal_colors([20], EXTRA)
    project = {"snapshot": deepcopy(window.snapshot), "analysis": deepcopy(window.analysis),
               "proposals": deepcopy(window.proposals), "settings": window.settings(),
               "view": window._project_view()}
    window._restore_project(project, project["snapshot"], None, tmp_path / "review.vispamp")
    assert window.undo_stack.count() == 0
    assert not window._undo_review()
    assert not window._project_dirty


def test_save_keeps_undo_and_undo_marks_the_saved_review_dirty(review, tmp_path):
    window = review()
    window._set_proposal_colors([20], EXTRA)
    path = tmp_path / "saved.vispamp"
    window.save_project_file(path)
    assert window.undo_stack.count() == 1
    assert not window._project_dirty

    assert window._undo_review()
    assert window.project_path == path
    assert window._project_dirty


def test_floating_suggestions_share_window_scoped_shortcuts(qapp, review):
    window = review()
    window._open_suggestions(20, False)
    window._detach_suggestions()
    floating = window.suggestions_window
    window._set_proposal_colors([20], EXTRA)
    assert window.undo_action in floating.actions()
    assert window.redo_action in floating.actions()
    assert window.undo_action.shortcutContext() == Qt.ShortcutContext.WindowShortcut
    def key(key, modifiers=Qt.KeyboardModifier.ControlModifier):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        floating.activateWindow()
        floating.setFocus()
        qapp.setActiveWindow(floating)
        QTest.keyClick(floating, key, modifiers)
        qapp.processEvents()

    key(Qt.Key.Key_Z)
    assert window._proposal(20)["color"] == CORE
    key(Qt.Key.Key_Y)
    assert window._proposal(20)["color"] == EXTRA
    key(Qt.Key.Key_Z)
    key(Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert window._proposal(20)["color"] == EXTRA


def test_text_editor_keeps_its_own_undo_without_consuming_marker_history(qapp, review):
    window = review()
    window._set_proposal_colors([20], EXTRA)
    editor = QLineEdit(window)
    editor.setText("Chapter")
    editor.show()
    editor.setFocus()
    window.activateWindow()
    qapp.processEvents()
    QTest.keyClicks(editor, " changed")
    assert editor.isUndoAvailable()

    QTest.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()
    assert editor.text() == "Chapter"
    assert window._proposal(20)["color"] == EXTRA
    assert window.undo_stack.index() == 1

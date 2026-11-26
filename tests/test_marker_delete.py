"""Remove prepared markers without touching Resolve, including across reloads."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QFrame

from tests.test_project_ui import _review as project_review
from tests.test_ui import action_analysis
from vispa_mp.markers import EXTRA, PAGE
from vispa_mp.project import load_project
from vispa_mp.ui import MainWindow


def _window(mode="strip", view_filter="all"):
    window = MainWindow(client=None)
    window.set_setting("action_extras", 0)
    window.show_analysis(action_analysis())
    window._set_marker_color(PAGE)
    window._set_mode(mode)
    window._set_filter(view_filter)
    window._project_dirty = False
    return window


def _delete_action(menu):
    return next(action for action in menu.actions() if action.text() == "Delete marker proposal")


@pytest.mark.parametrize("mode", ["strip", "board"])
@pytest.mark.parametrize("view_filter", ["all", "core", "starts"])
def test_proposal_delete_menu_works_in_each_view_and_filter(qapp, mode, view_filter):
    window = _window(mode, view_filter)
    original = deepcopy(window.proposals)
    menu = window._marker_menu(22)
    assert window.proposals == original
    assert window._project_dirty is False
    action = _delete_action(menu)
    assert action.isEnabled()
    action.trigger()
    assert window.proposals == []
    assert window._excluded_frames == {22}
    assert window.pages == []
    assert window.selected_frame is None
    assert window._project_dirty is True
    assert window.mode == mode and window.view_filter == view_filter


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_right_click_reaches_delete_action_from_a_displayed_frame(qapp, monkeypatch, mode):
    window = _window(mode)
    window.resize(1280, 800)
    window.show()
    qapp.processEvents()
    shown = []
    make_menu = window._marker_menu

    def choose_delete(*args, **kwargs):
        menu = make_menu(*args, **kwargs)

        def execute(position):
            shown.append(position)
            _delete_action(menu).trigger()

        menu.exec = execute
        return menu

    monkeypatch.setattr(window, "_marker_menu", choose_delete)
    if mode == "strip":
        card = window.thumb_area.widget().findChild(QFrame, "thumb-22-a")
        assert card is not None
        assert card.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
        card.customContextMenuRequested.emit(QPoint(8, 8))
    else:
        assert window.board._hits
        point = window.board._hits[0][0].center()
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, window.board.mapToGlobal(point))
        QApplication.sendEvent(window.board, event)

    assert len(shown) == 1
    assert window.proposals == []
    assert window._excluded_frames == {22}


def test_deleting_a_proposal_never_calls_resolve_or_changes_a_hand_placed_marker(qapp):
    window = _window()
    window.analysis["manual_frames"] = [12]
    window.snapshot = {"markers": [{"frame": 12, "automatic": False, "name": "My marker"}]}
    window._fill()
    snapshot = deepcopy(window.snapshot)

    class NoRPC:
        def read(self):
            pytest.fail("Deleting a proposal must remain local")

        def apply(self, *args, **kwargs):
            pytest.fail("Deleting a proposal must remain local")

        def seek(self, *args, **kwargs):
            pytest.fail("Deleting a proposal must remain local")

    window.client = NoRPC()
    manual_menu = window._marker_menu(12, manual=True)
    assert all(not action.isEnabled() for action in manual_menu.actions())
    window._delete_marker_proposal(12)
    assert window._proposal(22) is not None
    assert window._excluded_frames == set()
    window._delete_marker_proposal(22)
    assert window.proposals == []
    assert window.analysis["manual_frames"] == [12]
    assert window.snapshot == snapshot
    assert window._excluded_frames == {22}
    assert window.selected_frame == 12 and window.selected_manual


def test_automatic_deleted_proposals_do_not_return_when_thresholds_recalculate(qapp):
    window = _window()
    window._delete_marker_proposal(22)
    window.set_setting("sharpness_floor", 0.6)
    window.recompute()
    assert window.proposals == []
    assert window._excluded_frames == {22}
    assert window.apply_payload()["proposals"] == []


def test_deleting_a_replaced_image_also_excludes_the_original_automatic_position(qapp):
    window = _window()
    window._open_suggestions(22, False)
    window._use_suggestion(12)
    assert window._proposal(12)["origin_frame"] == 22
    window._delete_marker_proposal(12)
    assert window._excluded_frames == {12, 22}
    assert window.proposals == []
    assert window._suggestions_open is False
    assert window.suggestion_panel.isHidden()
    assert "Existing Resolve markers are unchanged" in window.status.text()
    window.recompute()
    assert window._proposal(12) is None
    assert window._proposal(22) is None
    assert window.proposals == []


def test_a_replaced_markers_original_position_survives_save_before_its_later_deletion(qapp, tmp_path):
    window = project_review(qapp, tmp_path)
    assert window._proposal(12)["origin_frame"] == 22
    path = tmp_path / "replaced-marker.vispamp"
    assert window.save_project_file(path)
    project = load_project(path, tmp_path / "restored-cache")
    assert project["proposals"][0]["origin_frame"] == 22
    restored = MainWindow(client=None)
    restored._restore_project(project, deepcopy(window.snapshot), None, path)
    restored._delete_marker_proposal(12)
    assert restored._excluded_frames == {12, 22}
    restored.recompute()
    assert restored.proposals == []


def test_a_user_added_proposal_can_be_deleted_and_explicitly_added_back(qapp):
    window = _window()
    window._open_suggestions(22, False)
    original = deepcopy(window._proposal(22))
    window._add_suggestion_marker(12)
    assert window._proposal(12)["rule"] == "user"
    window._delete_marker_proposal(12)
    assert window._proposal(12) is None
    assert window._proposal(22) == original
    assert window._excluded_frames == {12}
    window.recompute()
    assert window._proposal(12) is None
    window._open_suggestions(22, False)
    window._add_suggestion_marker(12, EXTRA)
    assert window._proposal(12)["rule"] == "user"
    assert window._excluded_frames == set()
    window.recompute()
    assert window._proposal(12)["color"] == EXTRA


def test_delete_commands_are_disabled_while_busy_and_unknown_frames_do_nothing(qapp):
    window = _window()
    original = deepcopy(window.proposals)
    window._delete_marker_proposal(999)
    assert window.proposals == original
    assert window._project_dirty is False
    window.worker = object()
    try:
        assert not _delete_action(window._marker_menu(22)).isEnabled()
        window._delete_marker_proposal(22)
    finally:
        window.worker = None
    assert window.proposals == original
    assert window._excluded_frames == set()


def test_new_analysis_clears_only_the_previous_reviews_exclusions(qapp):
    window = _window()
    window._delete_marker_proposal(22)
    assert window.proposals == []
    window.show_analysis(action_analysis())
    assert window._excluded_frames == set()
    assert [item["frame"] for item in window.proposals] == [22]


def test_deletion_and_user_choices_survive_a_project_roundtrip_and_recalculation(qapp, tmp_path, monkeypatch):
    window = project_review(qapp, tmp_path)
    window._use_suggestion(22)
    window._add_suggestion_marker(2)
    window._delete_marker_proposal(22)
    assert [(item["frame"], item["rule"]) for item in window.proposals] == [(2, "user")]
    path = tmp_path / "removed-marker.vispamp"
    assert window.save_project_file(path)
    project = load_project(path, tmp_path / "restored-cache")
    assert project["view"]["excluded_frames"] == [22]
    restored = MainWindow(client=None)
    restored._restore_project(project, deepcopy(window.snapshot), None, path)
    assert restored._excluded_frames == {22}
    assert [(item["frame"], item["rule"]) for item in restored.proposals] == [(2, "user")]
    assert restored._project_dirty is False
    restored.recompute()
    assert restored._proposal(22) is None
    assert restored._proposal(2)["rule"] == "user"


def test_a_project_with_every_proposal_removed_can_be_saved_and_reopened(qapp, tmp_path):
    window = project_review(qapp, tmp_path)
    window._use_suggestion(22)
    window._delete_marker_proposal(22)
    path = tmp_path / "empty-review.vispamp"
    assert window.save_project_file(path)
    project = load_project(path, tmp_path / "cache")
    restored = MainWindow(client=None)
    restored._restore_project(project, deepcopy(window.snapshot), None, path)
    restored.recompute()
    assert restored.proposals == []
    assert restored.pages == []
    assert restored.selected_frame is None
    assert restored._excluded_frames == {22}

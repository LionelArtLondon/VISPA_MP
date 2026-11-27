"""Keep several reviewed candidates without replacing the existing marker."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QPoint, Qt

from tests.test_project_ui import _review
from tests.test_ui import action_analysis
from vispa_mp.markers import CORE, EXTRA, NAMES, PAGE
from vispa_mp.project import load_project
from vispa_mp.ui import MainWindow


def _window(mode="strip"):
    window = MainWindow(client=None)
    window.set_setting("action_extras", 0)
    window.show_analysis(action_analysis())
    window._set_mode(mode)
    window._open_suggestions(22, False)
    window._project_dirty = False
    return window


@pytest.mark.parametrize("mode", ["strip", "board"])
@pytest.mark.parametrize("label,color", [
    ("Add Extra marker", EXTRA),
    ("Add Core marker", CORE),
    ("Start a new page here", PAGE),
])
def test_a_suggestion_menu_adds_a_marker_without_replacing_the_original(qapp, mode, label, color):
    window = _window(mode)
    original = deepcopy(window.proposals)
    menu = window._suggestion_menu(12)

    # Opening or dismissing the menu itself must not accept an image.
    assert window.proposals == original
    assert window.selected_frame == 22
    assert window._project_dirty is False
    action = next(action for action in menu.actions() if action.text() == label)
    assert action.isEnabled()
    action.trigger()

    assert window._proposal(22) == original[0]
    assert [item["frame"] for item in window.proposals] == [12, 22]
    added = window._proposal(12)
    assert added["color"] == color
    assert added["name"] == NAMES[color]
    assert added["rule"] == "user"
    assert window.selected_frame == 22
    assert window.selected_manual is False
    assert window._project_dirty is True
    assert window.mode == mode


def test_several_suggestions_can_be_kept_and_applied_in_chronological_order(qapp):
    window = _window()
    window._add_suggestion_marker(12)
    window._add_suggestion_marker(2)
    assert [(item["frame"], item["color"]) for item in window.proposals] == [
        (2, EXTRA), (12, EXTRA), (22, CORE),
    ]
    assert window.apply_payload()["proposals"] == [
        {"frame": 2, "color": EXTRA},
        {"frame": 12, "color": EXTRA},
        {"frame": 22, "color": CORE},
    ]


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_right_click_opens_the_suggestion_menu_without_accepting_its_image(qapp, monkeypatch, mode):
    window = _window(mode)
    original = deepcopy(window.proposals)
    window._preview = 2
    card = window._suggestion_cards[12]
    opened = []

    make_menu = window._suggestion_menu

    def dismiss_menu(*args, **kwargs):
        menu = make_menu(*args, **kwargs)
        menu.exec = lambda _position: opened.append([action.text() for action in menu.actions()])
        return menu

    monkeypatch.setattr(window, "_suggestion_menu", dismiss_menu)
    assert card.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    point = QPoint(8, 8)
    card.customContextMenuRequested.emit(point)

    assert opened == [["Add Extra marker", "Add Core marker", "Start a new page here", "", "Use as replacement"]]
    assert window.proposals == original
    assert window.selected_frame == 22
    assert window._preview == 12  # The new context target and its non-destructive preview agree.
    assert window._project_dirty is False


def test_an_existing_proposal_or_manual_marker_cannot_be_added_twice(qapp):
    window = _window()
    window._add_suggestion_marker(12)
    before = deepcopy(window.proposals)
    window._project_dirty = False
    window._add_suggestion_marker(12, PAGE)
    window._add_suggestion_marker(22)
    assert window.proposals == before
    assert window._project_dirty is False

    window.analysis["manual_frames"] = [2]
    window._add_suggestion_marker(2)
    assert window.proposals == before
    assert window.analysis["manual_frames"] == [2]
    assert window._project_dirty is False


def test_a_manual_marker_in_the_latest_snapshot_also_blocks_an_addition(qapp):
    window = _window()
    window.snapshot = {"markers": [{"frame": 12, "automatic": False}]}
    before = deepcopy(window.proposals)
    menu = window._suggestion_menu(12)
    assert all(not action.isEnabled() for action in menu.actions() if not action.isSeparator())
    window._add_suggestion_marker(12)
    assert window.proposals == before
    assert window._project_dirty is False


@pytest.mark.parametrize("mode", ["strip", "board"])
@pytest.mark.parametrize("view_filter", ["core", "starts"])
def test_adding_an_extra_makes_it_visible_when_the_current_filter_hides_extras(qapp, mode, view_filter):
    window = _window(mode)
    window._set_marker_color(PAGE)
    window._set_filter(view_filter)
    window._open_suggestions(22, False)
    window._add_suggestion_marker(12)
    assert window.view_filter == "all"
    assert window.filter_buttons["all"].isChecked()
    assert window.selected_frame == 22
    assert window._proposal(12)["color"] == EXTRA
    assert window.mode == mode


def test_only_available_candidates_can_be_added_while_review_is_idle(qapp):
    window = _window()
    before = deepcopy(window.proposals)
    window._add_suggestion_marker(9999)
    assert window.proposals == before
    window.worker = object()
    try:
        window._add_suggestion_marker(12)
    finally:
        window.worker = None
    assert window.proposals == before
    assert window._project_dirty is False


def test_recalculation_keeps_user_added_markers_ahead_of_automatic_duplicates(qapp):
    window = _window()
    window._add_suggestion_marker(12, CORE)
    original = deepcopy(window._proposal(12))
    # This setting generates automatic action extras at frames 2 and 12.
    window.set_setting("action_extras", 2)
    assert window._proposal(12) == original
    assert sum(item["frame"] == 12 for item in window.proposals) == 1
    window.set_setting("action_extras", 0)
    assert window._proposal(12) == original
    assert [item["frame"] for item in window.proposals] == [12, 22]


def test_adding_a_core_updates_the_page_minimum_warning_and_keeps_the_original(qapp):
    window = _window()
    window.set_setting("core_page_min", 2)
    window.set_setting("total_page_min", 2)
    original = deepcopy(window.proposals[0])
    assert len(window.pages) == 1
    assert any("1 Core images, 1 in all, below the minimum" in line
               for line in window._warning_lines())
    assert "below the minimum" in window.warnings.text()

    menu = window._suggestion_menu(12)
    next(action for action in menu.actions() if action.text() == "Add Core marker").trigger()

    assert window._proposal(22) == original
    assert len(window.pages) == 1
    assert len(window.pages[0]["items"]) == 2
    assert all(item["proposal"]["color"] == CORE for item in window.pages[0]["items"])
    assert not any("below the minimum" in line for line in window._warning_lines())
    assert "below the minimum" not in window.warnings.text()


def test_user_additions_do_not_leak_into_a_new_analysis(qapp):
    window = _window()
    window._add_suggestion_marker(12)
    window.show_analysis(action_analysis())
    assert [item["frame"] for item in window.proposals] == [22]
    assert all(item.get("rule") != "user" for item in window.proposals)


def test_project_save_and_restore_keep_extra_candidates_and_their_manual_choice(qapp, tmp_path):
    window = _review(qapp, tmp_path)
    original = deepcopy(window.proposals)
    window._add_suggestion_marker(2)
    path = tmp_path / "multiple-choices.vispamp"
    assert window.save_project_file(path)
    project = load_project(path, tmp_path / "restored-cache")
    restored = MainWindow(client=None)
    restored._restore_project(project, deepcopy(window.snapshot), None, path)
    assert [item["frame"] for item in restored.proposals] == [2, 12]
    assert restored._proposal(2)["rule"] == "user"
    assert restored._proposal(2)["color"] == EXTRA
    assert restored._proposal(12)["color"] == original[0]["color"]
    assert restored.selected_frame == 12
    assert restored._project_dirty is False
    restored.recompute()
    assert restored._proposal(2)["rule"] == "user"
    assert restored._proposal(2)["color"] == EXTRA

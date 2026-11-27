"""Suggestion selections add markers while the original reviewed image stays put."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest

from tests.test_project_ui import _review
from tests.test_suggestion_add import _window
from vispa_mp.markers import CORE, EXTRA
from vispa_mp.project import load_project
from vispa_mp.ui import MainWindow


def settle(qapp):
    for _ in range(5):
        qapp.processEvents()


@pytest.fixture
def make_review(qapp):
    windows = []

    def create(mode="strip", detached=False):
        window = _window(mode)
        windows.append(window)
        window.resize(1600, 900)
        window.show()
        if detached:
            window._detach_suggestions()
        settle(qapp)
        window._project_dirty = False
        return window

    yield create
    for window in windows:
        window.worker = None
        window._project_dirty = False
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def click_suggestion(window, qapp, number, modifiers=Qt.KeyboardModifier.NoModifier, surface="picture"):
    card = window._suggestion_cards[number]
    widget = card._suggestion_picture if surface == "picture" else card
    point = widget.rect().center() if surface == "picture" else QPoint(3, 3)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, modifiers, point)
    settle(qapp)


def add_action(menu, color):
    label = "Add Extra marker" if color == EXTRA else "Add Core marker"
    return next(action for action in menu.actions() if action.text() == label)


@pytest.mark.parametrize("mode", ["strip", "board"])
@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.parametrize("surface", ["card", "picture"])
def test_ctrl_click_selects_multiple_suggestions_without_replacing_or_selecting_main_markers(
        qapp, make_review, mode, detached, surface):
    window = make_review(mode, detached)
    proposals, main_selection = deepcopy(window.proposals), set(window._selected_keys)
    click_suggestion(window, qapp, 12, surface=surface)
    assert window._selected_suggestion_frames == {12}
    assert window._preview == 12
    click_suggestion(window, qapp, 2, Qt.KeyboardModifier.ControlModifier, surface)
    assert window._selected_suggestion_frames == {2, 12}
    click_suggestion(window, qapp, 12, Qt.KeyboardModifier.ControlModifier, surface)
    assert window._selected_suggestion_frames == {2}
    assert window.proposals == proposals
    assert window.selected_frame == 22 and not window.selected_manual
    assert window._selected_keys == main_selection
    assert not window._project_dirty


@pytest.mark.parametrize("mode", ["strip", "board"])
@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.parametrize("color", [CORE, EXTRA])
def test_context_action_adds_all_selected_suggestions_and_keeps_the_original(
        qapp, make_review, mode, detached, color):
    window = make_review(mode, detached)
    original = deepcopy(window._proposal(22))
    main_selection = set(window._selected_keys)
    click_suggestion(window, qapp, 12)
    click_suggestion(window, qapp, 2, Qt.KeyboardModifier.ControlModifier)
    menu = window._suggestion_menu(12)
    try:
        action = add_action(menu, color)
        assert action.isEnabled()
        action.trigger()
        settle(qapp)
        assert [item["frame"] for item in window.proposals] == [2, 12, 22]
        assert window._proposal(22) == original
        assert all(window._proposal(number)["color"] == color for number in (2, 12))
        assert all(window._proposal(number)["rule"] == "user" for number in (2, 12))
        assert window.selected_frame == 22 and window._selected_keys == main_selection
        assert window._preview is None
        assert window._project_dirty
        assert window.suggestions_detached is detached
    finally:
        menu.deleteLater()


@pytest.mark.parametrize("detached", [False, True])
def test_right_click_within_a_multi_selection_preserves_it_and_dismissing_the_menu_edits_nothing(
        qapp, make_review, monkeypatch, detached):
    window = make_review(detached=detached)
    click_suggestion(window, qapp, 12)
    click_suggestion(window, qapp, 2, Qt.KeyboardModifier.ControlModifier)
    original = deepcopy(window.proposals)
    opened = []

    make_menu = window._suggestion_menu

    def dismiss_menu(*args, **kwargs):
        menu = make_menu(*args, **kwargs)
        menu.exec = lambda _position: opened.append(set(window._selected_suggestion_frames))
        return menu

    monkeypatch.setattr(window, "_suggestion_menu", dismiss_menu)
    card = window._suggestion_cards[12]
    QTest.mouseClick(card._suggestion_picture, Qt.MouseButton.RightButton)
    if not opened:  # The offscreen platform does not synthesize native context events.
        window._suggestion_cards[12].customContextMenuRequested.emit(QPoint(8, 8))
    settle(qapp)
    assert opened == [{2, 12}]
    assert window._selected_suggestion_frames == {2, 12}
    assert window.proposals == original
    assert window.selected_frame == 22 and not window._project_dirty


@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.parametrize("gesture", ["double_click", "enter"])
def test_replacement_requires_an_explicit_gesture(qapp, make_review, detached, gesture):
    window = make_review(detached=detached)
    click_suggestion(window, qapp, 12)
    assert window._proposal(22) is not None and window._proposal(12) is None
    if gesture == "double_click":
        QTest.mouseDClick(window._suggestion_cards[12]._suggestion_picture, Qt.MouseButton.LeftButton)
    else:
        host = window.suggestions_window if detached else window
        host.activateWindow()
        qapp.setActiveWindow(host)
        QTest.keyClick(host, Qt.Key.Key_Return)
    settle(qapp)
    assert window._proposal(22) is None
    assert len(window.proposals) == 1 and window._proposal(12) is not None
    assert window._proposal(12)["origin_frame"] == 22


def test_batch_add_skips_existing_and_manual_markers_without_recolouring_them(qapp, make_review):
    window = make_review()
    original = deepcopy(window._proposal(22))
    window.analysis["manual_frames"] = [12]
    added = window._add_suggestion_markers([22, 12, 2, 2, 9999], EXTRA)
    assert added == 1
    assert [item["frame"] for item in window.proposals] == [2, 22]
    assert window._proposal(22) == original
    assert window._proposal(2)["color"] == EXTRA
    assert window.analysis["manual_frames"] == [12]
    assert window.selected_frame == 22


def test_batch_add_and_context_actions_are_blocked_during_analysis(qapp, make_review):
    window = make_review()
    original = deepcopy(window.proposals)
    window.worker = object()
    try:
        assert window._add_suggestion_markers([2, 12], EXTRA) == 0
        menu = window._suggestion_menu(12)
        try:
            assert not add_action(menu, EXTRA).isEnabled()
            assert not add_action(menu, CORE).isEnabled()
        finally:
            menu.deleteLater()
        assert window.proposals == original and not window._project_dirty
    finally:
        window.worker = None


def test_a_context_action_from_another_preparation_cannot_add_its_frame_numbers(qapp, make_review):
    from tests.test_ui import action_analysis

    window = make_review()
    click_suggestion(window, qapp, 12)
    menu = window._suggestion_menu(12)
    try:
        window.show_analysis(action_analysis())
        original = deepcopy(window.proposals)
        action = add_action(menu, EXTRA)
        action.trigger()
        assert window.proposals == original
        assert window._proposal(12) is None
    finally:
        menu.deleteLater()


def test_batch_user_markers_survive_save_reload_and_recalculation(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("vispa_mp.project_location.LOCATION_PATH", tmp_path / "locations.json")
    window = _review(qapp, tmp_path)
    restored = None
    try:
        original = deepcopy(window._proposal(12))
        assert window._add_suggestion_markers([2, 22], EXTRA) == 2
        assert window._proposal(12) == original and window.selected_frame == 12
        path = tmp_path / "batch-suggestions.vispamp"
        assert window.save_project_file(path)
        project = load_project(path, tmp_path / "reload-cache")
        restored = MainWindow(client=None)
        restored._restore_project(project, deepcopy(window.snapshot), None, path)
        assert restored.selected_frame == 12
        for current in (window, restored):
            current.recompute()
            assert current._proposal(12)["frame"] == original["frame"]
            assert all(current._proposal(number)["rule"] == "user" for number in (2, 22))
            assert all(current._proposal(number)["color"] == EXTRA for number in (2, 22))
            assert len({item["frame"] for item in current.proposals}) == len(current.proposals)
    finally:
        for current in (window, restored):
            if current is not None:
                current._project_dirty = False
                current.close()
                current.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


def test_dismissing_a_menu_keeps_enter_aligned_with_the_visible_selected_suggestion(qapp, make_review):
    window = make_review()
    original = deepcopy(window.proposals)
    click_suggestion(window, qapp, 2)
    assert window._preview == 2
    menu = window._suggestion_menu(12)
    try:
        assert window._selected_suggestion_frames == {12}
        assert window._preview == 12
        assert window.proposals == original
    finally:
        menu.deleteLater()
    window._keep_preview()
    assert window._proposal(22) is None and window._proposal(12) is not None


def test_batch_additions_join_the_original_editorial_page_without_moving_existing_images(qapp, make_review):
    from vispa_mp.markers import NAMES, PAGE

    window = make_review()
    window.proposals.append({"frame": 18, "color": PAGE, "name": NAMES[PAGE], "rule": "user", "image": ""})
    window._page_layout = [{"id": 18, "frames": [18]}, {"id": 22, "frames": [22]}]
    window._fill()
    window._open_suggestions(22, False)
    original = deepcopy(window._proposal(22))
    assert window._add_suggestion_markers([2, 12], EXTRA) == 2
    assert window._page_layout == [{"id": 18, "frames": [18]}, {"id": 22, "frames": [2, 12, 22]}]
    assert window._proposal(22) == original
    assert window.selected_page_id == 22 and window.selected_frame == 22

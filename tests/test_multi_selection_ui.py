"""Review selection supports editing batches without changing hand-placed markers."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from tests.test_page_reorder_ui import _window
from tests.test_ui import action_analysis
from vispa_mp.markers import CORE, EXTRA, PAGE
from vispa_mp.project import load_project
from vispa_mp.review_drag import MarkerDragCard
from vispa_mp.ui import item_frame


@pytest.fixture
def review(qapp):
    windows = []

    def create(mode="strip", *, manual=False):
        window = _window(mode, manual=manual)
        windows.append(window)
        window.resize(1400, 950)
        window.show()
        window.activateWindow()
        qapp.processEvents()
        return window

    yield create
    for window in windows:
        window._project_dirty = False
        window._resolve_timer.stop()
        window.close()
    qapp.processEvents()


def click_image(qapp, window, frame, *, manual=False, ctrl=False):
    modifiers = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    if window.mode == "strip":
        card = window.thumb_area.widget().findChild(
            MarkerDragCard, f"thumb-{frame}-{'m' if manual else 'a'}")
        assert card is not None
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, modifiers, QPoint(8, 8))
    else:
        window.board.grab()
        rect = next(rect for rect, item in window.board._hits
                    if item_frame(item) == frame and bool(item["manual"]) == manual)
        QTest.mouseClick(window.board, Qt.MouseButton.LeftButton, modifiers, rect.center())
    qapp.processEvents()


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_ctrl_click_adds_removes_and_plain_click_replaces_selection(qapp, review, mode):
    window = review(mode)
    click_image(qapp, window, 10)
    click_image(qapp, window, 20, ctrl=True)
    click_image(qapp, window, 30, ctrl=True)
    assert window._selected_keys == {(10, False), (20, False), (30, False)}
    click_image(qapp, window, 20, ctrl=True)
    assert window._selected_keys == {(10, False), (30, False)}
    click_image(qapp, window, 20)
    assert window._selected_keys == {(20, False)}
    assert window.selected_frame == 20 and not window.selected_manual


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_ctrl_click_can_leave_no_images_selected(qapp, review, mode):
    window = review(mode)
    click_image(qapp, window, 20)
    click_image(qapp, window, 20, ctrl=True)
    assert window._selected_keys == set()
    window._fill()
    assert window._selected_keys == set()
    assert all(not button.isEnabled() for button in window.color_buttons.values())
    before = deepcopy(window.proposals)
    window._set_marker_color(EXTRA)
    window._delete_selected_marker_proposals()
    assert window.proposals == before


def test_selection_survives_switching_between_strip_and_board(qapp, review):
    window = review()
    click_image(qapp, window, 10)
    click_image(qapp, window, 20, ctrl=True)
    selected = {(10, False), (20, False)}
    window.board_button.click()
    qapp.processEvents()
    assert window._selected_keys == selected
    assert window.board.selected_keys == selected
    click_image(qapp, window, 30, ctrl=True)
    window.strip_button.click()
    qapp.processEvents()
    assert window._selected_keys == selected | {(30, False)}
    for frame in (10, 20, 30):
        card = window.thumb_area.widget().findChild(MarkerDragCard, f"thumb-{frame}-a")
        assert card.property("selected") == "true"


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_bulk_status_changes_every_selected_frame_even_when_pages_regroup(qapp, review, mode):
    window = review(mode)
    click_image(qapp, window, 20)
    click_image(qapp, window, 30, ctrl=True)
    untouched = {item["frame"]: deepcopy(item) for item in window.proposals if item["frame"] not in (20, 30)}
    window.color_buttons[PAGE].click()
    assert all(window._proposal(frame)["color"] == PAGE for frame in (20, 30))
    assert all(window._proposal(frame)["user_role"] is True for frame in (20, 30))
    assert {page["id"] for page in window.pages} == {10, 20, 30, 40}
    assert window._selected_keys == {(20, False), (30, False)}
    assert all(window._proposal(frame) == proposal for frame, proposal in untouched.items())
    assert window._project_dirty is True
    window.recompute()
    assert all(window._proposal(frame)["color"] == PAGE for frame in (20, 30))


def test_mixed_selection_changes_only_editable_proposals(qapp, review):
    window = review(manual=True)
    click_image(qapp, window, 20)
    click_image(qapp, window, 15, manual=True, ctrl=True)
    snapshot = deepcopy(window.snapshot)
    before = {item["frame"]: deepcopy(item) for item in window.proposals if item["frame"] != 20}
    window._set_marker_color(EXTRA)
    assert window._proposal(20)["color"] == EXTRA
    assert all(window._proposal(frame) == proposal for frame, proposal in before.items())
    assert window.analysis["manual_frames"] == [15]
    assert window.snapshot == snapshot
    assert window._selected_keys == {(20, False), (15, True)}


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_delete_key_removes_selected_proposals_and_keeps_manuals(qapp, review, mode):
    window = review(mode, manual=True)
    click_image(qapp, window, 20)
    click_image(qapp, window, 30, ctrl=True)
    click_image(qapp, window, 15, manual=True, ctrl=True)
    window._proposal(30)["origin_frame"] = 25
    before = {item["frame"]: deepcopy(item) for item in window.proposals if item["frame"] not in (20, 30)}
    snapshot = deepcopy(window.snapshot)
    focus = window.board if mode == "board" else window.thumb_area
    focus.setFocus()
    qapp.processEvents()
    QTest.keyClick(focus, Qt.Key.Key_Delete)
    qapp.processEvents()
    assert window._proposal(20) is None and window._proposal(30) is None
    assert window._excluded_frames == {20, 25, 30}
    assert all(window._proposal(frame) == proposal for frame, proposal in before.items())
    assert window.analysis["manual_frames"] == [15]
    assert window.snapshot == snapshot
    assert not (window._selected_keys & {(20, False), (30, False)})


def test_context_menu_uses_the_selected_batch(qapp, review, monkeypatch):
    window = review()
    click_image(qapp, window, 20)
    click_image(qapp, window, 30, ctrl=True)
    make_menu = window._marker_menu

    def choose_delete(*args, **kwargs):
        assert window._selected_keys == {(20, False), (30, False)}
        menu = make_menu(*args, **kwargs)
        action = next(action for action in menu.actions() if action.text() == "Delete marker proposals")
        assert action.isEnabled()
        menu.exec = lambda _position: action.trigger()
        return menu

    monkeypatch.setattr(window, "_marker_menu", choose_delete)
    window._show_marker_menu(20, False, window.mapToGlobal(QPoint(20, 20)))
    assert window._proposal(20) is None and window._proposal(30) is None
    assert window._excluded_frames == {20, 30}


def test_delete_key_does_not_remove_images_while_editing_a_format_field(qapp, review):
    window = review("board")
    click_image(qapp, window, 20)
    click_image(qapp, window, 30, ctrl=True)
    window._choose_format("Custom")
    editor = window.width_box.lineEdit()
    editor.setFocus()
    editor.selectAll()
    qapp.processEvents()
    before = deepcopy(window.proposals)
    QTest.keyClick(editor, Qt.Key.Key_Delete)
    qapp.processEvents()
    assert window.proposals == before
    assert window._excluded_frames == set()


def test_busy_review_refuses_batch_changes(qapp, review):
    window = review()
    click_image(qapp, window, 20)
    click_image(qapp, window, 30, ctrl=True)
    before = deepcopy(window.proposals)
    window.worker = object()
    try:
        window._set_marker_color(CORE)
        window._delete_selected_marker_proposals()
    finally:
        window.worker = None
    assert window.proposals == before
    assert window._excluded_frames == set()


def test_finishing_a_worker_restores_selected_image_role_controls(qapp, review):
    window = review()
    click_image(qapp, window, 20)
    window.worker = object()
    try:
        window._set_review_busy(True)
        window._fill()
        assert all(not button.isEnabled() for button in window.color_buttons.values())
    finally:
        window.worker = None
        window._set_review_busy(False)
    assert all(button.isEnabled() for button in window.color_buttons.values())


def test_missing_frames_and_new_analysis_do_not_keep_stale_selection(qapp, review):
    window = review()
    click_image(qapp, window, 20)
    click_image(qapp, window, 30, ctrl=True)
    window.proposals = [proposal for proposal in window.proposals if proposal["frame"] != 20]
    window._fill()
    assert window._selected_keys == {(30, False)}
    window.show_analysis(action_analysis())
    assert window._selected_keys <= {(22, False)}
    assert not (window._selected_keys & {(20, False), (30, False)})


def test_cross_page_selection_edits_every_target_after_switching_view_and_filter(qapp, review):
    window = review()
    window._set_filter("starts")
    qapp.processEvents()
    click_image(qapp, window, 10)
    click_image(qapp, window, 40, ctrl=True)
    window.board_button.click()
    window._set_filter("all")
    qapp.processEvents()
    assert window._selected_keys == {(10, False), (40, False)}
    window.color_buttons[CORE].click()
    assert window._proposal(10)["color"] == window._proposal(40)["color"] == CORE
    assert window._selected_keys == {(10, False), (40, False)}
    assert window._proposal(20)["color"] == window._proposal(50)["color"] == CORE
    assert window._proposal(30)["color"] == window._proposal(60)["color"] == EXTRA


def test_refill_keeps_a_surviving_selected_frame_active_across_pages(qapp, review):
    window = review()
    window._choose_frame(20, False)
    window._toggle_frame_selection(50, False)
    assert window.selected_page_id == 40 and window.selected_frame == 50
    window.proposals = [proposal for proposal in window.proposals if proposal["frame"] != 50]
    window._fill()
    assert window._selected_keys == {(20, False)}
    assert window.selected_frame == 20 and window.selected_page_id == 10


def test_restoring_a_review_replaces_previous_multi_selection(qapp, review, tmp_path):
    source = review()
    source._choose_frame(20, False)
    path = tmp_path / "selected-review.vispamp"
    assert source.save_project_file(path)
    project = load_project(path, tmp_path / "restored-cache")
    restored = review()
    restored._choose_frame(20, False)
    restored._toggle_frame_selection(30, False)
    assert restored._selected_keys == {(20, False), (30, False)}
    restored._restore_project(project, deepcopy(source.snapshot), None, path)
    assert restored._selected_keys == {(20, False)}
    assert restored.selected_frame == 20 and not restored.selected_manual

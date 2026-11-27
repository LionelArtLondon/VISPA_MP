"""Fit suggestions to chosen rows without losing candidates or editing gestures."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtTest import QTest

from tests.test_ui import _frame
from vispa_mp.markers import EXTRA
from vispa_mp.ui import MainWindow


def settle(qapp, count=8):
    for _ in range(count):
        qapp.processEvents()


def analysis(count):
    frames = [_frame(5 + index * 10) for index in range(count)]
    return {"fps": 24,
            "timebase": {"fps": 24, "start_frame": 0, "start_timecode": "00:00:00:00", "drop": False},
            "shots": [{"start": 0, "end": count * 10, "motion": 0, "opening": False,
                       "cut_grey": 0, "cut_colour": 0, "frames": frames}],
            "utterances": [], "manual_frames": [], "warnings": []}


@pytest.fixture
def make_review(qapp):
    windows = []

    def create(count=16, mode="strip", detached=True):
        window = MainWindow(client=None)
        windows.append(window)
        window.set_setting("global_markers_enabled", False)
        window.set_setting("action_extras", 0)
        window.set_setting("episode_minutes", 0)
        window.show_analysis(analysis(count))
        window._set_mode(mode)
        window.resize(1700, 1050)
        window.show()
        window._open_suggestions(window.proposals[-1]["frame"], False)
        if detached:
            window._detach_suggestions()
            window.suggestions_window.resize(1280, 760)
        else:
            window.set_suggestions_height(470)
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


def visible_cards(window):
    viewport = window.suggestion_area.viewport()
    return {number: QRect(card.mapTo(viewport, QPoint(0, 0)), card.size())
            for number, card in window._suggestion_cards.items()}


def assert_fitted(window, rows, count):
    area = window.suggestion_area
    cards = visible_cards(window)
    assert len(cards) == count
    assert area.horizontalScrollBar().maximum() == 0
    assert area.verticalScrollBar().maximum() == 0
    bounds = area.viewport().rect().adjusted(-1, -1, 1, 1)
    assert all(bounds.contains(rect) for rect in cards.values())
    assert len({rect.y() for rect in cards.values()}) == min(rows, count)
    visual_order = sorted(cards, key=lambda number: (cards[number].y(), cards[number].x()))
    assert visual_order == sorted(cards)


@pytest.mark.parametrize("mode", ["strip", "board"])
@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.parametrize("rows,count", [(2, 16), (3, 11), (4, 16)])
def test_fit_rows_keep_every_candidate_visible_in_both_hosts(qapp, make_review, mode, detached, rows, count):
    window = make_review(count, mode, detached)
    original = deepcopy((window.analysis, window.proposals, window.selected_frame))
    window._set_suggestions_rows(rows)
    settle(qapp)
    assert window.suggestions_rows == rows
    assert window.suggestions_rows_box.currentData() == rows
    assert_fitted(window, rows, count)
    assert (window.analysis, window.proposals, window.selected_frame) == original


def test_fewer_candidates_than_requested_rows_stay_visible_without_empty_scroll_space(qapp, make_review):
    window = make_review(3)
    window._set_suggestions_rows(6)
    settle(qapp)
    assert_fitted(window, 6, 3)


def test_four_candidates_use_all_three_requested_rows(qapp, make_review):
    window = make_review(4)
    window._set_suggestions_rows(3)
    settle(qapp)
    assert_fitted(window, 3, 4)
    cards = visible_cards(window)
    counts = [sum(rect.y() == y for rect in cards.values())
              for y in sorted({rect.y() for rect in cards.values()})]
    assert counts == [2, 1, 1]


def test_tiny_docked_six_rows_hide_captions_and_keep_all_candidates_visible(qapp, make_review):
    window = make_review(16, detached=False)
    window.set_suggestions_height(120)
    window._set_suggestions_rows(6)
    settle(qapp)
    assert_fitted(window, 6, 16)
    for card in window._suggestion_cards.values():
        assert card._suggestion_label.isHidden()
        assert card._suggestion_picture.width() > 0
        assert card._suggestion_picture.height() > 0


def test_resize_changes_thumbnail_sizes_without_recreating_cards_or_running_analysis(qapp, make_review, monkeypatch):
    window = make_review()
    window._set_suggestions_rows(3)
    settle(qapp)
    cards = dict(window._suggestion_cards)

    def forbidden(*_args, **_kwargs):
        pytest.fail("A suggestions display resize must not recalculate marker choices or run models")

    monkeypatch.setattr(window, "recompute", forbidden)
    monkeypatch.setattr("vispa_mp.ui.analyze", forbidden)
    floating = window.suggestions_window
    floating.resize(950, 500)
    settle(qapp)
    small = next(iter(cards.values()))._suggestion_picture.size()
    assert_fitted(window, 3, 16)
    floating.resize(1500, 850)
    settle(qapp)
    large = next(iter(cards.values()))._suggestion_picture.size()
    assert large.width() > small.width() and large.height() > small.height()
    assert window._suggestion_cards == cards
    assert_fitted(window, 3, 16)
    stable = visible_cards(window)
    settle(qapp, 25)
    assert visible_cards(window) == stable


def test_fit_respects_custom_frame_ratio_and_keeps_normal_height_captions_readable(qapp, make_review):
    window = make_review(11)
    window._set_suggestions_rows(3)
    window.frame_format_box.setCurrentText("Custom")
    window.frame_width_box.setValue(2)
    window.frame_height_box.setValue(3)
    settle(qapp)
    assert_fitted(window, 3, 11)
    for card in window._suggestion_cards.values():
        picture, label = card._suggestion_picture, card._suggestion_label
        assert abs(picture.width() - picture.height() * 2 / 3) <= 1.5
        assert label.height() >= label.fontMetrics().height()


def test_row_choice_survives_mode_switch_docking_and_fullscreen(qapp, make_review):
    window = make_review(11)
    window._set_suggestions_rows(3)
    window._set_mode("board")
    settle(qapp)
    assert_fitted(window, 3, 11)
    window.suggestions_window.toggle_fullscreen()
    settle(qapp)
    assert_fitted(window, 3, 11)
    window.suggestions_window.toggle_fullscreen()
    window._dock_suggestions()
    window.set_suggestions_height(470)
    settle(qapp)
    assert window.suggestions_rows_box.currentData() == 3
    assert_fitted(window, 3, 11)
    window._detach_suggestions()
    settle(qapp)
    assert_fitted(window, 3, 11)


def test_scroll_mode_remains_available_after_fitting_a_grid(qapp, make_review):
    window = make_review(16)
    assert window.suggestions_rows == 0
    assert window.suggestion_area.horizontalScrollBar().maximum() > 0
    window._set_suggestions_rows(2)
    settle(qapp)
    assert_fitted(window, 2, 16)
    window._set_suggestions_rows(0)
    settle(qapp)
    assert window.suggestion_area.horizontalScrollBar().maximum() > 0
    assert len(window._suggestion_cards) == 16


def test_ctrl_selection_and_batch_add_still_work_on_fitted_rows(qapp, make_review):
    window = make_review(11)
    window._set_suggestions_rows(3)
    settle(qapp)
    original = deepcopy(window.proposals)
    anchor = window.selected_frame
    first, second = sorted(window._suggestion_cards)[:2]
    for number, modifier in ((first, Qt.KeyboardModifier.NoModifier),
                             (second, Qt.KeyboardModifier.ControlModifier)):
        picture = window._suggestion_cards[number]._suggestion_picture
        QTest.mouseClick(picture, Qt.MouseButton.LeftButton, modifier, picture.rect().center())
        settle(qapp)
    assert window._selected_suggestion_frames == {first, second}
    assert window.proposals == original
    menu = window._suggestion_menu(second)
    try:
        next(action for action in menu.actions() if action.text() == "Add Extra marker").trigger()
    finally:
        menu.deleteLater()
    settle(qapp)
    assert window.selected_frame == anchor
    assert all(window._proposal(item["frame"]) == item for item in original)
    assert all(window._proposal(number)["color"] == EXTRA for number in (first, second))
    assert_fitted(window, 3, 11)

"""The shared Suggestions pane grows its stills in both review modes."""

import pytest
from PySide6.QtCore import Qt

from tests.test_ui import _review, action_analysis


def _settle(qapp):
    for _ in range(4):
        qapp.processEvents()


def _open(qapp, mode):
    window = _review(qapp, action_analysis())
    window._set_mode(mode)
    window._open_suggestions(window.proposals[0]["frame"], False)
    _settle(qapp)
    return window


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_dragging_the_separator_grows_suggestions_without_recreating_them(qapp, mode):
    window = _open(qapp, mode)
    splitter = window.review_splitter
    assert splitter.orientation() == Qt.Orientation.Vertical
    assert splitter.handle(1).isVisible()
    assert splitter.handleWidth() >= 6
    cards = dict(window._suggestion_cards)
    card = next(iter(cards.values()))
    before = card._suggestion_picture.size()
    height = window.get_suggestions_height()

    splitter.moveSplitter(max(120, splitter.sizes()[0] - 140), 1)
    _settle(qapp)

    assert window.get_suggestions_height() > height + 80
    assert card._suggestion_picture.height() > before.height() + 60
    assert card._suggestion_picture.width() > before.width()
    assert window._suggestion_cards == cards
    assert splitter.sizes()[0] >= 120
    assert window.suggestion_area.horizontalScrollBar().maximum() > 0


def test_suggestions_keep_the_same_height_across_modes_refresh_and_reopening(qapp):
    window = _open(qapp, "strip")
    window.set_suggestions_height(320)
    _settle(qapp)
    height = window.get_suggestions_height()
    selected = window.selected_frame
    window._set_mode("board")
    _settle(qapp)
    assert abs(window.get_suggestions_height() - height) <= 2
    assert window.selected_frame == selected
    window._refresh_suggestions()
    _settle(qapp)
    assert abs(window.get_suggestions_height() - height) <= 2
    window._suggestions_open = False
    window._refresh_suggestions()
    _settle(qapp)
    assert window.suggestion_panel.isHidden()
    assert window.suggestion_area.isHidden()
    window._open_suggestions(selected, False)
    _settle(qapp)
    assert abs(window.get_suggestions_height() - height) <= 2


def test_shrinking_suggestions_keeps_the_caption_visible_and_does_not_cache_every_resize(qapp):
    window = _open(qapp, "strip")
    for height in (350, 300, 260, 220, 170, 120):
        window.set_suggestions_height(height)
        _settle(qapp)
        for card in window._suggestion_cards.values():
            assert card.height() <= window.suggestion_area.viewport().height()
            assert card._suggestion_label.height() >= card._suggestion_label.fontMetrics().height()
            assert card._suggestion_picture.height() >= 40
    # Only the main review images go through the thumbnail cache. The pane's
    # intermediate resize sizes must not leave a pixmap for each candidate.
    cache = getattr(window, "_thumb_cache", {})
    assert not any(key[1] == next(iter(window._suggestion_cards.values()))._suggestion_picture.width()
                   and key[2] == next(iter(window._suggestion_cards.values()))._suggestion_picture.height()
                   for key in cache)

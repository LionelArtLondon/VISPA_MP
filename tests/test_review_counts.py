"""Counters describe visible panels and retain the other filter's useful total."""

from copy import deepcopy

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from vispa_mp.markers import CORE, EXTRA, PAGE
from vispa_mp.review_counts import PanelCounter
from vispa_mp.ui_tokens import px


def panel(frame, color=CORE):
    return {"manual": False, "proposal": {"frame": frame, "color": color}}


def manual(frame):
    return {"manual": True, "frame": frame}


@pytest.fixture
def counter(qapp):
    parent = QWidget()
    widget = PanelCounter(parent)
    yield widget
    parent.close()


def test_empty_counter_is_compact_and_mouse_transparent_on_the_existing_canvas(counter):
    assert counter.primary.text() == "0 panels"
    assert counter.secondary.text() == "0 Core"
    assert counter.parentWidget().layout() is None
    assert counter.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert counter.primary.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert counter.secondary.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert counter.focusPolicy() == Qt.FocusPolicy.NoFocus
    counter.ensurePolished()
    counter.primary.ensurePolished()
    counter.secondary.ensurePolished()
    assert counter.primary.font().pixelSize() == px(24)
    assert counter.secondary.font().pixelSize() == px(12)
    assert counter.sizeHint().height() < px(80)
    counter.layout().activate()
    assert counter.secondary.geometry().left() > counter.primary.geometry().right()
    assert abs(counter.primary.geometry().center().y() - counter.secondary.geometry().center().y()) <= 1


def test_all_counts_every_visible_panel_and_page_starts_count_as_core(counter):
    items = [panel(10, PAGE), panel(20), panel(30, EXTRA), manual(35), panel(40, EXTRA)]
    before = deepcopy(items)
    counter.update_counts(items, items, "all")
    assert counter.primary.text() == "5 panels"
    assert counter.secondary.text() == "2 Core"
    assert "Core (including Page starts): 2" in counter.toolTip()
    assert "Extras: 2" in counter.toolTip()
    assert "Manual Resolve markers: 1" in counter.toolTip()
    assert "no Core/Extra role is inferred" in counter.toolTip()
    assert items == before


def test_core_counts_actual_displayed_images_and_retains_the_unfiltered_total(counter):
    all_items = [panel(10, PAGE), panel(20), panel(30, EXTRA), manual(35)]
    counter.update_counts(all_items[:2], all_items, "core")
    assert counter.primary.text() == "2 Core"
    assert counter.secondary.text() == "4 incl. Extras"
    assert "Extras: 1" in counter.secondary.toolTip()
    assert "Manual Resolve markers: 1" in counter.primary.toolTip()


def test_page_start_filter_uses_global_chapter_core_total(counter):
    chapter = [panel(10, PAGE), panel(20), panel(30, EXTRA),
               panel(100, PAGE), panel(110), panel(120, EXTRA)]
    starts = [chapter[0], chapter[3]]
    counter.update_counts(starts, chapter, "starts")
    assert counter.primary.text() == "2 Page starts"
    assert counter.secondary.text() == "4 Core"
    assert "All panels: 6" in counter.toolTip()
    assert "Page starts: 2" in counter.toolTip()


def test_primary_uses_displayed_length_instead_of_recounting_all_available_roles(counter):
    all_items = [panel(10, PAGE), panel(20), panel(30)]
    counter.update_counts([all_items[0]], all_items, "core")
    assert counter.primary.text() == "1 Core"
    counter.update_counts([], all_items, "all")
    assert counter.primary.text() == "0 panels"
    assert counter.secondary.text() == "3 Core"


def test_manual_marker_colors_do_not_silently_become_editable_core_roles(counter):
    items = [manual(10), {**manual(20), "proposal": {"color": CORE}}, panel(30, EXTRA)]
    counter.update_counts(items, items, "all")
    assert counter.primary.text() == "3 panels"
    assert counter.secondary.text() == "0 Core"
    assert "Manual Resolve markers: 2" in counter.toolTip()


@pytest.mark.parametrize("view_filter,primary,secondary", [
    ("all", "0 panels", "0 Core"), ("core", "0 Core", "0 incl. Extras"),
    ("starts", "0 Page starts", "0 Core"),
])
def test_clearing_analysis_clears_old_counts_in_every_filter(counter, view_filter, primary, secondary):
    items = [panel(10, PAGE), panel(20), panel(30, EXTRA)]
    counter.update_counts(items, items, "all")
    counter.update_counts(None, None, view_filter)
    assert counter.primary.text() == primary
    assert counter.secondary.text() == secondary
    assert "Extras: 0" in counter.toolTip()


def test_page_edits_filter_switches_and_undo_snapshots_update_both_labels_together(counter):
    first = [panel(10, PAGE), panel(20), panel(30, EXTRA)]
    second = [panel(100, PAGE), panel(110, EXTRA)]
    counter.update_counts(first, first, "all")
    assert (counter.primary.text(), counter.secondary.text()) == ("3 panels", "2 Core")
    second_before = deepcopy(second)
    second.append(first.pop())  # Move an Extra to the other page.
    counter.update_counts(first, first, "all")
    assert (counter.primary.text(), counter.secondary.text()) == ("2 panels", "2 Core")
    counter.update_counts(second, second, "all")
    assert (counter.primary.text(), counter.secondary.text()) == ("3 panels", "1 Core")
    second[1]["proposal"]["color"] = CORE
    core_items = [item for item in second if item["proposal"]["color"] in (PAGE, CORE)]
    counter.update_counts(core_items, second, "core")
    assert (counter.primary.text(), counter.secondary.text()) == ("2 Core", "3 incl. Extras")
    counter.update_counts(second_before, second_before, "all")
    assert (counter.primary.text(), counter.secondary.text()) == ("2 panels", "1 Core")
    assert "Extras: 1" in counter.toolTip()


def test_unchanged_counts_do_not_trigger_new_label_updates_or_enable_disabled_painting(counter, monkeypatch):
    items = [panel(10)]
    counter.update_counts(items, items, "all")
    monkeypatch.setattr(counter.primary, "setText", lambda _text: pytest.fail("Unchanged totals need no update"))
    monkeypatch.setattr(counter.secondary, "setText", lambda _text: pytest.fail("Unchanged totals need no update"))
    counter.update_counts(deepcopy(items), deepcopy(items), "all")
    assert counter.updatesEnabled()


def test_update_respects_a_parent_disabled_repaint_state(counter):
    counter.setUpdatesEnabled(False)
    counter.update_counts([panel(10)], [panel(10)], "all")
    assert counter.primary.text() == "1 panels"
    assert not counter.updatesEnabled()

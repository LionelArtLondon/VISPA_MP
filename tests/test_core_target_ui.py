"""A soft Core average remains optional and follows saved review settings."""

from copy import deepcopy
import json

import pytest
from PySide6.QtWidgets import QDoubleSpinBox

from tests.test_project import _rewrite
from tests.test_project_ui import _review
from tests.test_ui import action_analysis
from vispa_mp.markers import CORE, EXTRA, PAGE
from vispa_mp.project import load_project
from vispa_mp.ui import MainWindow, group_pages, item_frame


def test_core_average_is_an_optional_decimal_control_on_the_pages_tab(qapp):
    window = MainWindow(client=None)
    control = window.widgets["core_page_target"]
    pages_tab = window.settings_tabs.widget(0)
    assert window.settings_tabs.tabText(0) == "Pages"
    assert isinstance(control, QDoubleSpinBox)
    assert pages_tab.isAncestorOf(control)
    assert control.minimum() == 0
    assert control.value() == 0
    assert control.specialValueText() == "Off"
    assert control.singleStep() == 0.5


def test_target_zero_retains_legacy_page_target_and_changes_need_no_analysis(qapp, monkeypatch):
    window = MainWindow(client=None)
    window.show_analysis(action_analysis())
    original = deepcopy(window.proposals)
    legacy_text = window.page_target.text()
    assert legacy_text.startswith("Target:")
    monkeypatch.setattr("vispa_mp.ui.analyze", lambda *args, **kwargs:
                        pytest.fail("Changing the average must use only cached measures"))

    window.set_setting("core_page_target", 6)
    assert window.settings()["core_page_target"] == 6
    assert window.page_target.text().startswith("Core target: 6 per page")
    pages = len(window.pages)
    cores = sum(item["color"] in (PAGE, CORE) for item in window.proposals)
    assert pages > 0
    assert f"average {cores / pages:.1f}" in window.page_target.text()
    # Cyan extras must never inflate the Core average in the displayed result.
    assert len(window.proposals) > cores
    assert "page and image limits apply" in window.page_target.text()

    window.set_setting("core_page_target", 0)
    assert window.page_target.text() == legacy_text
    assert window.proposals == original


def test_leading_extras_belong_to_the_first_page_in_core_average_mode(qapp):
    window = MainWindow(client=None)
    window.set_setting("action_extras", 2)
    window.set_setting("episode_minutes", 0)
    window.set_setting("core_page_target", 6)
    window.show_analysis(action_analysis())

    assert [(item["frame"], item["color"]) for item in window.proposals] == [
        (2, EXTRA), (12, EXTRA), (22, PAGE),
    ]
    assert len(window.pages) == 1
    assert window.pages[0]["id"] == 22
    assert [item_frame(item) for item in window.pages[0]["items"]] == [2, 12, 22]
    assert sum(item["color"] in (PAGE, CORE) for item in window.proposals) == 1
    assert "1 page proposed" in window.page_target.text()
    assert "average 1.0" in window.page_target.text()


def test_group_pages_keeps_legacy_leading_extras_separate_unless_requested():
    proposals = [{"frame": 2, "color": EXTRA}, {"frame": 12, "color": EXTRA},
                 {"frame": 22, "color": PAGE}]
    legacy = group_pages(proposals, [])
    assert [[item_frame(item) for item in page["items"]] for page in legacy] == [[2, 12], [22]]
    grouped = group_pages(proposals, [], include_leading_extras=True)
    assert len(grouped) == 1
    assert grouped[0]["id"] == 22
    assert [item_frame(item) for item in grouped[0]["items"]] == [2, 12, 22]


def test_a_decimal_core_average_survives_saved_settings_and_the_next_launch(qapp, tmp_path, user_settings):
    path = tmp_path / "core-average.json"
    window = MainWindow(client=None)
    window.set_setting("core_page_target", 5.5)
    window.save_settings_file(path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["settings"]["core_page_target"] == 5.5
    window.set_setting("core_page_target", 0)
    window.load_settings_file(path)
    assert window.widgets["core_page_target"].value() == 5.5
    assert window.settings()["core_page_target"] == 5.5
    assert json.loads(user_settings.read_text(encoding="utf-8"))["core_page_target"] == 5.5
    again = MainWindow(client=None)
    assert again.widgets["core_page_target"].value() == 5.5


def test_a_portable_review_restores_the_core_average_without_recomputing_choices(qapp, tmp_path, monkeypatch):
    original = _review(qapp, tmp_path)
    original.set_setting("core_page_target", 5.5)
    original._add_suggestion_marker(2)
    expected = [(item["frame"], item["color"], item["rule"]) for item in original.proposals]
    path = tmp_path / "core-average.vispamp"
    assert original.save_project_file(path)
    project = load_project(path, tmp_path / "restored-cache")
    assert project["settings"]["core_page_target"] == 5.5

    restored = MainWindow(client=None)
    monkeypatch.setattr(restored, "recompute", lambda:
                        pytest.fail("Loading a review must keep its prepared choices"))
    restored._validate_project_controls(project)
    restored._restore_project(project, deepcopy(original.snapshot), None, path)
    assert restored.settings()["core_page_target"] == 5.5
    assert restored.widgets["core_page_target"].value() == 5.5
    assert [(item["frame"], item["color"], item["rule"]) for item in restored.proposals] == expected
    assert restored.page_target.text().startswith("Core target: 5.5 per page")
    assert restored._project_dirty is False


def test_an_older_project_without_a_core_average_uses_the_legacy_mode(qapp, tmp_path):
    original = _review(qapp, tmp_path)
    path = tmp_path / "legacy.vispamp"
    assert original.save_project_file(path)
    _rewrite(path, edit=lambda metadata: metadata["settings"].pop("core_page_target", None))
    project = load_project(path, tmp_path / "restored-cache")
    restored = MainWindow(client=None)
    restored.set_setting("core_page_target", 6)
    restored._restore_project(project, deepcopy(original.snapshot), None, path)
    assert restored.widgets["core_page_target"].value() == 0
    assert restored.settings()["core_page_target"] == 0
    assert restored.page_target.text().startswith("Target:")

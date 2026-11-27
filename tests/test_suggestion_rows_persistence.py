"""Suggestion row counts travel with view preferences, never analysis rules."""

from copy import deepcopy
import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from tests.test_project import _review, _rewrite
from vispa_mp.preset import DEFAULTS, VIEW_DEFAULTS, load_user, save_user
from vispa_mp.project import load_project, save_project


def test_legacy_preferences_keep_the_scrolling_strip_without_changing_analysis_settings(tmp_path):
    settings, view = load_user(tmp_path / "missing.json")
    assert view["suggestions_rows"] == VIEW_DEFAULTS["suggestions_rows"] == 0
    assert "suggestions_rows" not in DEFAULTS and "suggestions_rows" not in settings


@pytest.mark.parametrize("rows", range(7))
def test_row_choice_round_trips_in_user_preferences(tmp_path, rows):
    target = tmp_path / "user.json"
    settings, view = load_user(target)
    view["suggestions_rows"] = rows
    before = deepcopy(settings)
    save_user(settings, view, target)
    restored_settings, restored_view = load_user(target)
    assert restored_view["suggestions_rows"] == rows
    assert restored_settings == before
    if rows == 0:
        assert not target.exists()
    else:
        assert json.loads(target.read_text(encoding="utf-8")) == {"suggestions_rows": rows}


@pytest.mark.parametrize("invalid", [True, False, 2.0, 2.5, "2", None, -1, 7, [], {}, float("nan"), float("inf")])
def test_invalid_user_row_choices_fall_back_and_are_not_saved(tmp_path, invalid):
    target = tmp_path / "user.json"
    target.write_text(json.dumps({"suggestions_rows": invalid}), encoding="utf-8")
    _settings, view = load_user(target)
    assert view["suggestions_rows"] == 0
    save_user({}, {"suggestions_rows": invalid}, target)
    assert not target.exists()


@pytest.mark.parametrize("rows", range(7))
def test_preparation_restores_exact_row_choice_without_changing_marker_data(tmp_path, rows):
    review = _review(tmp_path)
    review["view"]["suggestions_rows"] = rows
    before = deepcopy(review)
    target = tmp_path / "rows.vispamp"
    save_project(target, **review)
    restored = load_project(target, tmp_path / "cache")
    assert restored["view"]["suggestions_rows"] == rows
    assert restored["settings"] == review["settings"]
    assert [(item["frame"], item["color"]) for item in restored["proposals"]] == [
        (item["frame"], item["color"]) for item in review["proposals"]]
    assert review == before


@pytest.mark.parametrize("invalid", [True, False, 2.0, "2", None, -1, 7])
def test_invalid_project_row_counts_are_rejected_before_loading(tmp_path, invalid):
    target = tmp_path / "invalid-rows.vispamp"
    save_project(target, **_review(tmp_path))
    _rewrite(target, edit=lambda project: project["view"].update(suggestions_rows=invalid))
    with pytest.raises(ValueError, match="suggestions row preference"):
        load_project(target, tmp_path / "cache")


def test_preparations_without_row_preferences_remain_readable(tmp_path):
    review = _review(tmp_path)
    assert "suggestions_rows" not in review["view"]
    target = tmp_path / "legacy.vispamp"
    save_project(target, **review)
    restored = load_project(target, tmp_path / "cache")
    assert restored["view"] == review["view"]


def test_working_review_exports_rows_as_view_state_without_recalculating(qapp, monkeypatch, tmp_path):
    from vispa_mp.ui import MainWindow

    monkeypatch.setattr("vispa_mp.project_location.LOCATION_PATH", tmp_path / "locations.json")
    window = MainWindow(client=None)
    try:
        window.suggestions_rows = 3
        before = deepcopy(window.proposals)
        monkeypatch.setattr(window, "recompute", lambda: pytest.fail("Reading view state must not recalculate"))
        view = window._project_view()
        assert view["suggestions_rows"] == 3
        assert "suggestions_rows" not in window.settings()
        assert window.proposals == before
    finally:
        window._project_dirty = False
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

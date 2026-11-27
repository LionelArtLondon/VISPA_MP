"""Suggestion display choices remain view preferences and survive saved work."""

from copy import deepcopy
import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from tests.test_project import _review, _rewrite
from vispa_mp.preset import DEFAULTS, VIEW_DEFAULTS, load_user, save_user
from vispa_mp.project import load_project, save_project


OPTIONS = ("suggestions_auto_open", "suggestions_detached")


def test_suggestion_defaults_keep_the_existing_double_click_docked_behaviour(tmp_path):
    settings, view = load_user(tmp_path / "missing.json")
    assert all(view[key] is False for key in OPTIONS)
    assert all(key not in DEFAULTS and key not in settings for key in OPTIONS)


def test_suggestion_preferences_round_trip_without_becoming_analysis_settings(tmp_path):
    path = tmp_path / "user.json"
    settings, view = load_user(path)
    view.update(suggestions_auto_open=True, suggestions_detached=True)
    save_user(settings, view, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {key: True for key in OPTIONS}
    restored_settings, restored_view = load_user(path)
    assert restored_settings == settings
    assert all(restored_view[key] is True for key in OPTIONS)
    restored_view.update({key: False for key in OPTIONS})
    save_user(restored_settings, restored_view, path)
    assert not path.exists()


@pytest.mark.parametrize("invalid", [1, "yes", None, [], {}])
def test_malformed_user_suggestion_options_fall_back_instead_of_reaching_the_ui(tmp_path, invalid):
    path = tmp_path / "user.json"
    path.write_text(json.dumps({key: invalid for key in OPTIONS}), encoding="utf-8")
    _settings, view = load_user(path)
    assert all(view[key] is False for key in OPTIONS)
    save_user({}, {key: invalid for key in OPTIONS}, path)
    assert not path.exists()


@pytest.mark.parametrize("auto,detached", [(False, False), (True, False), (False, True), (True, True)])
def test_portable_preparation_preserves_both_suggestion_preferences(tmp_path, auto, detached):
    review = _review(tmp_path)
    review["view"].update(suggestions_auto_open=auto, suggestions_detached=detached)
    before = deepcopy(review)
    path = tmp_path / "prepared.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "restored-cache")
    assert restored["view"]["suggestions_auto_open"] is auto
    assert restored["view"]["suggestions_detached"] is detached
    assert review == before


@pytest.mark.parametrize("key", OPTIONS)
@pytest.mark.parametrize("invalid", [1, "yes", None])
def test_malformed_project_suggestion_choices_are_rejected(tmp_path, key, invalid):
    path = tmp_path / "prepared.vispamp"
    save_project(path, **_review(tmp_path))
    _rewrite(path, edit=lambda project: project["view"].update({key: invalid}))
    with pytest.raises(ValueError, match="suggestions display preference"):
        load_project(path, tmp_path / "cache")


def test_legacy_preparations_without_display_options_are_still_readable(tmp_path):
    review = _review(tmp_path)
    path = tmp_path / "legacy.vispamp"
    save_project(path, **review)
    assert load_project(path, tmp_path / "cache")["view"] == review["view"]


def test_review_view_and_restore_hook_keep_display_preferences_without_recomputing(qapp, tmp_path, monkeypatch):
    from tests.test_project_ui import _review as reviewed_window
    from vispa_mp.ui import MainWindow

    monkeypatch.setattr("vispa_mp.project_location.LOCATION_PATH", tmp_path / "locations.json")
    original = reviewed_window(qapp, tmp_path)
    original.suggestions_auto_open = True
    original.suggestions_detached = True
    project = {"snapshot": deepcopy(original.snapshot), "analysis": deepcopy(original.analysis),
               "proposals": deepcopy(original.proposals), "settings": original.settings(),
               "view": original._project_view()}
    assert all(project["view"][key] is True for key in OPTIONS)
    restored = MainWindow()
    calls = []

    def restore_options(view):
        calls.append((deepcopy(view), deepcopy(restored.proposals), restored._restoring_project))
        for key in OPTIONS:
            setattr(restored, key, view.get(key, VIEW_DEFAULTS[key]))

    monkeypatch.setattr(restored, "_restore_suggestions_preferences", restore_options, raising=False)
    monkeypatch.setattr(restored, "recompute", lambda: pytest.fail("View restoration must preserve saved marker choices"))
    try:
        restored._restore_project(project, project["snapshot"], None, tmp_path / "prepared.vispamp")
        assert len(calls) == 1 and calls[0][2] is True
        assert calls[0][0] == project["view"] and calls[0][1] == project["proposals"]
        assert all(getattr(restored, key) is True for key in OPTIONS)
        assert restored.proposals == project["proposals"]
    finally:
        for window in (original, restored):
            window._project_dirty = False
            window.close()
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()

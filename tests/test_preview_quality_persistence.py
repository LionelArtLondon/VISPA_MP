"""Preview detail is a shared view preference, independent of marker analysis."""

from copy import deepcopy
import json

import pytest

from tests.test_project import _review, _rewrite
from vispa_mp.preset import (DEFAULTS, PREVIEW_DEFAULTS, PREVIEW_QUALITIES, VIEW_DEFAULTS,
                             export_settings, load_user, save_user)
from vispa_mp.project import load_project, save_project


_INVALID = (None, True, False, 0, 1, 1.0, "", "medium", "MEDIUM", " Low", "High ",
            "Ultra", [], {}, ["Low"])


def test_existing_preferences_use_medium_without_adding_an_analysis_setting(user_settings):
    user_settings.write_text('{"compression": 0.7, "frame_format": "4:3"}', encoding="utf-8")
    settings, view = load_user()
    assert view["preview_quality"] == PREVIEW_DEFAULTS["preview_quality"] == "Medium"
    assert VIEW_DEFAULTS["preview_quality"] == "Medium"
    assert settings["compression"] == 0.7
    assert view["frame_format"] == "4:3"
    assert "preview_quality" not in DEFAULTS
    assert "preview_quality" not in settings


@pytest.mark.parametrize("quality", PREVIEW_QUALITIES)
def test_quality_roundtrips_in_user_preferences_and_default_needs_no_override(user_settings, quality):
    settings, view = load_user()
    original_settings = deepcopy(settings)
    view["preview_quality"] = quality
    save_user(settings, view)
    again_settings, again_view = load_user()
    assert again_settings == original_settings
    assert again_view["preview_quality"] == quality
    if quality == "Medium":
        assert not user_settings.exists()
    else:
        assert json.loads(user_settings.read_text(encoding="utf-8")) == {"preview_quality": quality}


@pytest.mark.parametrize("invalid", _INVALID)
def test_malformed_quality_falls_back_without_losing_valid_preferences(user_settings, invalid):
    user_settings.write_text(json.dumps({"preview_quality": invalid, "show_board_labels": False,
                                        "compression": 0.7}), encoding="utf-8")
    settings, view = load_user()
    assert view["preview_quality"] == "Medium"
    assert view["show_board_labels"] is False
    assert settings["compression"] == 0.7


@pytest.mark.parametrize("invalid", _INVALID)
def test_invalid_quality_is_ignored_when_saving_user_preferences(user_settings, invalid):
    save_user({}, {"preview_quality": invalid, "show_board_labels": False})
    assert json.loads(user_settings.read_text(encoding="utf-8")) == {"show_board_labels": False}
    assert load_user()[1]["preview_quality"] == "Medium"


@pytest.mark.parametrize("quality", PREVIEW_QUALITIES)
def test_portable_project_keeps_quality_for_both_modes_without_changing_markers(tmp_path, quality):
    review = _review(tmp_path)
    review["view"]["preview_quality"] = quality
    before = deepcopy(review)
    path = tmp_path / "preview-quality.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "cache")
    assert restored["view"]["preview_quality"] == quality
    assert restored["settings"] == before["settings"]
    assert restored["snapshot"] == before["snapshot"]
    assert [(item["frame"], item["color"], item["note"]) for item in restored["proposals"]] == [
        (item["frame"], item["color"], item["note"]) for item in before["proposals"]]
    assert review == before


@pytest.mark.parametrize("invalid", _INVALID)
def test_invalid_saved_quality_is_rejected_before_project_loading(tmp_path, invalid):
    path = tmp_path / "invalid-quality.vispamp"
    save_project(path, **_review(tmp_path))
    _rewrite(path, edit=lambda project: project["view"].update(preview_quality=invalid))
    with pytest.raises(ValueError, match="preview quality"):
        load_project(path, tmp_path / "cache")


def test_invalid_live_quality_does_not_replace_an_existing_project(tmp_path):
    review = _review(tmp_path)
    path = tmp_path / "kept-project.vispamp"
    save_project(path, **review)
    before = path.read_bytes()
    review["view"]["preview_quality"] = "Ultra"
    with pytest.raises(ValueError, match="preview quality"):
        save_project(path, **review)
    assert path.read_bytes() == before


def test_older_project_without_quality_remains_readable_and_uses_preview_default(tmp_path):
    review = _review(tmp_path)
    assert "preview_quality" not in review["view"]
    path = tmp_path / "older-project.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "cache")
    assert restored["view"] == review["view"]
    assert restored["view"].get("preview_quality", PREVIEW_DEFAULTS["preview_quality"]) == "Medium"
    assert restored["settings"] == review["settings"]


def test_exported_analysis_settings_exclude_preview_quality(tmp_path):
    target = tmp_path / "analysis-settings.json"
    export_settings({"preview_quality": "High", "compression": 0.7}, target)
    assert json.loads(target.read_text(encoding="utf-8"))["settings"] == {"compression": 0.7}

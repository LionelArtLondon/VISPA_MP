"""Preview preferences and removed proposals travel with the prepared review."""

from copy import deepcopy
import json

import pytest

from tests.test_project import _review, _rewrite
from vispa_mp.preset import FRAME_FORMATS, PREVIEW_DEFAULTS, load_user, save_user
from vispa_mp.project import load_project, save_project


def test_preview_preferences_and_exclusions_roundtrip_without_changing_source_or_markers(tmp_path):
    review = _review(tmp_path)
    preview = dict(show_board_labels=False, frame_format="Custom", frame_custom_width=4.5,
                   frame_custom_height=3.0, excluded_frames=[86402, 86408])
    review["view"].update(preview)
    original = deepcopy(review)
    path = tmp_path / "cropped-review.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "restored-cache")
    assert review == original
    assert restored["view"] == original["view"]
    assert restored["snapshot"] == original["snapshot"]
    assert [(item["frame"], item["color"]) for item in restored["proposals"]] == [
        (item["frame"], item["color"]) for item in original["proposals"]]


@pytest.mark.parametrize("frame_format", FRAME_FORMATS)
def test_each_frame_format_is_supported_in_a_saved_project(tmp_path, frame_format):
    review = _review(tmp_path)
    review["view"]["frame_format"] = frame_format
    path = tmp_path / "preview.vispamp"
    save_project(path, **review)
    assert load_project(path, tmp_path / "cache")["view"]["frame_format"] == frame_format


@pytest.mark.parametrize("key, value", [
    ("show_board_labels", 1), ("show_board_labels", "false"), ("show_board_labels", None),
    ("frame_format", "cinema"), ("frame_format", None),
    ("frame_custom_width", 0.09), ("frame_custom_height", 100.01),
    ("frame_custom_width", True), ("frame_custom_height", float("nan")),
    ("frame_custom_width", 10 ** 500),
    ("excluded_frames", [True]), ("excluded_frames", [2.5]),
    ("excluded_frames", ["2"]), ("excluded_frames", None), ("excluded_frames", {}),
])
def test_invalid_preview_or_exclusion_data_is_rejected_before_a_project_is_returned(tmp_path, key, value):
    path = tmp_path / "invalid-preview.vispamp"
    save_project(path, **_review(tmp_path))
    _rewrite(path, edit=lambda project: project["view"].update({key: value}))
    with pytest.raises(ValueError):
        load_project(path, tmp_path / "cache")


def test_preview_preferences_survive_next_launch_without_saving_excluded_frames_globally(user_settings):
    settings, view = load_user()
    view.update(show_board_labels=False, frame_format="Custom", frame_custom_width=2.0,
                frame_custom_height=3.0, excluded_frames=[123])
    save_user(settings, view)
    stored = json.loads(user_settings.read_text(encoding="utf-8"))
    assert "excluded_frames" not in stored
    again_settings, again_view = load_user()
    assert again_settings == settings
    for key in PREVIEW_DEFAULTS:
        assert again_view[key] == view[key]


def test_bad_preview_preferences_fall_back_without_losing_other_user_choices(user_settings):
    user_settings.write_text(json.dumps(dict(
        show_board_labels=0, frame_format="unknown", frame_custom_width=10 ** 500,
        frame_custom_height=True, core_page_target=8.0, page_format="B5",
    )), encoding="utf-8")
    settings, view = load_user()
    assert settings["core_page_target"] == 8.0
    assert view["page_format"] == "B5"
    assert {key: view[key] for key in PREVIEW_DEFAULTS} == PREVIEW_DEFAULTS


@pytest.mark.parametrize("origin", [True, 12.5, "12", 2 ** 80])
def test_invalid_original_marker_positions_are_rejected_before_restore(tmp_path, origin):
    path = tmp_path / "invalid-origin.vispamp"
    save_project(path, **_review(tmp_path))
    _rewrite(path, edit=lambda project: project["proposals"][0].update(origin_frame=origin))
    with pytest.raises(ValueError):
        load_project(path, tmp_path / "cache")


def test_restoring_a_project_syncs_preview_controls_without_recomputing_marker_choices(qapp, tmp_path, monkeypatch):
    from tests.test_project_ui import _review as ui_review, _semantic_proposals
    from vispa_mp.ui import MainWindow

    original = ui_review(qapp, tmp_path)
    original.frame_format = "Custom"
    original.frame_custom_width, original.frame_custom_height = 2.0, 3.0
    original.show_board_labels = False
    original._excluded_frames = {2, 8}
    original._sync_preview_fields()
    proposals = _semantic_proposals(original.proposals)
    path = tmp_path / "preview-controls.vispamp"
    assert original.save_project_file(path)
    project = load_project(path, tmp_path / "restored-cache")
    assert project["view"]["excluded_frames"] == [2, 8]

    restored = MainWindow(client=None)
    monkeypatch.setattr(restored, "recompute", lambda: pytest.fail("Opening must keep reviewed marker choices"))
    restored._restore_project(project, deepcopy(original.snapshot), None, path)
    assert restored.frame_format == "Custom"
    assert restored.frame_format_box.currentText() == "Custom"
    assert restored.frame_width_box.value() == 2.0
    assert restored.frame_height_box.value() == 3.0
    assert restored.show_board_labels is False
    assert restored.board_labels_check.isChecked() is False
    assert restored._excluded_frames == {2, 8}
    assert _semantic_proposals(restored.proposals) == proposals
    assert restored._project_dirty is False


def test_an_older_project_resets_preview_and_exclusions_to_defaults(qapp, tmp_path):
    from tests.test_project_ui import _review as ui_review
    from vispa_mp.ui import MainWindow

    original = ui_review(qapp, tmp_path)
    path = tmp_path / "older-review.vispamp"
    assert original.save_project_file(path)

    def strip_new_view_fields(project):
        for key in (*PREVIEW_DEFAULTS, "excluded_frames"):
            project["view"].pop(key, None)

    _rewrite(path, edit=strip_new_view_fields)
    project = load_project(path, tmp_path / "restored-cache")
    restored = MainWindow(client=None)
    restored.frame_format, restored.show_board_labels = "1:1", False
    restored.frame_custom_width, restored.frame_custom_height = 1.0, 1.0
    restored._excluded_frames = {12}
    restored._restore_project(project, deepcopy(original.snapshot), None, path)
    for key, value in PREVIEW_DEFAULTS.items():
        assert getattr(restored, key) == value
    assert restored.frame_format_box.currentText() == "Source"
    assert restored.board_labels_check.isChecked()
    assert restored._excluded_frames == set()
    assert [item["frame"] for item in restored.proposals] == [12]

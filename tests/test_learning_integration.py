"""A trained preference changes real proposals while review safeguards still apply."""

from copy import deepcopy
import json

import pytest

from vispa_mp.learning_model import FEATURE_NAMES, apply_profile, feature_vector, train_profile
from vispa_mp.preset import DEFAULTS
from vispa_mp.rules import propose


def selection_analysis():
    frames = [
        {"frame": 70, "sharpness": 80, "neighbor": 0, "open_mouth": 0.1,
         "closed_mouth": 0.9, "motion_blur": 0, "face": 0.9, "image": ""},
        {"frame": 90, "sharpness": 100, "neighbor": 0, "open_mouth": 0.95,
         "closed_mouth": 0.05, "motion_blur": 0, "face": 0.9, "image": ""},
    ]
    return {"fps": 24, "shots": [{"start": 0, "end": 100, "frames": frames}],
            "utterances": [], "manual_frames": [], "warnings": []}


@pytest.fixture(scope="module")
def personal_profile():
    references = []
    for chapter in range(3):
        samples = []
        for number in range(6):
            shot = deepcopy(selection_analysis()["shots"][0])
            offset = number * 100
            shot["start"], shot["end"] = offset, offset + 100
            for frame in shot["frames"]:
                frame["frame"] += offset
            for index, frame in enumerate(shot["frames"]):
                samples.append({"frame": frame["frame"], "shot": shot["start"],
                                "features": feature_vector(frame, shot),
                                "roles": ["core"] if index == 0 else []})
        references.append({"kind": "vispa-mp-reference", "version": 1,
                           "id": f"reference-{chapter}", "name": f"Chapter {chapter}",
                           "group_id": f"chapter-{chapter}", "feature_names": list(FEATURE_NAMES),
                           "samples": samples})
    return train_profile(references, "Earlier poses", holdout_group="chapter-2")


def options(**changes):
    result = dict(DEFAULTS, action_extras=0, core_page_target=0, global_markers_enabled=False)
    result.update(changes)
    return result


def role_profile(profile, role, feature, weight):
    from vispa_mp.learning_model import validate_profile

    result = deepcopy(profile)
    weights = [0.0] * len(FEATURE_NAMES)
    weights[FEATURE_NAMES.index(feature)] = weight
    result["roles"][role] = {"weights": weights, "bias": 0.0, "trained": True, "pairs": 1}
    result["report"]["roles"][role] = {"trained": True, "train_pairs": 1, "validation_pairs": 0,
                                        "baseline_accuracy": None, "personal_accuracy": None}
    return validate_profile(result)


def test_a_profile_actually_trained_on_references_changes_the_proposed_pose(personal_profile):
    analysis = selection_analysis()
    before = deepcopy(analysis)
    standard = propose(analysis, options())["proposals"]
    personal = propose(analysis, options(), profile=personal_profile)["proposals"]
    assert [item["frame"] for item in standard] == [90]
    assert [item["frame"] for item in personal] == [70]
    assert analysis == before
    assert personal_profile["report"]["validation_groups"] == ["chapter-2"]


def test_learning_never_bypasses_the_sharpness_floor(personal_profile):
    proposals = propose(selection_analysis(), options(sharpness_floor=90), profile=personal_profile)["proposals"]
    assert [item["frame"] for item in proposals] == [90]


def test_standard_mode_ignores_stale_personal_scores_without_mutating_them(personal_profile):
    analysis = selection_analysis()
    enriched = apply_profile(analysis, personal_profile)
    before = deepcopy(enriched)
    assert propose(enriched, options()) == propose(analysis, options())
    assert enriched == before


def test_learning_keeps_the_open_mouth_requirement_for_speech(personal_profile):
    analysis = selection_analysis()
    analysis["utterances"] = [{"start": 0, "end": 100}]
    proposals = propose(analysis, options(mouth_min=0.8), profile=personal_profile)["proposals"]
    speech = [item for item in proposals if item["rule"] == "speech"]
    assert [item["frame"] for item in speech] == [90]


def test_learning_never_invents_source_frames_or_overwrites_manual_markers(personal_profile):
    analysis = selection_analysis()
    analysis["manual_frames"] = [70]
    proposals = propose(analysis, options(skip_marked_shots=False), profile=personal_profile)["proposals"]
    assert all(item["frame"] in (70, 90) for item in proposals)
    assert all(item["frame"] != 70 for item in proposals)
    assert all(item["color"] != "Cyan" for item in proposals)


def test_page_preferences_work_when_the_core_average_is_disabled(personal_profile):
    analysis = {"fps": 24, "shots": [], "utterances": [], "manual_frames": []}
    for index in range(3):
        number = index * 100 + 90
        analysis["shots"].append({"start": index * 100, "end": (index + 1) * 100,
                                  "opening": index == 0, "cut_grey": 40,
                                  "cut_colour": 0.9 if index == 1 else 0.1,
                                  "frames": [{"frame": number, "sharpness": 100, "neighbor": 0}]})
    settings = options(target_pages_min=2, target_pages_max=2, episode_minutes=0,
                       core_page_min=0, core_page_max=30, total_page_min=0, total_page_max=100)
    standard = propose(analysis, settings)["proposals"]
    profile = role_profile(personal_profile, "page", "cut_colour", 15)
    personal = propose(analysis, settings, profile)["proposals"]
    assert [item["frame"] for item in standard if item["color"] == "Green"] == [90, 290]
    assert [item["frame"] for item in personal if item["color"] == "Green"] == [90, 190]
    assert len(personal) == len(standard)


def test_extra_preferences_choose_complements_without_changing_core_or_extra_count(personal_profile):
    from tests.test_ui import action_analysis

    settings = options(action_extras=1)
    analysis = action_analysis()
    standard = propose(analysis, settings)["proposals"]
    profile = role_profile(personal_profile, "extra", "shot_phase", -15)
    personal = propose(analysis, settings, profile)["proposals"]
    assert [item["frame"] for item in standard if item["color"] == "Cyan"] == [12]
    assert [item["frame"] for item in personal if item["color"] == "Cyan"] == [2]
    assert [item["frame"] for item in personal if item["color"] == "Blue"] == [22]


def test_a_project_carries_its_active_profile_without_loading_external_files(qapp, tmp_path, personal_profile):
    from tests.test_project_ui import _review
    from vispa_mp.project import load_project
    from vispa_mp.ui import MainWindow

    original = _review(qapp, tmp_path)
    original._restore_learning_profile(personal_profile)
    original._mark_project_dirty()
    path = tmp_path / "personal.vispamp"
    assert original.save_project_file(path)
    project = load_project(path, tmp_path / "other-computer")
    assert project["view"]["learning_profile"] == personal_profile
    restored = MainWindow(client=None)
    restored._restore_project(project, deepcopy(original.snapshot), None, path)
    assert restored._learning_profile == personal_profile
    assert restored._project_dirty is False
    assert [(item["frame"], item["color"]) for item in restored.proposals] == [
        (item["frame"], item["color"]) for item in original.proposals]


def test_resetting_settings_returns_to_standard_selection(qapp, personal_profile):
    from vispa_mp.ui import MainWindow

    window = MainWindow(client=None)
    window._restore_learning_profile(personal_profile)
    assert window._learning_profile is not None
    window.reset_settings()
    assert window._learning_profile is None
    assert window.settings()["learning_profile"] == ""


def test_a_settings_file_with_a_missing_profile_preserves_current_choices(qapp, tmp_path, personal_profile):
    from vispa_mp.ui import MainWindow

    window = MainWindow(client=None)
    window._restore_learning_profile(personal_profile)
    window.show_analysis(selection_analysis())
    settings, proposals = deepcopy(window.settings()), deepcopy(window.proposals)
    path = tmp_path / "unavailable-profile.json"
    path.write_text(json.dumps({"learning_profile": str(tmp_path / "missing.json"), "mouth_min": 0.9}), encoding="utf-8")
    with pytest.raises(ValueError):
        window.load_settings_file(path)
    assert window.settings() == settings
    assert window.proposals == proposals
    assert window._learning_profile == personal_profile


def test_an_invalid_embedded_profile_does_not_open_as_a_valid_project(tmp_path, personal_profile):
    from tests.test_project import _review, _rewrite
    from vispa_mp.project import load_project, save_project

    review = _review(tmp_path)
    review["view"]["learning_profile"] = personal_profile
    path = tmp_path / "invalid-profile.vispamp"
    save_project(path, **review)
    _rewrite(path, edit=lambda project: project["view"]["learning_profile"].update(version=99))
    with pytest.raises(ValueError, match="personal selection profile"):
        load_project(path, tmp_path / "loaded")


@pytest.mark.parametrize("value", ["0.5", True, -0.1, 1.1])
def test_project_preference_scores_are_numeric_and_bounded(tmp_path, value):
    from tests.test_project import _review
    from vispa_mp.project import save_project

    review = _review(tmp_path)
    review["proposals"][0]["personal_core"] = value
    with pytest.raises(ValueError, match="personal image preference"):
        save_project(tmp_path / "invalid-score.vispamp", **review)

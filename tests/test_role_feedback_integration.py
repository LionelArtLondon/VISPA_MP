"""Feedback changes eligible roles while image selection and quotas stay fixed."""

from copy import deepcopy

import pytest

from vispa_mp.learning_model import FEATURE_NAMES, train_profile
from vispa_mp.learning_ui import profile_report
from vispa_mp.markers import CORE, EXTRA, PAGE
from vispa_mp.preset import DEFAULTS
from vispa_mp.project import load_project, save_project
from vispa_mp.rules import propose


def scene(signature_kind="local"):
    frames = []
    for index, number in enumerate((20, 60, 100, 140)):
        signature = [65.0, 130.0, 105.0, 180.0] * 16
        if signature_kind == "local":
            for cell in range(25, 31):
                signature[cell] += index * 18
        elif signature_kind == "broad":
            signature = [value + index * 20 for value in signature]
        frame = {"frame": number, "sharpness": 100, "neighbor": 0.2,
                 "signature": signature, "open_mouth": 0, "closed_mouth": 0,
                 "face": 0, "solo": 0.8, "expression": 1, "motion_blur": 0,
                 "image": f"frame-{number}.jpg"}
        if signature_kind == "missing":
            frame.pop("signature")
        frames.append(frame)
    return {"fps": 24, "shots": [{"start": 0, "end": 160, "opening": True,
                                    "frames": frames, "motion": 0.2}],
            "utterances": [], "manual_frames": []}


def settings():
    return dict(DEFAULTS, global_markers_enabled=True, global_markers_auto=False,
                global_markers_min=4, global_markers_target=4, global_markers_max=4,
                end_fraction=1, duplicate_diff=0, action_extras=0,
                target_pages_min=1, target_pages_max=1, episode_minutes=0,
                core_page_min=2, core_page_max=8, total_page_min=4, total_page_max=8,
                core_page_target=0)


def reference(group="a", reverse=False):
    samples = []
    for index, expression in enumerate((0, 1)):
        features = [0.0] * len(FEATURE_NAMES)
        features[FEATURE_NAMES.index("expression")] = expression
        role = "extra" if expression == reverse else "core"
        samples.append({"frame": index * 50, "shot": 0, "features": features, "roles": [role]})
    return {"kind": "vispa-mp-reference", "version": 1, "id": group, "name": group,
            "group_id": group, "feature_names": list(FEATURE_NAMES), "samples": samples}


def identities(result):
    return [(item["frame"], item["image"]) for item in result["proposals"]]


def test_standard_selection_reclassifies_intermediate_movements_without_adding_images():
    analysis = scene()
    before = deepcopy(analysis)
    result = propose(analysis, settings())
    assert identities(result) == [(number, f"frame-{number}.jpg") for number in (20, 60, 100, 140)]
    assert [item["color"] for item in result["proposals"]] == [PAGE, EXTRA, EXTRA, CORE]
    assert result["marker_budget"]["actual"] == 4
    assert analysis == before


def test_a_moving_object_can_occupy_a_third_of_the_frame_without_becoming_another_framing():
    from vispa_mp.role_refinement import refine_roles

    analysis = scene()
    frames = analysis["shots"][0]["frames"]
    background = [80.0, 120.0, 110.0, 150.0] * 16
    for frame, (start, end) in zip(frames, ((0, 8), (16, 28), (8, 16), (24, 32))):
        frame["signature"] = list(background)
        for cell in range(start, end):
            frame["signature"][cell] += 40
    proposals = [{"frame": frame["frame"], "image": frame["image"],
                  "color": color, "rule": "page" if color == PAGE else "body"}
                 for frame, color in zip(frames, (PAGE, CORE, CORE, EXTRA))]
    result = refine_roles(proposals, analysis, settings())
    assert [item["color"] for item in result] == [PAGE, EXTRA, CORE, EXTRA]
    assert [(item["frame"], item["image"]) for item in result] == [
        (item["frame"], item["image"]) for item in proposals]


@pytest.mark.parametrize("signature_kind", ["missing", "broad", "static"])
def test_reassignment_requires_evidence_of_local_motion_in_a_stable_composition(signature_kind):
    result = propose(scene(signature_kind), settings())
    assert [item["color"] for item in result["proposals"]] == [PAGE, CORE, CORE, CORE]
    assert result["marker_budget"]["actual"] == 4


def test_standard_mode_ignores_stale_learned_role_scores():
    analysis = scene()
    expected = propose(analysis, settings())
    for frame in analysis["shots"][0]["frames"]:
        frame["personal_extra_role"] = 0.0
    assert propose(analysis, settings()) == expected


def test_a_manually_assigned_core_role_is_preserved_in_the_full_budget_pipeline():
    analysis = scene()
    analysis["_budget_user_proposals"] = [{"frame": 60, "image": "frame-60.jpg", "color": CORE,
                                            "name": "Core", "rule": "body", "user_role": True}]
    result = propose(analysis, settings())
    assert [item["frame"] for item in result["proposals"]] == [20, 60, 100, 140]
    assert [item["color"] for item in result["proposals"]] == [PAGE, CORE, EXTRA, CORE]
    assert result["proposals"][1]["user_role"] is True
    assert result["marker_budget"]["actual"] == 4


def test_a_real_approved_role_profile_can_keep_core_for_an_intermediate_image():
    profile = train_profile([reference()])
    assert not any(model["trained"] for model in profile["roles"].values())
    standard = propose(scene(), settings())
    personal = propose(scene(), settings(), profile=profile)
    assert identities(personal) == identities(standard)
    assert [item["color"] for item in personal["proposals"]] == [PAGE, CORE, CORE, CORE]
    assert personal["proposals"][0]["frame"] == standard["proposals"][0]["frame"]
    assert personal["marker_budget"]["actual"] == standard["marker_budget"]["actual"] == 4


def test_role_refinement_refreshes_the_core_average_warning_without_removing_images():
    analysis = scene()
    prototype = analysis["shots"][0]["frames"][0]
    frames = []
    for index in range(6):
        frame = deepcopy(prototype)
        frame["frame"] = 20 + index * 40
        frame["image"] = f"frame-{frame['frame']}.jpg"
        for cell in range(25, 31):
            frame["signature"][cell] += index * 12
        frames.append(frame)
    analysis["shots"][0].update(end=240, frames=frames)
    options = settings()
    options.update(global_markers_min=6, global_markers_target=6, global_markers_max=6,
                   core_page_target=2, total_page_min=6)
    result = propose(analysis, options)
    assert [item["frame"] for item in result["proposals"]] == [20, 60, 100, 140, 180, 220]
    assert sum(item["color"] in (PAGE, CORE) for item in result["proposals"]) == 2
    assert sum(item["color"] == EXTRA for item in result["proposals"]) == 4
    assert result["marker_budget"]["actual"] == 6
    assert not any("Core target" in warning for warning in result["warnings"])
    assert not any("minimum keeps" in warning for warning in result["warnings"])


def test_profile_report_separates_role_assignment_from_quality_ranking_metrics():
    profile = train_profile([reference("a"), reference("z")])
    text = profile_report(profile)
    assert "Core/Extra assignment: learned from 1 approved Core images and 1 approved Extras" in text
    assert "held-out balanced agreement 100.0%" in text
    assert "unmarked images are excluded" in text
    assert "standard selection remains available" in text


def test_profile_report_does_not_invent_a_role_validation_score_for_one_chapter():
    text = profile_report(train_profile([reference()]))
    assert "Core/Extra assignment has no independent score yet" in text
    assert "held-out balanced agreement" not in text


def test_legacy_profile_report_explicitly_keeps_standard_role_assignment():
    from tests.test_learning_model import _profile

    text = profile_report(_profile())
    assert "Core/Extra assignment: standard contextual rules" in text
    assert "this profile has no learned role model" in text


def test_portable_preparation_preserves_a_learned_role_score(tmp_path):
    from tests.test_project import _review

    review = _review(tmp_path)
    review["analysis"]["shots"][0]["frames"][0]["personal_extra_role"] = 0.25
    path = tmp_path / "role-feedback.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "cache")
    assert restored["analysis"]["shots"][0]["frames"][0]["personal_extra_role"] == 0.25


@pytest.mark.parametrize("invalid", [False, -0.01, 1.01])
def test_loading_a_project_rejects_malformed_learned_role_scores(tmp_path, invalid):
    from tests.test_project import _review, _rewrite

    path = tmp_path / "bad-role-score.vispamp"
    save_project(path, **_review(tmp_path))
    _rewrite(path, edit=lambda data: data["analysis"]["shots"][0]["frames"][0].update(personal_extra_role=invalid))
    with pytest.raises(ValueError, match="personal image role preference"):
        load_project(path, tmp_path / "cache")


@pytest.mark.parametrize("invalid", [None, 1, "yes"])
def test_loading_a_project_rejects_malformed_verified_speech_metadata(tmp_path, invalid):
    from tests.test_project import _review, _rewrite

    path = tmp_path / "bad-speech-preference.vispamp"
    save_project(path, **_review(tmp_path))
    _rewrite(path, edit=lambda data: data["proposals"][0].update(speech_quality_ok=invalid))
    with pytest.raises(ValueError, match="verified speech preference"):
        load_project(path, tmp_path / "cache")

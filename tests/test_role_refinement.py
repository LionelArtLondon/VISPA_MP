"""A local action's intermediate images can change role, never selection."""

from copy import deepcopy

import numpy as np
import pytest

from vispa_mp.markers import CORE, EXTRA, PAGE
from vispa_mp.preset import DEFAULTS
from vispa_mp.role_refinement import refine_roles


def _case(count=4):
    # Fixed textured background with an object changing only six spatial cells.
    background = np.array([65.0, 130.0, 105.0, 180.0] * 16)
    frames, proposals = [], []
    for index in range(count):
        signature = background.copy()
        signature[25:31] += index * 18
        number = 10 + index * 20
        frames.append({"frame": number, "signature": signature.tolist()})
        proposals.append({"frame": number, "color": PAGE if index == 0 else CORE,
                          "rule": "page" if index == 0 else "body", "name": "Page" if index == 0 else "Core",
                          "note": "Original", "image": f"{number}.jpg"})
    analysis = {"fps": 24, "shots": [{"start": 0, "end": count * 20 + 20, "frames": frames}],
                "manual_frames": []}
    settings = dict(DEFAULTS, core_page_min=2, core_page_target=0)
    return proposals, analysis, settings


def test_three_core_and_one_extra_become_two_core_and_two_extra_with_same_images():
    proposals, analysis, settings = _case()
    proposals[2].update(color=EXTRA, rule="action", name="Extra")
    before = deepcopy((proposals, analysis, settings))
    result = refine_roles(proposals, analysis, settings)
    assert [item["color"] for item in result] == [PAGE, EXTRA, EXTRA, CORE]
    assert [item["frame"] for item in result] == [item["frame"] for item in proposals]
    assert [item["image"] for item in result] == [item["image"] for item in proposals]
    assert result[0] == proposals[0] and result[2] == proposals[2] and result[-1] == proposals[-1]
    assert result[1]["rule"] == "intermediate" and result[1]["note"] == "Extra, intermediate movement"
    assert (proposals, analysis, settings) == before


def test_intermediate_conversions_are_not_a_fixed_extra_quota():
    proposals, analysis, settings = _case(6)
    result = refine_roles(proposals, analysis, settings)
    assert [item["color"] for item in result] == [PAGE, EXTRA, EXTRA, EXTRA, EXTRA, CORE]


@pytest.mark.parametrize("rule", ["speech", "speech_plain", "user"])
def test_verified_speech_and_explicit_user_choices_remain_core(rule):
    proposals, analysis, settings = _case()
    proposals[1]["rule"] = rule
    assert refine_roles(proposals, analysis, settings)[1] == proposals[1]


@pytest.mark.parametrize("protection", ["user_role", "manual", "budget", "speech_quality_ok"])
def test_other_explicit_protections_keep_the_assigned_role(protection):
    proposals, analysis, settings = _case()
    if protection in ("user_role", "speech_quality_ok"):
        proposals[1][protection] = True
    elif protection == "manual":
        analysis["manual_frames"] = [proposals[1]["frame"]]
    else:
        settings["_budget_protected_frames"] = {proposals[1]["frame"]}
    assert refine_roles(proposals, analysis, settings)[1] == proposals[1]


def test_unverified_speech_can_be_an_intermediate_without_sacrificing_a_verified_line():
    proposals, analysis, settings = _case()
    proposals[1]["rule"] = "speech_unverified"
    assert refine_roles(proposals, analysis, settings)[1]["color"] == EXTRA


def test_page_minimum_counts_the_page_start_and_limits_conversions():
    proposals, analysis, settings = _case()
    settings["core_page_min"] = 3
    result = refine_roles(proposals, analysis, settings)
    assert sum(item["color"] in (PAGE, CORE) for item in result) == 3
    assert sum(item["color"] == EXTRA for item in result) == 1
    settings["core_page_min"] = 4
    assert refine_roles(proposals, analysis, settings) == proposals


def test_page_boundaries_and_each_pages_minimum_remain_intact():
    proposals, analysis, settings = _case(6)
    proposals[3].update(color=PAGE, rule="page")
    result = refine_roles(proposals, analysis, settings)
    assert [item["frame"] for item in result if item["color"] == PAGE] == [10, 70]
    assert [item["color"] for item in result] == [PAGE, EXTRA, CORE, PAGE, EXTRA, CORE]


@pytest.mark.parametrize("change", ["static", "duplicates", "brightness", "broad", "camera", "missing"])
def test_insufficient_or_broad_visual_evidence_does_not_reassign(change):
    proposals, analysis, settings = _case()
    frames = analysis["shots"][0]["frames"]
    first = list(frames[0]["signature"])
    if change == "static":
        for frame in frames:
            frame["signature"] = list(first)
    elif change == "duplicates":
        frames[1]["signature"] = list(first)
        frames[2]["signature"] = list(frames[-1]["signature"])
    elif change == "brightness":
        for index, frame in enumerate(frames):
            frame["signature"] = [value + index * 15 for value in first]
    elif change == "broad":
        for index, frame in enumerate(frames):
            frame["signature"] = [value + index * 18 if cell % 2 else value - index * 18
                                  for cell, value in enumerate(first)]
    elif change == "camera":
        for index, frame in enumerate(frames):
            frame["signature"] = np.roll(np.array(first).reshape(8, 8), index, axis=1).ravel().tolist()
    else:
        for frame in frames:
            frame.pop("signature")
    assert refine_roles(proposals, analysis, settings) == proposals


def test_actual_shot_cuts_are_not_merged_by_parent_bounds():
    proposals, analysis, settings = _case()
    all_frames = analysis["shots"][0]["frames"]
    analysis["shots"] = [{"start": 0, "end": 45, "frames": all_frames[:2], "parent_start": 0, "parent_end": 100},
                         {"start": 45, "end": 100, "frames": all_frames[2:], "parent_start": 0, "parent_end": 100}]
    assert refine_roles(proposals, analysis, settings) == proposals


@pytest.mark.parametrize("score", [0, 0.2, 0.35])
def test_strong_learned_core_evidence_vetoes_intermediate_conversion(score):
    proposals, analysis, settings = _case()
    settings["_personal_role_assignment"] = True
    analysis["shots"][0]["frames"][1]["personal_extra_role"] = score
    assert refine_roles(proposals, analysis, settings)[1] == proposals[1]


def test_learned_extra_preference_selects_which_eligible_conversion_fits_the_floor():
    proposals, analysis, settings = _case()
    settings["_personal_role_assignment"] = True
    settings["core_page_min"] = 3
    frames = analysis["shots"][0]["frames"]
    frames[1]["personal_extra_role"] = 0.6
    frames[2]["personal_extra_role"] = 0.9
    assert [item["color"] for item in refine_roles(proposals, analysis, settings)] == [PAGE, CORE, EXTRA, CORE]


def test_learned_extra_score_cannot_override_visual_or_manual_safeguards():
    proposals, analysis, settings = _case()
    settings["_personal_role_assignment"] = True
    for frame in analysis["shots"][0]["frames"]:
        frame["signature"] = [100.0] * 64
        frame["personal_extra_role"] = 0.99
    assert refine_roles(proposals, analysis, settings) == proposals


@pytest.mark.parametrize("score", [None, float("nan"), 1.1, True, "0.9", 10 ** 400])
def test_absent_or_invalid_optional_learning_scores_use_standard_context(score):
    proposals, analysis, settings = _case()
    settings["_personal_role_assignment"] = True
    analysis["shots"][0]["frames"][1]["personal_extra_role"] = score
    assert refine_roles(proposals, analysis, settings)[1]["color"] == EXTRA


def test_standard_mode_ignores_stale_personal_role_scores():
    proposals, analysis, settings = _case()
    analysis["shots"][0]["frames"][1]["personal_extra_role"] = 0.05
    assert refine_roles(proposals, analysis, settings)[1]["color"] == EXTRA

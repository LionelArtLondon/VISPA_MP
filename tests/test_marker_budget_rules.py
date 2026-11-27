"""Global counts select real admissible stills without sacrificing hard limits."""

from copy import deepcopy

import pytest

from tests.test_rules import analysis, frame, shot
from vispa_mp.markers import CORE, EXTRA, PAGE
from vispa_mp.preset import DEFAULTS
from vispa_mp.rules import _pages, propose


def options(target=4, minimum=0, maximum=100, **changes):
    result = dict(DEFAULTS, global_markers_enabled=True, global_markers_auto=False,
                  global_markers_min=minimum, global_markers_target=target,
                  global_markers_max=maximum, episode_minutes=0,
                  target_pages_min=1, target_pages_max=1, core_page_min=1,
                  core_page_max=12, total_page_min=1, total_page_max=16,
                  core_page_target=0, skip_marked_shots=False, action_extras=0,
                  end_fraction=1.0, min_marker_seconds=0.33)
    result.update(changes)
    return result


def stills(numbers):
    return [frame(number, signature=[float(number)] * 4) for number in numbers]


def wide_shot():
    return analysis([shot(0, 144, stills(range(10, 140, 20)), opening=True)])


def test_missing_or_disabled_budget_keeps_the_exact_legacy_result():
    source = wide_shot()
    absent = options()
    for key in list(absent):
        if key.startswith("global_markers_"):
            absent.pop(key)
    off = dict(absent, global_markers_enabled=False)
    expected = propose(source, absent)
    assert propose(source, off) == expected
    assert "marker_budget" not in expected
    assert len(expected["proposals"]) == 1


def test_target_adds_measured_core_candidates_instead_of_only_reporting_a_count():
    source = wide_shot()
    before = deepcopy(source)
    result = propose(source, options(target=4))
    assert result["marker_budget"]["actual"] == 4
    assert len(result["proposals"]) == 4
    assert sum(item["color"] == PAGE for item in result["proposals"]) == 1
    assert {item["frame"] for item in result["proposals"]} <= {frame["frame"] for frame in source["shots"][0]["frames"]}
    assert source == before


def test_lower_target_reduces_the_same_measured_pool():
    source = analysis([shot(start, start + 72, [frame(start + 60)], opening=True)
                       for start in range(0, 1440, 72)])
    loose = propose(source, options(target=15, target_pages_max=5))
    tight = propose(source, options(target=6, target_pages_max=5))
    assert 14 <= len(loose["proposals"]) <= 16
    assert len(tight["proposals"]) == 6
    assert tight["marker_budget"]["actual"] == 6


def test_manual_roles_count_once_and_other_manual_colours_only_block():
    source = wide_shot()
    source.update(manual_frames=[10, 30, 50, 70], _budget_manual_frames=[10, 10, 30])
    result = propose(source, options(target=5))
    assert result["marker_budget"]["manual_count"] == 2
    assert result["marker_budget"]["actual"] == 5
    assert len(result["proposals"]) == 3
    assert all(item["frame"] not in {10, 30, 50, 70} for item in result["proposals"])


def test_manual_count_above_maximum_is_preserved_and_does_not_add_automatic_markers():
    source = wide_shot()
    source.update(manual_frames=list(range(8)), _budget_manual_frames=list(range(8)))
    result = propose(source, options(target=4, maximum=5))
    assert result["proposals"] == []
    assert result["marker_budget"]["actual"] == 8
    assert any("maximum 5" in warning and "8 markers" in warning for warning in result["warnings"])


def test_existing_user_choices_are_not_recoloured_or_removed_for_a_quota():
    source = wide_shot()
    protected = [dict(frame=number, color=PAGE if number == 10 else CORE,
                      rule="user", name="Chosen", note="Keep this", sharpness=0)
                 for number in (10, 30, 50, 70)]
    source["_budget_user_proposals"] = deepcopy(protected)
    result = propose(source, options(target=2, maximum=3, core_page_max=2, total_page_max=3))
    assert result["proposals"] == protected
    assert result["marker_budget"]["actual"] == 4
    assert any("maximum 3" in warning for warning in result["warnings"])


def test_user_choice_on_an_existing_manual_frame_is_not_counted_twice():
    source = wide_shot()
    source.update(manual_frames=[10], _budget_manual_frames=[10], _budget_user_proposals=[
        dict(frame=10, color=PAGE, rule="user", sharpness=100, name="Page", note="Keep")])
    result = propose(source, options(target=4))
    assert result["marker_budget"]["actual"] == 4
    assert len(result["proposals"]) == 4


def test_deleted_proposals_are_never_reintroduced_to_fill_the_budget():
    source = wide_shot()
    source["_budget_excluded_frames"] = [50, 70, 90, 110, 130]
    result = propose(source, options(target=6, minimum=5))
    assert {item["frame"] for item in result["proposals"]}.isdisjoint(source["_budget_excluded_frames"])
    assert result["marker_budget"]["actual"] == 2
    assert any("minimum 5" in warning for warning in result["warnings"])


@pytest.mark.parametrize("damage", ["motion_blur", "sharpness"])
def test_minimum_does_not_relax_any_quality_threshold(damage):
    source = wide_shot()
    for candidate in source["shots"][0]["frames"]:
        candidate[damage] = 0.9 if damage == "motion_blur" else 0.1
    result = propose(source, options(target=5, minimum=4))
    assert result["proposals"] == []
    assert result["marker_budget"]["actual"] == 0
    assert any("minimum 4" in warning and "no thresholds were relaxed" in warning for warning in result["warnings"])


def test_page_image_minimums_can_make_the_global_maximum_unattainable():
    source = analysis([shot(start, start + 144, stills(range(start + 10, start + 140, 20)), opening=True)
                       for start in (0, 144)])
    result = propose(source, options(target=2, maximum=3, target_pages_min=2,
                                    target_pages_max=2, core_page_min=3, total_page_min=3))
    assert len(result["proposals"]) == 6
    assert all(len(page) == 3 for page in _pages(result["proposals"]))
    assert any("maximum 3" in warning and "minimums" in warning for warning in result["warnings"])


def test_final_additions_never_evade_per_page_core_or_total_ceilings():
    source = wide_shot()
    result = propose(source, options(target=7, minimum=5, core_page_max=3, total_page_max=4))
    assert len(result["proposals"]) == 3
    assert all(len(page) <= 4 and sum(item["color"] in (PAGE, CORE) for item in page) <= 3
               for page in _pages(result["proposals"]))
    assert any("minimum 5" in warning for warning in result["warnings"])


def test_static_frames_outside_the_end_region_do_not_become_quota_extras():
    source = analysis([shot(0, 120, stills([5, 15, 25, 110]), motion=0)])
    result = propose(source, options(target=5, minimum=3, end_fraction=0.1, action_extras=3))
    assert [(item["frame"], item["color"]) for item in result["proposals"]] == [(110, CORE)]
    assert any("minimum 3" in warning for warning in result["warnings"])


def test_repeated_drawing_cannot_fill_an_arbitrarily_high_target():
    source = wide_shot()
    for candidate in source["shots"][0]["frames"]:
        candidate["signature"] = [0, 20, 0, 20]
    result = propose(source, options(target=6, minimum=4))
    assert len(result["proposals"]) == 1
    assert any("minimum 4" in warning for warning in result["warnings"])


def test_global_spacing_also_applies_across_a_shot_boundary():
    source = analysis([shot(0, 48, [frame(45)]), shot(48, 96, [frame(50)])])
    result = propose(source, options(target=2, minimum=2, min_marker_seconds=0.5))
    assert len(result["proposals"]) == 1
    assert any("minimum 2" in warning for warning in result["warnings"])


def test_only_frames_and_manual_markers_inside_the_analyzed_range_count():
    source = wide_shot()
    source.update(range=[30, 110], manual_frames=[10, 30, 110], _budget_manual_frames=[10, 30, 110])
    result = propose(source, options(target=4))
    assert result["marker_budget"]["manual_count"] == 1
    assert all(30 <= item["frame"] < 110 for item in result["proposals"])
    assert result["marker_budget"]["actual"] == 4


def test_speech_candidates_keep_open_mouth_and_core_priority_over_action_fillers():
    frames = [frame(number, open_mouth=0.9, closed_mouth=0.01, signature=[float(number)] * 4)
              for number in (10, 30, 50)] + [frame(110)]
    source = analysis([shot(0, 120, frames)], utterances=[{"start": 0, "end": 70}])
    result = propose(source, options(target=3, end_fraction=0.1, mouth_fallback="none"))
    assert len(result["proposals"]) == 3
    assert all(item["color"] == CORE for item in result["proposals"])
    speech = [item for item in result["proposals"] if item["rule"] == "speech"]
    assert len(speech) >= 2 and all(item["frame"] in (10, 30, 50) for item in speech)


def test_global_average_never_becomes_a_quota_for_each_minute():
    first = [shot(start, start + 120, [frame(start + 100)]) for start in range(0, 1440, 120)]
    second = [shot(start, start + 36, [frame(start + 30)]) for start in range(1440, 2880, 36)]
    source = analysis(first + second, timeline_range=[0, 2880])
    config = options(global_markers_auto=True, core_page_max=80, total_page_max=100)
    result = propose(source, config)
    assert sum(item["frame"] < 1440 for item in result["proposals"]) == 12
    assert sum(item["frame"] >= 1440 for item in result["proposals"]) == 40
    assert result["marker_budget"]["actual"] == 52


def test_natural_selection_near_global_target_is_kept_without_exact_quota():
    source = analysis([shot(start, start + 120, [frame(start + 100)]) for start in range(0, 1200, 120)])
    result = propose(source, options(target=11, core_page_max=20, total_page_max=20))
    assert result["marker_budget"]["actual"] == 10


def test_action_extras_still_obey_the_configured_per_shot_cap():
    frames = [frame(number, signature=signature) for number, signature in (
        (2, [0, 20, 0, 20]), (10, [20, 0, 20, 0]), (18, [0, 0, 20, 20]), (26, [20, 20, 0, 0]))]
    source = analysis([shot(0, 30, frames, motion=30)], fps=25)
    result = propose(source, options(target=6, action_extras=1, end_fraction=0.1,
                                    min_marker_seconds=0.1, min_extra_seconds=0.1))
    assert sum(item["rule"] == "action" for item in result["proposals"]) <= 1
    assert any(item["color"] == EXTRA for item in result["proposals"])

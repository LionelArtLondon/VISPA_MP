"""The optional Core average guides page divisions, without counting Extras."""

import pytest

from vispa_mp.markers import CORE, EXTRA, NAMES, PAGE
from vispa_mp.preset import DEFAULTS
from vispa_mp.rules import _fit_story, _pages, _trim_pages, core_target, propose


def settings(**changes):
    result = dict(DEFAULTS, core_page_target=6.0, core_page_min=2, core_page_max=12,
                  total_page_min=1, total_page_max=100, target_pages_min=2,
                  target_pages_max=8, compression=0, episode_minutes=0,
                  min_green_seconds=0)
    result.update(changes)
    return result


def story(count=32):
    return [dict(frame=index * 100, color=PAGE if index in (0, 12, 24) else CORE,
                 name=NAMES[PAGE if index in (0, 12, 24) else CORE], note="Core",
                 rule="page" if index in (0, 12, 24) else "body", sharpness=100,
                 strength=0)
            for index in range(count)]


def fitted(items, **changes):
    options = settings(**changes)
    result, notes = _fit_story(items, options, shot_count=100)
    trimmed, trim_notes = _trim_pages(result, options)
    return trimmed, notes + trim_notes


def core_counts(items):
    return [sum(item["color"] in (PAGE, CORE) for item in page)
            for page in _pages(items, include_leading_extras=True)]


def test_six_core_average_divides_thirty_two_candidates_into_five_pages():
    source = story()
    legacy, _ = fitted(source, core_page_target=0, compression=0.8)
    result, notes = fitted(source)
    assert sum(item["color"] == PAGE for item in legacy) == 3
    assert sum(item["color"] == PAGE for item in result) == 5
    assert sorted(core_counts(result)) == [6, 6, 6, 7, 7]
    assert {item["frame"] for item in result} == {item["frame"] for item in source}
    assert notes == []


def test_zero_preserves_legacy_compression_and_never_changes_inputs():
    source = story()
    before = [dict(item) for item in source]
    options = settings(core_page_target=0)
    omitted = dict(options)
    del omitted["core_page_target"]
    assert _fit_story(source, options, 100) == _fit_story(source, omitted, 100)
    assert source == before
    assert core_target(options) == 0


@pytest.mark.parametrize("value, expected", [(1, 3), (20, 9), (5.5, 5.5), (-1, 0), (float("nan"), 0)])
def test_average_stays_within_core_limits(value, expected):
    assert core_target(settings(core_page_target=value, core_page_min=3, core_page_max=9)) == expected


def test_conflicting_core_limits_keep_the_minimum_as_existing_trim_does():
    assert core_target(settings(core_page_target=2, core_page_min=8, core_page_max=4)) == 8


def test_page_range_takes_priority_and_soft_selection_approaches_the_average():
    result, notes = fitted(story(), target_pages_min=3, target_pages_max=3)
    assert core_counts(result) == [7, 7, 7]
    assert len(result) == 21
    assert any("page limits allow 3" in note for note in notes)


def test_core_ceiling_can_choose_another_page_count_within_the_allowed_range():
    result, notes = fitted(story(), core_page_max=6)
    assert len(core_counts(result)) == 6
    assert max(core_counts(result)) <= 6
    assert len(result) == 32
    assert notes == []


def test_existing_core_cap_still_applies_when_page_range_cannot_hold_every_candidate():
    result, notes = fitted(story(), core_page_max=6, target_pages_min=3, target_pages_max=3)
    assert core_counts(result) == [6, 6, 6]
    assert any("Core selection adapts" in note for note in notes)


def test_page_range_is_prorated_for_analyzed_duration():
    result, notes = _fit_story(story(), settings(target_pages_min=12, target_pages_max=24,
                                              episode_minutes=24), 100, minutes=4)
    assert sum(item["color"] == PAGE for item in result) == 4
    assert any("page limits allow 2" in note for note in notes)


def test_extras_do_not_change_page_count_or_boundaries_and_are_not_cut_by_average():
    source = story()
    extras = [dict(frame=index * 100 + 50, color=EXTRA, name=NAMES[EXTRA], note="Extra, action",
                   rule="action", sharpness=100, strength=100) for index in range(31)]
    plain, _ = fitted(source)
    result, notes = fitted(sorted(source + extras, key=lambda item: item["frame"]))
    assert [item["frame"] for item in result if item["color"] == PAGE] == [
        item["frame"] for item in plain if item["color"] == PAGE]
    assert [item for item in result if item["color"] == EXTRA] == extras
    assert notes == []


def test_a_leading_extra_belongs_to_the_first_page_and_stays_unchanged():
    extra = dict(frame=-1, color=EXTRA, name=NAMES[EXTRA], note="Extra", rule="action", sharpness=10)
    result, notes = fitted([extra] + story())
    assert result[0] == extra
    assert sorted(core_counts(result)) == [6, 6, 6, 7, 7]
    assert notes == []


def test_scene_strength_breaks_ties_between_equally_balanced_divisions():
    source = story()
    source[7]["strength"] = 100
    source[2]["strength"] = 1000  # This cut would leave an unbalanced first page.
    result, _ = fitted(source)
    pages = [item["frame"] for item in result if item["color"] == PAGE]
    assert 700 in pages
    assert 200 not in pages
    assert sorted(core_counts(result)) == [6, 6, 6, 7, 7]


def test_too_few_existing_images_warns_without_inventing_markers():
    source = story(3)
    result, notes = fitted(source, target_pages_min=5, target_pages_max=6)
    assert len(result) == 3
    assert {item["frame"] for item in result} == {item["frame"] for item in source}
    assert sum(item["color"] == PAGE for item in result) == 3
    assert any("available images" in note for note in notes)


def test_time_gap_can_limit_page_count_and_reports_that_constraint():
    result, notes = fitted(story(), min_green_seconds=200)
    assert sum(item["color"] == PAGE for item in result) == 1
    assert any("minimum page gap" in note for note in notes)


def test_gap_can_force_uneven_pages_without_deleting_extras_for_the_target():
    source = story(8)
    for item, frame in zip(source, (0, 1, 2, 3, 4, 5, 100, 200)):
        item["frame"] = frame
    extra = dict(frame=6, color=EXTRA, name=NAMES[EXTRA], note="Extra", rule="action", sharpness=10)
    result, notes = fitted(sorted(source + [extra], key=lambda item: item["frame"]),
                           core_page_target=4, core_page_min=3, core_page_max=5,
                           target_pages_min=2, target_pages_max=2, min_green_seconds=50 / 24)
    assert sum(item["color"] == PAGE for item in result) == 2
    assert extra in result
    assert any("prevents an even Core distribution" in note for note in notes)


def test_propose_can_create_page_boundaries_from_existing_core_candidates_only():
    shots = []
    for index in range(32):
        frame = dict(frame=index * 100, sharpness=100, neighbor=0,
                     motion_blur=0, open_mouth=0, group=0)
        shots.append(dict(start=index * 100, end=index * 100 + 50,
                          opening=index == 0, frames=[frame]))
    result = propose({"fps": 24, "shots": shots}, settings())
    assert len(result["proposals"]) == 32
    assert sorted(core_counts(result["proposals"])) == [6, 6, 6, 7, 7]


def test_empty_core_pool_preserves_extras_and_has_no_invented_pages():
    extra = dict(frame=0, color=EXTRA, rule="action", sharpness=10)
    assert _fit_story([extra], settings(), 1) == ([extra], [])


def test_page_rounding_chooses_the_nearest_actual_average():
    result, _ = fitted(story(10), core_page_target=4)
    assert len(core_counts(result)) == 3  # 10 / 3 is nearer 4 than 10 / 2.
    assert sum(core_counts(result)) == 10


def test_soft_selection_removes_only_core_and_keeps_the_best_ranked_images():
    source = story(10)
    source[1]["rule"] = "speech_unverified"
    source[1]["sharpness"] = 200
    extras = [dict(frame=index * 100 + 50, color=EXTRA, name=NAMES[EXTRA], note="Extra",
                   rule="action", sharpness=0) for index in range(10)]
    result, _ = fitted(sorted(source + extras, key=lambda item: item["frame"]),
                       target_pages_min=1, target_pages_max=1, core_page_target=4)
    assert core_counts(result) == [5]
    assert all(item in result for item in extras)
    assert not any(item["frame"] == 100 for item in result)
    assert result[0]["color"] == PAGE


def test_total_minimum_can_keep_more_core_than_the_soft_target():
    result, notes = fitted(story(10), target_pages_min=1, target_pages_max=1,
                           core_page_target=4, total_page_min=8)
    assert core_counts(result) == [8]
    assert any("minimum keeps the Core average above its target" in note for note in notes)
    assert any("8 Core images over 1 pages give 8.00" in note for note in notes)


def test_fractional_average_uses_the_upper_edge_of_the_one_image_margin():
    result, _ = fitted(story(10), target_pages_min=1, target_pages_max=1, core_page_target=4.5)
    assert core_counts(result) == [5]


def test_existing_total_ceiling_still_applies_to_extras():
    extras = [dict(frame=index * 100 + 50, color=EXTRA, rule="action", sharpness=0) for index in range(10)]
    result, _ = fitted(sorted(story(10) + extras, key=lambda item: item["frame"]),
                       target_pages_min=1, target_pages_max=1, core_page_target=4,
                       total_page_max=8)
    assert core_counts(result) == [5]
    assert sum(item["color"] == EXTRA for item in result) == 3

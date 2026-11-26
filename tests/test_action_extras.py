"""Complete short action with distinct images without sacrificing the Core picks."""

from copy import deepcopy

import pytest

from tests.test_rules import analysis, frame, settings, shot
from vispa_mp.markers import CORE, EXTRA, PAGE
from vispa_mp.rules import _fit_story, _pages, _spread, _trim_pages, action_shot, drawing_change, propose


def held_action(**overrides):
    # Three distinct, dark drawings. Raw brightness differences can remain below
    # duplicate_diff even though their compositions are clearly different.
    frames = [frame(2, neighbor=0, signature=[0, 10, 0, 10]),
              frame(10, neighbor=0, signature=[10, 0, 10, 0]),
              frame(18, neighbor=0, signature=[0, 10, 0, 10]),
              frame(26, neighbor=0, signature=[0, 0, 10, 10])]
    return shot(0, 30, frames, motion=0, **overrides)


def test_a_held_action_keeps_its_core_and_adds_two_distinct_extras():
    source = analysis([held_action()], fps=25)
    original = deepcopy(source)
    options = settings(action_extras=3, min_marker_seconds=0.33, min_extra_seconds=0.12)
    result = propose(source, options)["proposals"]
    plain = propose(source, dict(options, action_extras=0))["proposals"]

    assert [(item["frame"], item["color"]) for item in plain] == [(26, CORE)]
    assert [(item["frame"], item["color"]) for item in result if item["color"] != EXTRA] == [(26, CORE)]
    assert sum(item["color"] == EXTRA for item in result) == 2
    assert all(item["rule"] == "action" for item in result if item["color"] == EXTRA)
    assert source == original


def test_shape_change_is_not_diluted_by_repeated_held_drawings():
    frames = []
    drawings = ([0, 10, 0, 10], [10, 0, 10, 0], [0, 0, 10, 10])
    for number in range(15):
        frames.append(frame(number, neighbor=0, signature=drawings[number // 5]))
    assert action_shot(shot(0, 25, frames, motion=0), frames,
                       settings(_fps=25, action_structure=0.35))


@pytest.mark.parametrize("left,right", [
    ([0, 0, 0, 0], [0.2, 0, 0.2, 0]),
    ([5, 10, 5, 10], [85, 90, 85, 90]),
    ([0, 0, 0, 0], [20, 20, 20, 20]),
])
def test_black_noise_or_brightness_alone_is_not_a_drawing_change(left, right):
    frames = [frame(2, signature=left), frame(22, signature=right)]
    assert drawing_change(frames[0], frames[1]) < 0.35
    assert not action_shot(shot(0, 25, frames, motion=0), frames, settings(_fps=25))


def test_missing_signatures_keep_the_existing_motion_test():
    frames = [frame(2, signature=[]), frame(22, signature=[])]
    assert action_shot(shot(0, 25, frames, motion=20), frames, settings(_fps=25))
    assert not action_shot(shot(0, 25, frames, motion=1), frames, settings(_fps=25))


def test_structure_sensitivity_and_action_duration_remain_adjustable():
    current = held_action()
    assert not action_shot(current, current["frames"], settings(_fps=25, action_structure=2))
    long = dict(current, end=125, motion=100)
    assert not action_shot(long, long["frames"], settings(_fps=25, action_max_seconds=2.5))


def test_extra_spacing_can_be_tighter_without_changing_core_spacing():
    frames = [frame(0, signature=[0, 20, 0, 20]),
              frame(3, signature=[20, 0, 20, 0]),
              frame(6, signature=[0, 0, 20, 20])]
    options = settings(_fps=25, min_marker_seconds=0.33, min_extra_seconds=0.12)
    selected = _spread(frames, shot(0, 7, frames), 2, [6], options, [frames[-1]], 100)
    assert [item["frame"] for item in selected] == [3, 0]
    wider = _spread(frames, shot(0, 7, frames), 2, [6],
                    dict(options, min_extra_seconds=0.33), [frames[-1]], 100)
    assert wider == []


def test_moving_but_sharp_candidates_remain_available_after_a_hold_is_taken():
    frames = [frame(2, neighbor=20, signature=[0, 10, 0, 10]),
              frame(10, neighbor=20, signature=[10, 0, 10, 0]),
              frame(26, neighbor=0, signature=[0, 0, 10, 10])]
    result = propose(analysis([shot(0, 30, frames, motion=20)], fps=25), settings())["proposals"]
    assert sum(item["color"] == EXTRA for item in result) == 2
    assert any(item["frame"] == 26 and item["color"] == CORE for item in result)


def test_extra_candidates_still_need_sharpness_and_low_blur():
    current = held_action()
    current["frames"][0]["motion_blur"] = 0.9
    current["frames"][1]["sharpness"] = 0.1
    current["frames"][2]["sharpness"] = 0.1
    result = propose(analysis([current], fps=25), settings())["proposals"]
    assert [(item["frame"], item["color"]) for item in result] == [(26, CORE)]


def test_manual_markers_block_extras_even_when_marked_shots_are_not_skipped():
    current = held_action()
    options = settings(_fps=25, min_extra_seconds=0.12)
    selected = _spread(current["frames"], current, 3, [26], options,
                       [current["frames"][-1]], 100, manual=[10])
    assert all(abs(item["frame"] - 10) >= 3 for item in selected)


def test_two_extras_do_not_repeat_the_same_drawing():
    current = held_action()
    selected = _spread(current["frames"], current, 3, [26], settings(_fps=25),
                       [current["frames"][-1]], 100)
    assert len(selected) == 2
    assert selected[0]["signature"] != selected[1]["signature"]


def core_story(count=80):
    return [dict(frame=index * 30, color=PAGE if index == 0 else CORE,
                 name="Page" if index == 0 else "Core", note="Core", rule="body",
                 sharpness=100, strength=0)
            for index in range(count)]


def core_options(**changes):
    return settings(core_page_target=8, core_page_min=2, core_page_max=12,
                    target_pages_min=2, target_pages_max=20, episode_minutes=0,
                    min_green_seconds=0, total_page_min=1, total_page_max=100, **changes)


def test_compression_still_reduces_pages_when_a_core_average_is_active():
    source = core_story()
    counts = []
    for compression in (0, 0.5, 1):
        options = core_options(compression=compression)
        fitted, _ = _fit_story(source, options, 100)
        trimmed, _ = _trim_pages(fitted, options)
        counts.append(sum(item["color"] == PAGE for item in trimmed))
        assert all(2 <= sum(item["color"] in (PAGE, CORE) for item in page)
                   <= 12 for page in _pages(trimmed))
    assert counts == [10, 6, 2]


def test_compression_does_not_discard_extras_or_count_them_as_core():
    source = core_story()
    extras = [dict(frame=index * 30 + 15, color=EXTRA, name="Extra", note="Extra",
                   rule="action", sharpness=0, strength=0) for index in range(30)]
    options = core_options(compression=1)
    fitted, _ = _fit_story(sorted(source + extras, key=lambda item: item["frame"]), options, 100)
    result, _ = _trim_pages(fitted, options)
    assert sum(item["color"] == PAGE for item in result) == 2
    assert [item for item in result if item["color"] == EXTRA] == extras


def test_compression_is_bounded_by_the_prorated_page_range():
    options = core_options(compression=1)
    options.update(target_pages_min=24, target_pages_max=48, episode_minutes=24)
    result, _ = _fit_story(core_story(), options, 100, minutes=4)
    assert sum(item["color"] == PAGE for item in result) == 4

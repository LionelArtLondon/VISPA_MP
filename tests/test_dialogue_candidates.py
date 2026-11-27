"""Every part of a dialogue gets a chance to reach visual recognition."""

from copy import deepcopy

import pytest

from vispa_mp.candidates import candidate_frames
from vispa_mp.preset import DEFAULTS


def shot(count=200, offset=0, **changes):
    frames = [{"frame": offset + number, "sharpness": 100.0, "neighbor": 0.1,
               "source_frame": number, "media": "chapter.mp4"} for number in range(count)]
    result = {"start": offset, "end": offset + count, "frames": frames}
    result.update(changes)
    return result


def options(**changes):
    return dict(DEFAULTS, **changes)


def numbers(selected):
    return [frame["frame"] for frame in selected]


def test_early_replies_cannot_exhaust_the_cap_before_later_speakers_are_sampled():
    source = shot(240)
    turns = [{"start": start, "end": start + 30, "speaker": f"speaker_{index % 2}",
              "confidence": 0.9, "source": "diarization"}
             for index, start in enumerate(range(0, 240, 30))]
    selected = candidate_frames(source, turns, options(max_tagged_per_shot=10))
    assert len(selected) == 10
    assert all(any(turn["start"] <= number < turn["end"] for number in numbers(selected)) for turn in turns)
    assert any(number >= 168 for number in numbers(selected))


def test_too_many_turns_are_spread_across_the_shot_instead_of_taking_only_the_first():
    source = shot(400)
    turns = [{"start": start, "end": start + 20} for start in range(0, 400, 20)]
    selected = candidate_frames(source, turns, options(max_tagged_per_shot=4))
    assert len(selected) == 4
    # The end candidate plus max-distance turn coverage spans the full scene.
    assert min(numbers(selected)) < 40
    assert max(numbers(selected)) >= 280
    assert any(140 <= number < 240 for number in numbers(selected))
    assert len({number // 20 for number in numbers(selected)}) == 4


def test_temporal_sampling_covers_mouth_poses_outside_a_cluster_of_sharp_frames():
    source = shot(120)
    for frame in source["frames"]:
        frame["sharpness"] = 1000 if frame["frame"] < 10 else 100
    selected = candidate_frames(source, [{"start": 0, "end": 100}],
                                options(max_tagged_per_shot=5, candidates_per_line=4, spread_tagged=0))
    positions = numbers(selected)
    assert any(0 <= number < 25 for number in positions)
    assert any(25 <= number < 50 for number in positions)
    assert any(50 <= number < 75 for number in positions)
    assert any(75 <= number < 100 for number in positions)
    assert any(number >= 84 for number in positions)


def test_held_and_moving_drawings_are_both_examined_inside_a_reply():
    source = shot(100)
    for frame in source["frames"]:
        frame["neighbor"] = 50 if frame["frame"] % 5 == 0 else 0.1
    selected = candidate_frames(source, [{"start": 0, "end": 70}],
                                options(max_tagged_per_shot=9, candidates_per_line=4))
    inside = [frame for frame in selected if frame["frame"] < 70]
    assert any(frame["hold"] for frame in inside)
    assert any(not frame["hold"] for frame in inside)
    assert len([frame for frame in inside if frame["hold"]]) <= 4
    assert len([frame for frame in inside if not frame["hold"]]) <= 4


@pytest.mark.parametrize("cap", [0, 1, 2, 4, 16])
def test_sampling_always_respects_the_cap_and_never_mutates_the_source(cap):
    source = shot()
    turns = [{"start": 0, "end": 100, "speaker": "A"}, {"start": 100, "end": 200, "speaker": "B"}]
    before = deepcopy((source, turns))
    selected = candidate_frames(source, turns, options(max_tagged_per_shot=cap))
    assert len(selected) <= cap
    assert len(set(numbers(selected))) == len(selected)
    assert numbers(selected) == sorted(numbers(selected))
    assert (source, turns) == before


def test_dialogue_turn_order_does_not_change_selected_candidates():
    source = shot(200)
    turns = [{"start": start, "end": start + 40} for start in range(0, 200, 40)]
    assert candidate_frames(source, turns, options()) == candidate_frames(source, list(reversed(turns)), options())


def test_clipped_and_overlapping_turns_stay_inside_the_shot_and_do_not_duplicate_frames():
    source = shot(120, offset=100)
    turns = [{"start": 0, "end": 80}, {"start": 80, "end": 150},
             {"start": 125, "end": 190}, {"start": 190, "end": 300}, {"start": 300, "end": 400}]
    selected = candidate_frames(source, turns, options(max_tagged_per_shot=12))
    assert all(100 <= number < 220 for number in numbers(selected))
    assert len(selected) == len(set(numbers(selected)))
    assert any(100 <= number < 150 for number in numbers(selected))
    assert any(150 <= number < 190 for number in numbers(selected))
    assert any(190 <= number < 220 for number in numbers(selected))


def test_no_dialogue_keeps_end_and_action_coverage():
    source = shot(120)
    source["frames"][-1]["sharpness"] = 200
    selected = candidate_frames(source, [], options(max_tagged_per_shot=10, spread_tagged=4))
    assert 119 in numbers(selected)
    assert any(number < 60 for number in numbers(selected))


def test_one_candidate_can_represent_the_end_even_when_there_is_no_held_drawing_there():
    source = shot(100)
    # A large moving tail, surrounded by a long quiet region, is not a hold.
    for frame in source["frames"][70:]:
        frame["neighbor"] = 50
    selected = candidate_frames(source, [{"start": 0, "end": 50}], options(max_tagged_per_shot=1))
    assert len(selected) == 1 and selected[0]["frame"] >= 70
    assert not selected[0]["hold"]

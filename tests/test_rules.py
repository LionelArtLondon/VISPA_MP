from vispa_mp.markers import CORE, EXTRA, PAGE, cue_warning, plan_apply
from vispa_mp.preset import DEFAULTS
from vispa_mp.rules import _trim_pages, propose


def frame(number, **overrides):
    base = {
        "frame": number, "sharpness": 100, "neighbor": 0.2, "signature": [float(number)] * 4,
        "open_mouth": 0.05, "closed_mouth": 0.8, "motion_blur": 0.0, "from_behind": 0.0,
        "face": 0.9, "expression": 0.2, "group": 0.05, "solo": 0.8, "image": "",
    }
    base.update(overrides)
    return base


def shot(start, end, frames, **overrides):
    base = {"start": start, "end": end, "opening": False, "cut_grey": 0, "cut_colour": 0,
            "cut_shape": 0, "motion": 1, "frames": frames}
    base.update(overrides)
    return base


def analysis(shots, **overrides):
    base = {"fps": 24, "shots": shots, "utterances": [], "manual_frames": []}
    base.update(overrides)
    return base


def settings(**overrides):
    data = dict(DEFAULTS)
    data.update(overrides)
    return data


def test_each_line_takes_the_open_mouth_and_the_end_of_the_shot_stays_blue():
    frames = [frame(10, open_mouth=0.9, closed_mouth=0.05), frame(90, open_mouth=0.05, closed_mouth=0.9)]
    result = propose(analysis([shot(0, 100, frames)], utterances=[{"start": 0, "end": 50}]), settings())
    by_frame = {item["frame"]: item for item in result["proposals"]}
    assert by_frame[10]["color"] == CORE
    assert by_frame[10]["note"] == "Line, mouth open"
    assert by_frame[90]["color"] == CORE
    assert by_frame[90]["note"] == "Body, end of shot"


def test_a_scene_opens_on_the_body_and_the_line_stays_blue():
    frames = [frame(10, open_mouth=0.9, closed_mouth=0.05), frame(90)]
    result = propose(analysis([shot(0, 100, frames, opening=True)], utterances=[{"start": 0, "end": 40}]), settings())
    by_frame = {item["frame"]: item for item in result["proposals"]}
    assert by_frame[90]["color"] == PAGE
    assert by_frame[90]["note"] == "Page start"
    assert by_frame[10]["color"] == CORE


def test_one_open_mouth_at_the_end_of_an_opening_shot_is_a_single_green():
    frames = [frame(50, open_mouth=0.92, closed_mouth=0.02)]
    result = propose(analysis([shot(0, 80, frames, opening=True)], utterances=[{"start": 20, "end": 70}]), settings())
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["color"] == PAGE
    assert result["proposals"][0]["note"] == "Page start, mouth open"


def test_closed_mouths_can_be_skipped():
    frames = [frame(20, open_mouth=0.1, closed_mouth=0.9), frame(90)]
    result = propose(analysis([shot(0, 100, frames)], utterances=[{"start": 0, "end": 40}]),
                     settings(mouth_fallback="none"))
    assert [item["frame"] for item in result["proposals"]] == [90]


def test_unverified_mouth_keeps_the_sharp_frame():
    frames = [frame(20, sharpness=40, open_mouth=0.0, closed_mouth=0.0, face=0.0),
              frame(30, sharpness=80, open_mouth=0.0, closed_mouth=0.0, face=0.0)]
    result = propose(analysis([shot(0, 100, frames)], utterances=[{"start": 0, "end": 50}]),
                     settings(mouth_fallback="sharp", end_fraction=0.1))
    speech = [item for item in result["proposals"] if "not verified" in item["note"]]
    assert [item["frame"] for item in speech] == [30]


def test_a_hold_with_an_open_mouth_beats_a_sharper_closed_cycle():
    frames = [frame(10, neighbor=0.1, sharpness=50, open_mouth=0.85, closed_mouth=0.05),
              frame(12, neighbor=30, sharpness=200, open_mouth=0.1, closed_mouth=0.9)]
    result = propose(analysis([shot(0, 100, frames)], utterances=[{"start": 0, "end": 40}]), settings())
    speech = [item for item in result["proposals"] if item["note"] == "Line, mouth open"]
    assert [item["frame"] for item in speech] == [10]


def test_a_speaking_pose_needs_the_mouth_interior_and_then_the_teeth():
    teeth_only = frame(12, sharpness=180, open_mouth=0.62, closed_mouth=0.05,
                       teeth=0.95, upper_teeth_only=0.9, clenched_teeth=0.4)
    interior = frame(24, sharpness=50, open_mouth=0.9, closed_mouth=0.03, tongue=0.55, teeth=0.08)
    with_teeth = frame(36, sharpness=70, open_mouth=0.84, closed_mouth=0.04, tongue=0.4, teeth=0.82)
    result = propose(analysis([shot(0, 80, [teeth_only, interior])], utterances=[{"start": 0, "end": 50}]),
                     settings(min_marker_seconds=8 / 24))
    speech = [item for item in result["proposals"] if item["note"] == "Line, mouth open"]
    assert [item["frame"] for item in speech] == [24]
    both = propose(analysis([shot(0, 80, [interior, with_teeth])], utterances=[{"start": 0, "end": 50}]),
                   settings(min_marker_seconds=8 / 24))
    speech = [item for item in both["proposals"] if item["note"] == "Line, mouth open"]
    assert [item["frame"] for item in speech] == [36]


def test_cycle_frame_is_used_when_every_hold_has_the_mouth_closed():
    frames = [frame(10, neighbor=0.1, sharpness=80, open_mouth=0.05, closed_mouth=0.9),
              frame(14, neighbor=25, sharpness=70, open_mouth=0.88, closed_mouth=0.04)]
    result = propose(analysis([shot(0, 100, frames)], utterances=[{"start": 0, "end": 40}]), settings())
    speech = [item for item in result["proposals"] if item["note"] == "Line, mouth open"]
    assert [item["frame"] for item in speech] == [14]


def test_action_extras_are_cyan_and_a_duplicate_of_the_body_is_dropped():
    frames = [frame(2, signature=[1, 1, 1, 1]), frame(12, signature=[9, 9, 9, 9]),
              frame(22, signature=[1, 1, 1, 1])]
    result = propose(analysis([shot(0, 24, frames, motion=30)]), settings(action_extras=2, min_marker_seconds=4 / 24))
    colours = [(item["frame"], item["color"]) for item in result["proposals"]]
    assert (22, CORE) in colours
    assert (12, EXTRA) in colours
    assert (2, EXTRA) not in colours


def test_turning_action_extras_off_removes_the_cyan_frames():
    frames = [frame(2), frame(12), frame(22)]
    base = analysis([shot(0, 24, frames, motion=30)])
    full = propose(base, settings(action_extras=2, min_marker_seconds=4 / 24))
    quiet = propose(base, settings(action_extras=0, min_marker_seconds=4 / 24))
    assert sum(item["color"] == EXTRA for item in full["proposals"]) == 2
    assert [item["color"] for item in quiet["proposals"]] == [CORE]


def test_a_group_shot_can_open_a_page():
    frames = [frame(80, group=0.8, solo=0.1)]
    result = propose(analysis([shot(0, 100, frames)]), settings())
    assert result["proposals"][0]["color"] == PAGE
    assert result["proposals"][0]["note"] == "Page start, group shot"


def test_marked_shots_are_left_alone_and_a_page_ceiling_keeps_one_corps():
    frames = [frame(10, open_mouth=0.9, closed_mouth=0.1), frame(90)]
    untouched = propose(analysis([shot(0, 100, frames, opening=True)], manual_frames=[40],
                                 utterances=[{"start": 0, "end": 30}]), settings())
    assert untouched["proposals"] == []
    opening = shot(0, 40, [frame(30)], opening=True)
    later = shot(40, 100, [frame(55, open_mouth=0.9, closed_mouth=0.05), frame(90)], cut_grey=0)
    crowded = propose(analysis([opening, later], utterances=[{"start": 40, "end": 70}]),
                      settings(core_page_min=1, core_page_max=1, total_page_min=1, total_page_max=4,
                               target_pages_min=1, target_pages_max=1))
    assert [item["color"] for item in crowded["proposals"]] == [PAGE]


def test_compression_keeps_the_page_count_inside_the_chosen_range():
    shots = [shot(0, 80, [frame(40)], opening=True)]
    for index, start in enumerate((80, 160, 240, 320), start=1):
        shots.append(shot(start, start + 80, [frame(start + 40)], cut_grey=80))
    loose = propose(analysis(shots), settings(compression=0, target_pages_min=5, target_pages_max=5, min_green_seconds=1 / 24, episode_minutes=0,
                                              core_page_min=1, total_page_min=1))
    tight = propose(analysis(shots), settings(compression=1, target_pages_min=2, target_pages_max=2, min_green_seconds=1 / 24, episode_minutes=0,
                                              core_page_min=1, total_page_min=1))
    assert sum(item["color"] == PAGE for item in loose["proposals"]) == 5
    assert sum(item["color"] == PAGE for item in tight["proposals"]) == 2
    assert tight["proposals"][0]["color"] == PAGE
    assert tight["proposals"][-1]["color"] == PAGE


def test_two_scene_opens_respect_the_minimum_gap():
    first = shot(0, 40, [frame(30)], opening=True)
    second = shot(40, 80, [frame(70)], cut_grey=80)
    result = propose(analysis([first, second]), settings(min_green_seconds=100 / 24))
    colours = [item["color"] for item in result["proposals"]]
    assert colours == [PAGE, CORE]


def test_a_page_drops_cyan_before_corps_and_stops_at_the_floor():
    page = [
        {"frame": 10, "color": PAGE, "rule": "page", "sharpness": 10},
        {"frame": 20, "color": CORE, "rule": "speech", "sharpness": 40},
        {"frame": 30, "color": CORE, "rule": "body", "sharpness": 90},
        {"frame": 35, "color": CORE, "rule": "body", "sharpness": 70},
        {"frame": 40, "color": EXTRA, "rule": "action", "sharpness": 80},
        {"frame": 50, "color": EXTRA, "rule": "action", "sharpness": 20},
    ]
    kept, warnings = _trim_pages(page, settings(
        core_page_min=1, core_page_max=6, total_page_min=1, total_page_max=4))
    assert [item["frame"] for item in kept] == [10, 20, 30, 35]
    assert warnings == []
    kept, warnings = _trim_pages(page, settings(
        core_page_min=3, core_page_max=2, total_page_min=1, total_page_max=8))
    assert [item["frame"] for item in kept] == [10, 30, 35, 40, 50]
    assert warnings and "maximum" in warnings[0]


def test_a_short_range_gets_its_share_of_the_episode_pages():
    from vispa_mp.rules import analyzed_minutes, page_goal
    data = settings(compression=0, target_pages_min=45, target_pages_max=60, episode_minutes=24)
    assert page_goal(data) == 60
    assert page_goal(data, minutes=4) == 10
    assert page_goal(settings(episode_minutes=0, compression=0, target_pages_max=60), minutes=4) == 60
    assert abs(analyzed_minutes({"fps": 50, "range": [188822, 199480]}) - 3.55) < 0.01
    assert analyzed_minutes({"fps": 24, "shots": [{"start": 0, "end": 1440}]}) == 1.0
    assert analyzed_minutes({"fps": 0, "shots": []}) is None


def test_gaps_in_seconds_keep_their_length_at_any_frame_rate():
    from vispa_mp.rules import gap_frames
    data = settings(min_marker_seconds=0.33, min_green_seconds=2.0)
    assert gap_frames(dict(data, _fps=24), "min_marker_seconds") == 8
    assert gap_frames(dict(data, _fps=50), "min_marker_seconds") == 16
    assert gap_frames(dict(data, _fps=50), "min_green_seconds") == 100
    assert gap_frames(data, "min_green_seconds") == 48  # no frame rate known: 24 fps
    # Two lines 10 frames apart: 0.4 s at 25 fps, 0.2 s at 50 fps.
    frames = [frame(10, open_mouth=0.9, closed_mouth=0.05), frame(20, open_mouth=0.9, closed_mouth=0.05)]
    lines = [{"start": 0, "end": 15}, {"start": 15, "end": 40}]
    slow = propose(analysis([shot(0, 100, frames)], fps=25, utterances=lines), settings(min_marker_seconds=0.3))
    fast = propose(analysis([shot(0, 100, frames)], fps=50, utterances=lines), settings(min_marker_seconds=0.3))
    assert {10, 20} <= {item["frame"] for item in slow["proposals"]}
    assert not {10, 20} <= {item["frame"] for item in fast["proposals"]}

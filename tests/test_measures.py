from vispa_mp.speech import map_turns, turns_from_probs
from vispa_mp.tags import features_from_probs
from vispa_mp.timebase import absolute_mark, format_timecode


def test_a_silence_splits_two_lines_and_a_short_blip_is_dropped():
    settings = {"speech_threshold": 0.5, "speech_min_silence_ms": 200, "speech_min_duration_ms": 250, "speech_pad_ms": 0}
    probs = [1.0] * 20 + [0.0] * 20 + [1.0] * 20
    turns = turns_from_probs(probs, settings)
    assert len(turns) == 2
    assert turns[0]["end"] < turns[1]["start"]
    blip = [0.0] * 5 + [1.0] * 2 + [0.0] * 10 + [1.0] * 20
    assert len(turns_from_probs(blip, settings)) == 1


def test_turns_land_on_timeline_frames():
    mapped = map_turns([{"start": 1.0, "end": 2.0}], 100, 25)
    assert mapped == [{"start": 125, "end": 150}]


def test_timecode_and_marks_use_the_timeline_clock():
    base = {"fps": 24, "start_frame": 86400, "start_timecode": "01:00:00:00", "drop": False}
    assert format_timecode(86400, base) == "01:00:00:00"
    assert format_timecode(86600, base) == "01:00:08:08"
    assert absolute_mark(10, 86400) == 86410
    assert absolute_mark(86500, 86400) == 86500


def test_tag_scores_read_mouth_group_and_expression():
    scores = features_from_probs({
        "open_mouth": 0.8, "closed_mouth": 0.1, "motion_blur": 0.6, "from_behind": 0.0,
        "2girls": 0.7, "solo": 0.2, "smile": 0.4, "1girl": 0.3,
        "teeth": 0.66, "tongue": 0.4, "upper_teeth_only": 0.2,
    })
    assert scores["open_mouth"] == 0.8
    assert scores["teeth"] == 0.66
    assert scores["tongue"] == 0.4
    assert scores["upper_teeth_only"] == 0.2
    assert scores["group"] == 0.7
    assert scores["expression"] == 0.4
    assert scores["motion_blur"] == 0.6
    assert scores["face"] >= 0.7

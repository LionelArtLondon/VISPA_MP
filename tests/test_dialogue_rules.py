"""Audio turns guide images without claiming who is visible on the picture."""

from copy import deepcopy

import pytest

from tests.test_rules import analysis, frame, settings, shot
from vispa_mp.markers import CORE, PAGE
from vispa_mp.rules import _budget_finish, _pick_speech, _trim_pages, propose


def turn(start, end, speaker=None, **changes):
    result = dict(start=start, end=end, source="speaker_change", confidence=0.9)
    if speaker is not None:
        result["speaker"] = speaker
    result.update(changes)
    return result


def options(**changes):
    return settings(**{**dict(action_extras=0, target_pages_min=1, target_pages_max=1,
                             episode_minutes=0, core_page_min=0, core_page_max=8,
                             total_page_min=0, total_page_max=8), **changes})


def speaking(number, **changes):
    return frame(number, **{**dict(open_mouth=0.9, closed_mouth=0.05), **changes})


def late_profile():
    from tests.test_learning_integration import role_profile
    from tests.test_learning_model import _profile
    return role_profile(_profile(), "core", "shot_phase", 15)


@pytest.mark.parametrize("personal", [False, True])
def test_adjacent_audio_turns_without_a_silence_keep_their_good_mouths(personal):
    source = analysis([shot(0, 160, [speaking(20), speaking(60, open_mouth=0.5),
                                    speaking(100), frame(140)])],
                      utterances=[turn(0, 80), turn(80, 160)])
    before = deepcopy(source)
    result = propose(source, options(core_page_max=2, total_page_max=2),
                     profile=late_profile() if personal else None)
    assert [item["frame"] for item in result["proposals"]] == [20, 100]
    assert [item["dialogue_turn"] for item in result["proposals"]] == [0, 80]
    assert all(item["speech_quality_ok"] for item in result["proposals"])
    assert all("dialogue_speaker" not in item for item in result["proposals"])
    assert source == before


def test_anonymous_voice_change_does_not_invent_a_visual_character_label():
    source = analysis([shot(0, 160, [speaking(20), speaking(100)])],
                      utterances=[turn(0, 80), turn(80, 160)])
    result = propose(source, options())["proposals"]
    assert {item["dialogue_turn"] for item in result} == {0, 80}
    assert all("dialogue_speaker" not in item for item in result)


@pytest.mark.parametrize("line", [turn(0, 100, "voice-a", confidence=0.2),
                                  turn(0, 100, "voice-a", confidence=float("nan")),
                                  {"start": 0, "end": 100}])
def test_uncertain_and_legacy_audio_keep_their_previous_personal_ranking(line):
    frames = [speaking(20, personal_core=0.01), speaking(60, open_mouth=0.5, personal_core=0.99)]
    picked, _kind = _pick_speech(frames, line, options(), 100)
    assert picked["frame"] == 60


@pytest.mark.parametrize("lines", [[turn(0, 100, confidence=0.1)],
                                   [turn(0, 100), turn(20, 100)],
                                   [{"start": 0, "end": 100}]])
def test_unreliable_or_overlapping_turns_do_not_gain_identity_metadata(lines):
    source = analysis([shot(0, 100, [speaking(50)])], utterances=lines)
    result = propose(source, options())["proposals"]
    assert result
    assert all("dialogue_speaker" not in item and "dialogue_turn" not in item for item in result)


def test_approved_speaker_identity_is_preserved_only_as_audio_metadata():
    source = analysis([shot(0, 100, [speaking(50)])], utterances=[turn(0, 100, "audio-1:voice-b")])
    result = propose(source, options())["proposals"]
    assert result[0]["dialogue_speaker"] == "audio-1:voice-b"
    assert result[0]["dialogue_turn"] == 0
    assert result[0]["name"] == "Core"


def test_offscreen_voice_keeps_a_reaction_fallback_without_a_speaker_claim():
    source = analysis([shot(0, 160, [frame(20, face=0, open_mouth=0, closed_mouth=0),
                                    frame(100, face=0, open_mouth=0, closed_mouth=0)])],
                      utterances=[turn(0, 80, "voice-a"), turn(80, 160, "voice-b")])
    result = propose(source, options())["proposals"]
    assert len(result) == 2
    assert all("speech_quality_ok" not in item for item in result)
    assert all("dialogue_speaker" not in item and "dialogue_turn" not in item for item in result)


def test_turns_do_not_bypass_the_configured_marker_gap():
    source = analysis([shot(0, 100, [speaking(30), speaking(35)])],
                      utterances=[turn(0, 33), turn(33, 100)])
    result = propose(source, options(min_marker_seconds=1))["proposals"]
    assert len(result) == 1


def _dialogue_page(named=True):
    result = [{"frame": 10, "color": PAGE, "rule": "page", "sharpness": 100}]
    for number, speech_turn, preference in ((30, 20, 0.99), (50, 20, 0.95), (110, 80, 0.01)):
        item = dict(frame=number, color=CORE, rule="speech", sharpness=100,
                    speech_quality_ok=True, dialogue_turn=speech_turn, personal_core=preference)
        if named:
            item["dialogue_speaker"] = "a" if speech_turn == 20 else "b"
        result.append(item)
    return result


@pytest.mark.parametrize("named", [False, True])
def test_page_limits_prefer_dialogue_diversity_over_more_images_from_the_same_turn(named):
    page = _dialogue_page(named)
    before = deepcopy(page)
    kept, _warnings = _trim_pages(page, options(core_page_min=1, core_page_max=3))
    assert {item["frame"] for item in kept} == {10, 30, 110}
    assert page == before


def test_disabling_the_mouth_requirement_disables_cached_turn_retention():
    kept, _warnings = _trim_pages(_dialogue_page(), options(require_open_mouth=False,
                                                         core_page_min=1, core_page_max=3))
    assert {item["frame"] for item in kept} == {10, 30, 50}


def test_dialogue_priority_remains_soft_when_the_page_has_room_for_only_one_speech_image():
    page = _dialogue_page()
    kept, _warnings = _trim_pages(page, options(core_page_min=1, core_page_max=2))
    assert len(kept) == 2
    assert kept[0]["frame"] == 10


def test_global_budget_reconsiders_dialogue_coverage_after_each_removal():
    from vispa_mp.marker_budget import budget_settings
    from tests.test_marker_budget_rules import options as budget_options

    page = _dialogue_page()
    page.insert(3, dict(frame=60, color=CORE, rule="speech", sharpness=100,
                       speech_quality_ok=True, dialogue_turn=20, dialogue_speaker="a", personal_core=0.9))
    page.append(dict(frame=130, color=CORE, rule="speech", sharpness=100,
                     speech_quality_ok=True, dialogue_turn=80, dialogue_speaker="b", personal_core=0.001))
    source = analysis([shot(0, 160, [speaking(item["frame"]) for item in page])])
    config = budget_options(target=3, minimum=3, maximum=3, core_page_min=1)
    config["_fps"] = 24
    budget = budget_settings(config, source)
    sources = {item["frame"]: ((0, 160), 100, speaking(item["frame"])) for item in page}
    kept, _warnings, actual = _budget_finish(page, [], budget, config, sources, [], set(), set())
    assert actual == 3
    assert [item["frame"] for item in kept] == [10, 30, 110]


@pytest.mark.parametrize("edit", ["user", "user_role", "budget"])
def test_dialogue_diversity_does_not_override_a_manual_role_choice(edit):
    page = _dialogue_page()
    config = options(core_page_min=1, core_page_max=3)
    if edit == "user":
        page[2]["rule"] = "user"
    elif edit == "user_role":
        page[2]["user_role"] = True
    else:
        config["_budget_protected_frames"] = {50}
    kept, _warnings = _trim_pages(page, config)
    assert 50 in {item["frame"] for item in kept}

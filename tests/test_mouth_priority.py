"""A valid speaking pose must not lose to a late closed-mouth hold by default."""

from copy import deepcopy

import pytest

from tests.test_rules import analysis, frame, settings, shot
from vispa_mp.markers import CORE, PAGE
from vispa_mp.rules import _pick_body, _trim_pages, propose


def _end_frames(**open_changes):
    opened = frame(70, sharpness=60, hold=False, open_mouth=0.9, closed_mouth=0.05,
                   personal_core=0.05)
    opened.update(open_changes)
    closed = frame(90, sharpness=100, hold=True, open_mouth=0.05, closed_mouth=0.9,
                   personal_core=0.99)
    return opened, closed


def test_valid_open_mouth_in_the_end_region_beats_a_personally_preferred_closed_hold():
    opened, closed = _end_frames()
    source = shot(0, 100, [opened, closed])
    assert _pick_body(source["frames"], source, [{"start": 0, "end": 80}], settings(), 100) is opened


@pytest.mark.parametrize("case", ["silent", "outside_line", "before_end", "disabled", "no_open"])
def test_end_preference_stays_in_charge_without_an_applicable_verified_mouth(case):
    opened, closed = _end_frames()
    lines = [{"start": 0, "end": 80}]
    options = settings()
    if case == "silent":
        lines = []
    elif case == "outside_line":
        lines = [{"start": 0, "end": 60}]
    elif case == "before_end":
        opened["frame"] = 60
    elif case == "disabled":
        options["require_open_mouth"] = False
    else:
        opened.update(open_mouth=0.1, closed_mouth=0.8)
    source = shot(0, 100, [opened, closed])
    assert _pick_body(source["frames"], source, lines, options, 100) is closed


@pytest.mark.parametrize("changes", [{"motion_blur": 0.9}, {"sharpness": 0.1}, {"sharpness": 20},
                                    {"from_behind": 0.9}, {"closed_mouth": 0.95}])
def test_mouth_priority_never_relaxes_image_quality_or_mouth_verification(changes):
    opened, closed = _end_frames(**changes)
    source = shot(0, 100, [opened, closed])
    assert _pick_body(source["frames"], source, [{"start": 0, "end": 80}], settings(), 100) is closed


def _page(speech_quality=True):
    return [
        {"frame": 10, "color": PAGE, "rule": "page", "sharpness": 100},
        {"frame": 30, "color": CORE, "rule": "speech", "sharpness": 60,
         "personal_core": 0.05, "speech_quality_ok": speech_quality},
        {"frame": 90, "color": CORE, "rule": "body", "sharpness": 100, "personal_core": 0.99},
    ]


@pytest.mark.parametrize("ceiling", ["core", "total", "average"])
def test_page_pressure_preserves_good_verified_dialogue_before_a_closed_end_hold(ceiling):
    page = _page()
    before = deepcopy(page)
    changes = dict(core_page_min=1, core_page_max=8, total_page_min=1, total_page_max=12)
    if ceiling == "core":
        changes["core_page_max"] = 2
    elif ceiling == "total":
        changes["total_page_max"] = 2
    else:
        changes["core_page_target"] = 1
    kept, _warnings = _trim_pages(page, settings(**changes))
    assert [item["frame"] for item in kept] == [10, 30]
    assert page == before


def test_quality_semantics_survive_an_earlier_page_to_core_reassignment():
    page = _page()
    page[1]["rule"] = "body"
    kept, _warnings = _trim_pages(page, settings(core_page_min=1, core_page_max=2))
    assert [item["frame"] for item in kept] == [10, 30]


def test_disabling_mouth_requirement_also_disables_semantic_retention_of_cached_metadata():
    page = _page()
    kept, _warnings = _trim_pages(page, settings(require_open_mouth=False, core_page_min=1, core_page_max=2))
    assert [item["frame"] for item in kept] == [10, 90]


@pytest.mark.parametrize("protection", ["user", "user_role", "budget"])
def test_dialogue_priority_does_not_discard_explicit_role_choices(protection):
    page = _page()
    options = settings(core_page_min=1, core_page_max=2)
    if protection == "user":
        page[-1]["rule"] = "user"
    elif protection == "user_role":
        page[-1]["user_role"] = True
    else:
        options["_budget_protected_frames"] = {90}
    kept, _warnings = _trim_pages(page, options)
    assert [item["frame"] for item in kept] == [10, 90]


@pytest.mark.parametrize("poor_quality", [None, "blur", "relative", "absolute"])
def test_real_proposals_mark_only_quality_approved_speech_for_retention(poor_quality):
    speaking = frame(60, sharpness=60, open_mouth=0.9, closed_mouth=0.05)
    if poor_quality == "blur":
        speaking["motion_blur"] = 0.9
    elif poor_quality == "relative":
        speaking["sharpness"] = 20
    elif poor_quality == "absolute":
        speaking["sharpness"] = 0.1
    source = analysis([shot(0, 50, [frame(40)], opening=True),
                       shot(50, 150, [speaking, frame(140)])], utterances=[{"start": 50, "end": 100}])
    original = deepcopy(source)
    options = settings(target_pages_min=1, target_pages_max=1, episode_minutes=0,
                       core_page_min=1, core_page_max=2, total_page_min=1, total_page_max=8,
                       action_extras=0)
    loose = propose(source, {**options, "core_page_max": 8})["proposals"]
    speech = next(item for item in loose if item["frame"] == 60)
    assert speech["rule"] == "speech"
    assert speech.get("speech_quality_ok", False) is (poor_quality is None)
    kept = propose(source, options)["proposals"]
    assert [item["frame"] for item in kept] == ([40, 60] if poor_quality is None else [40, 140])
    assert source == original


def test_budget_candidates_carry_the_same_quality_approved_speech_priority():
    from vispa_mp.rules import _budget_candidates, mark_holds

    speaking = frame(60, sharpness=60, open_mouth=0.9, closed_mouth=0.05)
    source = shot(50, 150, [speaking, frame(140)])
    mark_holds(source["frames"], 1.15)
    candidates = _budget_candidates(source, source["frames"], [{"start": 50, "end": 100}], settings(), 100)
    speech = next(item for item in candidates if item["frame"] == 60)
    assert speech["speech_quality_ok"] is True
    assert "speech_quality_ok" not in next(item for item in candidates if item["frame"] == 140)


def test_an_active_personal_profile_cannot_restore_a_late_closed_pose_over_a_good_speaking_pose():
    from tests.test_learning_integration import role_profile
    from tests.test_learning_model import _profile
    from vispa_mp.learning_model import apply_profile

    personal = role_profile(_profile(), "core", "shot_phase", 15)
    opened, closed = _end_frames()
    source = analysis([shot(0, 100, [opened, closed], opening=True)],
                      utterances=[{"start": 0, "end": 80}])
    scored = apply_profile(source, personal)["shots"][0]["frames"]
    assert scored[1]["personal_core"] > scored[0]["personal_core"]
    options = settings(action_extras=0, target_pages_min=1, target_pages_max=1, episode_minutes=0)
    assert [item["frame"] for item in propose(source, options, profile=personal)["proposals"]] == [70]


def test_personal_end_preference_does_not_drop_good_earlier_dialogue_under_page_pressure():
    from tests.test_learning_integration import role_profile
    from tests.test_learning_model import _profile

    personal = role_profile(_profile(), "core", "shot_phase", 15)
    speaking = frame(60, sharpness=60, open_mouth=0.9, closed_mouth=0.05)
    source = analysis([shot(0, 50, [frame(40)], opening=True),
                       shot(50, 150, [speaking, frame(140)])], utterances=[{"start": 50, "end": 100}])
    options = settings(target_pages_min=1, target_pages_max=1, episode_minutes=0,
                       core_page_min=1, core_page_max=2, total_page_min=1, total_page_max=8,
                       action_extras=0)
    assert [item["frame"] for item in propose(source, options, profile=personal)["proposals"]] == [40, 60]


@pytest.mark.parametrize("personal", [False, True])
def test_global_budget_keeps_a_verified_speaking_page_after_it_becomes_core(personal):
    profile = None
    if personal:
        from tests.test_learning_integration import role_profile
        from tests.test_learning_model import _profile
        profile = role_profile(_profile(), "core", "expression", 15)
    source = analysis([
        shot(0, 100, [frame(40)], opening=True),
        shot(100, 200, [frame(140, open_mouth=0.9, closed_mouth=0.05)], opening=True),
        shot(200, 300, [frame(240, expression=1)], opening=True),
    ], utterances=[{"start": 100, "end": 160}])
    options = settings(global_markers_enabled=True, global_markers_auto=False,
                       global_markers_min=2, global_markers_target=2, global_markers_max=2,
                       target_pages_min=1, target_pages_max=1, episode_minutes=0,
                       core_page_min=1, core_page_max=8, total_page_min=1, total_page_max=8,
                       action_extras=0)
    result = propose(source, options, profile=profile)
    assert [item["frame"] for item in result["proposals"]] == [40, 140]
    assert [item["color"] for item in result["proposals"]] == [PAGE, CORE]
    assert result["proposals"][1]["rule"] == "body"
    assert result["proposals"][1]["speech_quality_ok"] is True
    assert result["marker_budget"]["actual"] == 2

"""Comparison reranks existing measurements while preserving the working review."""

from copy import deepcopy

import pytest

from tests.test_learning_integration import options, personal_profile, selection_analysis
from tests.test_marker_budget_rules import options as budget_options, wide_shot
from vispa_mp import comparison
from vispa_mp.rules import propose


def test_standard_and_personal_variants_match_the_real_selector(personal_profile):
    analysis, settings = selection_analysis(), options()
    before = deepcopy((analysis, settings, personal_profile))
    messages = []
    result = comparison.build_comparison(analysis, settings, personal_profile, progress=messages.append)
    standard, personal = result["variants"]
    assert standard["name"] == "MP standard rules" and standard["profile"] is None
    assert personal["name"] == "Earlier poses" and personal["profile"] == personal_profile
    assert standard["proposals"] == propose(analysis, settings)["proposals"]
    assert personal["proposals"] == propose(analysis, settings, personal_profile)["proposals"]
    assert [item["frame"] for item in standard["proposals"]] == [90]
    assert [item["frame"] for item in personal["proposals"]] == [70]
    assert (analysis, settings, personal_profile) == before
    assert messages == ["Comparing selection: MP standard rules", "Comparing selection: Earlier poses"]
    result["analysis"]["shots"][0]["frames"][0]["sharpness"] = 0
    result["settings"]["custom"] = True
    personal["profile"]["name"] = "Changed copy"
    assert (analysis, settings, personal_profile) == before


def test_review_additions_exclusions_and_order_do_not_bias_the_comparison(personal_profile):
    analysis = wide_shot()
    analysis.update(_budget_user_proposals=[dict(frame=10, color="Green", rule="user", note="Keep", sharpness=100)],
                    _budget_excluded_frames=[30, 50, 70],
                    manual_frames=[90], _budget_manual_frames=[90], custom_context="preserved")
    before = deepcopy(analysis)
    settings = budget_options(target=4)
    result = comparison.build_comparison(analysis, settings, personal_profile)
    clean = deepcopy(analysis)
    clean.pop("_budget_user_proposals")
    clean.pop("_budget_excluded_frames")
    assert result["analysis"] == clean
    assert result["variants"][0]["proposals"] == propose(clean, settings)["proposals"]
    assert all(item["frame"] != 90 for variant in result["variants"] for item in variant["proposals"])
    assert all(item.get("rule") != "user" for variant in result["variants"] for item in variant["proposals"])
    assert analysis == before


def test_speech_settings_refresh_both_variants_from_the_same_probabilities(personal_profile, monkeypatch):
    analysis = selection_analysis()
    analysis["speech_tracks"] = [{"start": 0, "end": 100, "probs": [0.9] * 20}]
    analysis["utterances"] = [{"start": 90, "end": 100}]
    observed = []

    def refresh(measured, settings):
        assert measured["speech_tracks"] == analysis["speech_tracks"]
        assert settings["speech_threshold"] == 0.75
        return [{"start": 0, "end": 100}]

    def select(measured, settings, profile=None):
        observed.append(deepcopy(measured["utterances"]))
        return {"proposals": [], "warnings": []}

    monkeypatch.setattr(comparison, "refresh_utterances", refresh)
    monkeypatch.setattr(comparison, "propose", select)
    result = comparison.build_comparison(analysis, options(speech_threshold=0.75), personal_profile)
    assert observed == [[{"start": 0, "end": 100}]] * 2
    assert result["analysis"]["utterances"] == [{"start": 0, "end": 100}]
    assert analysis["utterances"] == [{"start": 90, "end": 100}]


@pytest.mark.parametrize("analysis", [None, {}, {"shots": []}, {"shots": [{"start": 0, "end": 100, "frames": []}]}])
def test_missing_measured_images_gives_a_clear_error(analysis, personal_profile):
    with pytest.raises(ValueError, match="Analyze.*examined images"):
        comparison.build_comparison(analysis, options(), personal_profile)


def test_invalid_profile_is_rejected_before_any_selection(monkeypatch):
    monkeypatch.setattr(comparison, "propose", lambda *_args, **_kwargs: pytest.fail("Invalid profiles cannot be scored"))
    with pytest.raises(ValueError, match="compatible.*profile"):
        comparison.build_comparison(selection_analysis(), options(), {"name": "Invalid"})


def test_cancel_before_start_does_not_select_or_return_partial_data(personal_profile, monkeypatch):
    monkeypatch.setattr(comparison, "propose", lambda *_args, **_kwargs: pytest.fail("Cancelled comparisons do no work"))
    with pytest.raises(InterruptedError, match="cancelled"):
        comparison.build_comparison(selection_analysis(), options(), personal_profile, cancel=lambda: True)


def test_cancel_after_first_selection_does_not_start_the_second(personal_profile, monkeypatch):
    calls, state = [], {"cancelled": False}

    def select(*_args, **_kwargs):
        calls.append(True)
        state["cancelled"] = True
        return {"proposals": [], "warnings": []}

    monkeypatch.setattr(comparison, "propose", select)
    with pytest.raises(InterruptedError):
        comparison.build_comparison(selection_analysis(), options(), personal_profile, cancel=lambda: state["cancelled"])
    assert calls == [True]


def test_cancel_from_progress_is_checked_before_selection(personal_profile, monkeypatch):
    state = {"cancelled": False}
    monkeypatch.setattr(comparison, "propose", lambda *_args, **_kwargs: pytest.fail("Cancelled progress must stop before selection"))
    with pytest.raises(InterruptedError):
        comparison.build_comparison(selection_analysis(), options(), personal_profile,
                                    progress=lambda _message: state.update(cancelled=True),
                                    cancel=lambda: state["cancelled"])


def test_empty_automatic_selection_remains_a_valid_comparison(personal_profile):
    analysis = selection_analysis()
    analysis["manual_frames"] = [70, 90]
    result = comparison.build_comparison(analysis, options(), personal_profile)
    assert all(variant["proposals"] == [] for variant in result["variants"])
    assert result["analysis"]["manual_frames"] == [70, 90]

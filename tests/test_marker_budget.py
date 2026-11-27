"""Global marker totals follow analyzed time and count each image only once."""

from copy import deepcopy
import json
import math

import pytest

from vispa_mp.marker_budget import (
    BUDGET_DEFAULTS, MAX_MARKERS, band_for_compression, budget_settings, compression_for_band, compression_for_target,
    count_markers, marker_frames, target_for_compression, valid_budget_value,
)


def settings(**changes):
    return {**BUDGET_DEFAULTS, **changes}


def analysis(seconds=600, fps=24):
    return {"fps": fps, "timebase": {"fps": fps, "start_frame": 86400},
            "timeline_range": [86400, 86400 + int(seconds * fps)], "shots": []}


def test_default_auto_totals_scale_with_analyzed_duration_and_preserve_inputs():
    config, measured = settings(), analysis()
    original = deepcopy((config, measured))
    budget = budget_settings(config, measured)
    assert budget["enabled"] and budget["automatic"] and not budget["legacy"]
    assert (budget["min"], budget["target"], budget["max"]) == (120, 300, 450)
    assert budget["minutes"] == 10 and budget["seconds"] == 600
    assert budget["span"] == measured["timeline_range"] and budget["duration_source"] == "timeline"
    assert budget["rates"] == {"min": 12.0, "target": 30.0, "max": 45.0}
    assert not budget["corrected"] and budget["warnings"] == []
    assert (config, measured) == original
    second = budget_settings(config, analysis(1200))
    assert (second["min"], second["target"], second["max"]) == (240, 600, 900)


def test_analyzed_in_out_takes_precedence_over_whole_timeline_and_shots():
    measured = analysis(1200)
    measured["range"] = [90000, 90000 + 24 * 60]
    measured["shots"] = [{"start": 90000, "end": 90024}]
    budget = budget_settings(settings(), measured)
    assert budget["minutes"] == 1 and budget["duration_source"] == "range"
    assert budget["span"] == measured["range"]
    assert (budget["min"], budget["target"], budget["max"]) == (12, 30, 45)


def test_timeline_duration_includes_gaps_and_supports_direct_snapshot_bounds():
    measured = analysis(600)
    measured["shots"] = [{"start": 86400, "end": 86424}, {"start": 100000, "end": 100024}]
    assert budget_settings(settings(), measured)["minutes"] == 10
    del measured["timeline_range"]
    measured["start_frame"], measured["end_frame"] = 86400, 100800
    budget = budget_settings(settings(), measured)
    assert budget["minutes"] == 10 and budget["duration_source"] == "timeline"
    del measured["start_frame"]
    assert budget_settings(settings(), measured)["minutes"] == 10


def test_legacy_shot_extent_includes_internal_gaps_and_ignores_display_half_rate():
    measured = {"fps": 50, "timebase": {"fps": 50, "timecode_fps": 25},
                "shots": [{"start": 180000, "end": 180050}, {"start": 182950, "end": 183000}]}
    budget = budget_settings(settings(), measured)
    assert budget["minutes"] == 1
    assert budget["duration_source"] == "shots" and budget["span"] == [180000, 183000]
    assert budget["target"] == 30


@pytest.mark.parametrize("measured", [None, {}, {"fps": 24, "shots": []},
                                        {"fps": 0, "timeline_range": [0, 240]},
                                        {"fps": True, "timeline_range": [0, 240]},
                                        {"fps": float("nan"), "timeline_range": [0, 240]},
                                        {"fps": 24, "range": [10, 0], "timeline_range": [0, 14400]},
                                        {"fps": 24, "range": [False, 240]},
                                        {"fps": 24, "shots": [{"start": 0, "end": 240}, {}]}])
def test_missing_or_invalid_duration_never_invents_automatic_totals(measured):
    budget = budget_settings(settings(), measured)
    assert budget["minutes"] == 0
    assert budget["span"] is None and budget["duration_source"] == "unknown"
    assert (budget["min"], budget["target"], budget["max"]) == (0, 0, 0)


def test_zero_range_is_zero_and_does_not_fall_back_to_whole_timeline():
    measured = dict(analysis(600), range=[90000, 90000])
    budget = budget_settings(settings(), measured)
    assert budget["span"] == [90000, 90000] and budget["duration_source"] == "range"
    assert (budget["min"], budget["target"], budget["max"]) == (0, 0, 0)


def test_rounding_both_bounds_up_keeps_short_ranges_usable():
    budget = budget_settings(settings(), analysis(1))
    assert (budget["min"], budget["target"], budget["max"]) == (1, 1, 1)
    half = budget_settings(settings(global_markers_per_min_min=0, global_markers_per_min_max=100), analysis(1))
    assert half["target"] == 1  # 30/min * 1/60 min = 0.5 rounds upward.
    zero = budget_settings(settings(global_markers_per_min_min=0, global_markers_per_min_target=0,
                                    global_markers_per_min_max=0), analysis(1))
    assert (zero["min"], zero["target"], zero["max"]) == (0, 0, 0)


def test_manual_totals_are_independent_of_duration_and_auto_preserves_them():
    config = settings(global_markers_auto=False, global_markers_min=125, global_markers_target=180, global_markers_max=230)
    for measured in (None, analysis(600), analysis(1200)):
        budget = budget_settings(config, measured)
        assert (budget["min"], budget["target"], budget["max"]) == (125, 180, 230)
    config["global_markers_auto"] = True
    budget = budget_settings(config, analysis(600))
    assert budget["target"] == 300 and config["global_markers_target"] == 180


@pytest.mark.parametrize("automatic", [False, True])
def test_reversed_bounds_are_sorted_and_target_is_clamped_with_explanation(automatic):
    config = settings(global_markers_auto=automatic, global_markers_min=200, global_markers_target=400,
                      global_markers_max=100, global_markers_per_min_min=50,
                      global_markers_per_min_target=70, global_markers_per_min_max=10)
    budget = budget_settings(config, analysis(60))
    expected = (10, 50, 50) if automatic else (100, 200, 200)
    assert (budget["min"], budget["target"], budget["max"]) == expected
    assert budget["corrected"]
    assert any("reversed" in warning for warning in budget["warnings"])
    assert any("target" in warning for warning in budget["warnings"])


def test_feature_requires_explicit_activation_in_legacy_callers():
    assert budget_settings(None, analysis())["enabled"] is False
    assert budget_settings({"compression": 0.35}, analysis())["legacy"] is True
    assert budget_settings({"global_markers_auto": True}, analysis())["enabled"] is False
    assert budget_settings(settings(global_markers_enabled=False), analysis())["enabled"] is False
    assert budget_settings(settings(), analysis())["enabled"] is True


@pytest.mark.parametrize("key,value", [
    ("global_markers_enabled", 1), ("global_markers_auto", "yes"),
    ("global_markers_per_min_min", True), ("global_markers_per_min_target", "30"),
    ("global_markers_per_min_max", float("inf")), ("global_markers_per_min_min", float("nan")),
    ("global_markers_per_min_min", -1), ("global_markers_min", 1.5),
    ("global_markers_target", 1.0), ("global_markers_max", True),
    ("global_markers_min", -1), ("global_markers_max", MAX_MARKERS + 1),
    ("global_markers_per_min_max", 10 ** 1000),
])
def test_invalid_budget_values_are_rejected_strictly(key, value):
    assert not valid_budget_value(key, value)
    with pytest.raises(ValueError, match=key):
        budget_settings(settings(**{key: value}), analysis())


def test_large_automatic_totals_are_capped_with_a_warning():
    budget = budget_settings(settings(global_markers_per_min_max=MAX_MARKERS), analysis(1200))
    assert budget["max"] == MAX_MARKERS
    assert budget["corrected"] and any("capped" in warning for warning in budget["warnings"])


def test_unique_marker_images_include_all_roles_and_reserved_frames_once():
    markers = [{"frame": 10, "color": "Green"}, {"frame": 10, "color": "Blue"},
               {"frame": 20, "color": "Cyan"}, {"frame": 30, "color": "Yellow"},
               {"frame": 40, "color": "Blue"}]
    assert marker_frames(markers, [10, 30, 30]) == {10, 20, 30, 40}
    assert count_markers(markers, [10, 30, 30]) == 4
    assert marker_frames(markers, [10, 30, 40], span=[10, 40]) == {10, 20, 30}
    assert count_markers(None, None) == 0


@pytest.mark.parametrize("markers,manual,span", [([{"frame": True, "color": "Blue"}], [], None),
                                                    ([], [1.0], None), ([False], [], None),
                                                    ([], [], [10, 0]), ([], [], [False, 10])])
def test_invalid_counting_frames_or_span_are_not_guessed(markers, manual, span):
    with pytest.raises(ValueError):
        count_markers(markers, manual, span)


def test_compression_defaults_midpoint_and_reverse_mapping():
    assert compression_for_target(10, 30, 50) == 0.5
    assert compression_for_target(100, 300, 500) == 0.5
    assert compression_for_target(10, 50, 50) == 0
    assert compression_for_target(10, 10, 50) == 1
    assert target_for_compression(10, 50, 0.5) == 30
    assert target_for_compression(100, 500, 0.5, integer=True) == 300
    assert target_for_compression(0, 1, 0.5, integer=True) == 1
    for target in (10, 20.5, 30, 40.5, 50):
        assert target_for_compression(10, 50, compression_for_target(10, target, 50)) == pytest.approx(target)


def test_density_band_reference_is_fifty_percent_and_custom_shapes_survive_slider_moves():
    assert compression_for_band((12, 30, 45)) == 0.5
    assert band_for_compression((12, 30, 45), 0) == (24, 60, 90)
    assert band_for_compression((12, 30, 45), 1) == (6, 15, 22.5)
    custom = (10, 30, 60)
    changed = band_for_compression(custom, 0.5)
    assert sum(changed) == pytest.approx(87)
    assert changed[2] / changed[0] == pytest.approx(6)
    assert compression_for_band(changed) == pytest.approx(0.5)
    assert band_for_compression((0, 0, 0), 0.5) == (12, 30, 45)


def test_compression_clamps_bounds_values_and_equal_limits_preserve_previous():
    assert compression_for_target(50, 90, 10) == 0
    assert compression_for_target(10, 0, 50) == 1
    assert compression_for_target(5, 5, 5, previous=0.42) == 0.42
    assert target_for_compression(5, 5, 0.99, integer=True) == 5
    assert target_for_compression(10, 50, -1) == 50
    assert target_for_compression(10, 50, 2) == 10
    with pytest.raises(ValueError):
        target_for_compression(0.1, 0.9, 0.5, integer=True)
    for value in (True, float("nan"), float("inf"), "0.5"):
        with pytest.raises(ValueError):
            target_for_compression(10, 50, value)


def test_budget_settings_round_trip_through_user_and_exported_presets(tmp_path):
    from vispa_mp.preset import export_settings, import_settings, load, load_user, save_user

    config = {**load(), **settings(global_markers_auto=False, global_markers_min=120,
                                  global_markers_target=240, global_markers_max=500)}
    path = tmp_path / "user.json"
    save_user(config, {}, path)
    restored, _view = load_user(path)
    assert restored == config
    exported = tmp_path / "budget-settings.json"
    export_settings(config, exported)
    assert import_settings(exported) == config
    assert math.isclose(restored["compression"], 0.5)
    assert budget_settings(restored, analysis())["target"] == 240


def test_invalid_persisted_budget_values_are_skipped_safely(tmp_path):
    from vispa_mp.preset import import_settings, load_user

    path = tmp_path / "bad-budget.json"
    path.write_text(json.dumps({"global_markers_enabled": "true", "global_markers_min": 2.5,
                                "global_markers_per_min_max": float("nan"), "mouth_min": 0.4}), encoding="utf-8")
    restored, _view = load_user(path)
    assert restored["global_markers_min"] == 0
    assert restored["global_markers_per_min_max"] == 45
    assert import_settings(path) == {"mouth_min": 0.4}


def test_budget_settings_and_legacy_absence_round_trip_in_portable_projects(tmp_path):
    from tests.test_project import _review
    from vispa_mp.project import load_project, save_project

    review = _review(tmp_path)
    review["settings"].update(settings(global_markers_auto=False, global_markers_min=1,
                                      global_markers_target=2, global_markers_max=3))
    path = tmp_path / "budget.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "cache")
    assert restored["settings"] == review["settings"]
    assert budget_settings(restored["settings"], restored["analysis"])["target"] == 2
    legacy = {key: value for key, value in review["settings"].items() if key not in BUDGET_DEFAULTS}
    review["settings"] = legacy
    save_project(path, **review)
    restored = load_project(path, tmp_path / "cache")
    assert restored["settings"] == legacy
    assert not budget_settings(restored["settings"], restored["analysis"])["enabled"]

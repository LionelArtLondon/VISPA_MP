"""Learn preferences locally, with honest media-group validation and safe JSON."""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from vispa_mp.learning_model import (
    FEATURE_NAMES, apply_profile, cross_validate, feature_vector,
    load_cross_validation_report, load_profile, save_cross_validation_report, save_profile,
    train_profile, validate_cross_validation_report, validate_profile,
)


def _shot(offset=0):
    # The marked image favours expression over the very sharp alternative.
    return {"start": offset, "end": offset + 50, "motion": 8, "cut_grey": 12,
            "cut_colour": 0.1, "frames": [
                {"frame": offset + 10, "sharpness": 30, "open_mouth": 0.1,
                 "closed_mouth": 0.1, "expression": 1, "face": 0.8, "neighbor": 1},
                {"frame": offset + 30, "sharpness": 2000, "open_mouth": 0.1,
                 "closed_mouth": 0.1, "expression": 0, "face": 0.8, "neighbor": 1},
            ]}


def _reference(group="chapter-a", identifier=None, role="core", offset=0, reverse=False):
    shot = _shot(offset)
    roles = ["core", "page"] if role == "page" else [role]
    return {"kind": "vispa-mp-reference", "version": 1, "id": identifier or group,
            "name": group, "group_id": group, "timebase": {"fps": 24},
            "feature_names": list(FEATURE_NAMES), "samples": [
                {"frame": frame["frame"], "shot": shot["start"], "features": feature_vector(frame, shot),
                 "roles": roles if index == int(reverse) else []}
                for index, frame in enumerate(shot["frames"])], "summary": {}}


def _profile():
    return train_profile([_reference()])


def _rank(profile, reference, role="core"):
    model = profile["roles"][role]
    return np.asarray([sample["features"] for sample in reference["samples"]]) @ np.asarray(model["weights"])


def test_visual_features_are_finite_relative_and_do_not_mutate_the_analysis():
    original = _shot()
    before = deepcopy(original)
    later = _shot(90000)
    first = feature_vector(original["frames"][0], original, 24, [{"start": 0, "end": 20}])
    translated = feature_vector(later["frames"][0], later, 24, [{"start": 90000, "end": 90020}])
    assert first == translated
    assert len(first) == len(FEATURE_NAMES)
    assert all(isinstance(value, float) and 0 <= value <= 1 for value in first)
    assert original == before
    assert not any("frame" in name or "chapter" in name for name in FEATURE_NAMES)


def test_missing_or_nonfinite_measurements_never_create_nan_predictions():
    shot = {"start": 0, "end": 1, "frames": []}
    values = feature_vector({"frame": 0, "sharpness": float("nan"), "open_mouth": float("inf"),
                             "expression": None}, shot, fps=0)
    assert np.isfinite(values).all()
    assert min(values) >= 0 and max(values) <= 1


def test_a_real_pairwise_fit_can_reverse_a_standard_quality_preference():
    reference = _reference()
    original = deepcopy(reference)
    profile = train_profile([reference], name="My selection")
    assert profile["roles"]["core"]["trained"]
    assert _rank(profile, reference)[0] > _rank(profile, reference)[1]
    assert profile["report"]["roles"]["core"]["train_accuracy"] == 1
    assert profile["name"] == "My selection"
    assert reference == original


def test_one_media_group_is_explicitly_unvalidated_and_never_has_holdout_scores():
    profile = train_profile([_reference(), _reference(identifier="another-edit")])
    report = profile["report"]
    assert report["train_groups"] == ["chapter-a"]
    assert report["validation_groups"] == []
    assert report["validation_unavailable"] is True
    assert any("no independent chapter validation" in warning for warning in report["warnings"])
    assert all(value["baseline_accuracy"] is None and value["personal_accuracy"] is None
               for value in report["roles"].values())


def test_a_whole_chapter_including_all_its_edits_is_held_out():
    refs = [_reference("train-a"), _reference("test-b", "test-b-v1"),
            _reference("test-b", "test-b-v2", offset=100)]
    profile = train_profile(refs, holdout_group="test-b")
    report = profile["report"]
    assert report["train_groups"] == ["train-a"]
    assert report["validation_groups"] == ["test-b"]
    assert report["validation_unavailable"] is False
    assert report["roles"]["core"]["validation_pairs"] == 2
    assert report["roles"]["core"]["personal_accuracy"] == 1
    assert report["roles"]["core"]["baseline_accuracy"] == 0
    # Changing every label in the held-out chapter changes the report, never
    # the trained weights or their stable ID.
    reversed_refs = [refs[0], _reference("test-b", "test-b-v1", reverse=True),
                     _reference("test-b", "test-b-v2", offset=100, reverse=True)]
    reversed_profile = train_profile(reversed_refs, holdout_group="test-b")
    assert profile["roles"] == reversed_profile["roles"]
    assert profile["id"] == reversed_profile["id"]
    assert reversed_profile["report"]["roles"]["core"]["personal_accuracy"] == 0


def test_default_holdout_and_training_are_deterministic_regardless_of_reference_order():
    references = [_reference("chapter-a"), _reference("chapter-z"), _reference("chapter-b")]
    first = train_profile(references)
    second = train_profile(list(reversed(references)))
    assert first == second
    assert first["report"]["validation_groups"] == ["chapter-z"]
    assert set(first["report"]["train_groups"]).isdisjoint(first["report"]["validation_groups"])


@pytest.mark.parametrize("media", [["I:/films/episode.mov"], [{"path": "I:/films/episode.mov", "size": 100}]])
def test_the_same_video_cannot_leak_between_differently_named_groups(media):
    first, second = _reference("group-a"), _reference("group-b")
    first["source"] = {"media": media}
    second["source"] = {"media": [{"path": "i:/FILMS/./episode.mov", "size": 100}]}
    with pytest.raises(ValueError, match="same chapter group"):
        train_profile([first, second])


def test_edits_sharing_even_one_clip_must_be_grouped_together():
    first, second = _reference("group-a"), _reference("group-b")
    first["source"] = {"media": ["I:/films/shared.mov", "I:/films/other.mov"]}
    second["source"] = {"media": ["I:/films/shared.mov"]}
    with pytest.raises(ValueError, match="same footage"):
        train_profile([first, second])
    second["group_id"] = first["group_id"]
    profile = train_profile([first, second])
    assert profile["report"]["validation_unavailable"]


def test_a_reference_selected_twice_does_not_double_the_training_corpus():
    reference = _reference()
    profile = train_profile([reference, deepcopy(reference)])
    assert profile == train_profile([reference])
    assert profile["report"]["reference_count"] == 1


def test_unlabelled_images_are_alternatives_not_fake_absolute_negative_labels():
    reference = _reference()
    profile = train_profile([reference])
    assert profile["report"]["alternative_weight"] == 0.25
    assert profile["report"]["metric"] == "pairwise_preference_accuracy"
    assert profile["report"]["baseline"] == "standard_visual_weights_v1"
    assert profile["roles"]["core"]["pairs"] == 1
    assert reference["samples"][1]["roles"] == []
    assert "negative" not in reference["samples"][1]


def test_an_image_selected_as_an_extra_is_not_a_core_quality_loser():
    reference = _reference()
    reference["samples"][1]["roles"] = ["extra"]
    profile = train_profile([reference])
    # An approved Extra is still not a rejected image for the quality ranker.
    assert profile["roles"]["core"]["pairs"] == 0
    assert profile["roles"]["extra"]["pairs"] == 0
    # Explicitly different roles can now teach the separate assignment model.
    assert profile["role_assignment"]["trained"] is True


def test_nearby_or_visually_identical_holds_do_not_manufacture_preferences():
    reference = _reference()
    reference["samples"][1]["frame"] = reference["samples"][0]["frame"] + 1
    with pytest.raises(ValueError, match="no usable preference comparisons"):
        train_profile([reference])
    reference = _reference()
    reference["samples"][0]["signature"] = [10.0] * 64
    reference["samples"][1]["signature"] = [10.1] * 64
    with pytest.raises(ValueError, match="no usable preference comparisons"):
        train_profile([reference])


@pytest.mark.parametrize("role", ["core", "extra", "page"])
def test_only_roles_with_learned_pairs_add_scores_to_a_copied_analysis(role):
    profile = train_profile([_reference(role=role)])
    shot = _shot()
    shot["frames"][0].update(personal_core=0.1, personal_extra=0.1, personal_page=0.1)
    analysis = {"fps": 24, "shots": [shot], "utterances": []}
    original = deepcopy(analysis)
    applied = apply_profile(analysis, profile)
    assert analysis == original
    fields = applied["shots"][0]["frames"][0]
    for candidate_role in ("core", "extra", "page"):
        if profile["roles"][candidate_role]["trained"]:
            assert 0 <= fields[f"personal_{candidate_role}"] <= 1
        else:
            assert f"personal_{candidate_role}" not in fields
    assert applied["shots"][0]["frames"][0][f"personal_{role}"] > applied["shots"][0]["frames"][1][f"personal_{role}"]
    assert [item["frame"] for item in applied["shots"][0]["frames"]] == [10, 30]


def test_validation_without_usable_role_comparisons_does_not_show_a_fake_accuracy():
    training, held = _reference("a"), _reference("z")
    held["samples"][1]["roles"] = ["extra"]
    profile = train_profile([training, held])
    report = profile["report"]["roles"]["core"]
    assert report["trained"] and report["validation_pairs"] == 0
    assert report["personal_accuracy"] is None


def test_cancellation_and_progress_have_no_partial_profile_output():
    calls = []
    with pytest.raises(InterruptedError, match="stopped"):
        train_profile([_reference()], progress=calls.append, cancel=lambda: True)
    assert calls == []
    calls = []
    profile = train_profile([_reference()], progress=calls.append)
    assert profile["name"]
    assert any("Training Core" in value for value in calls)
    assert "before activation" in calls[-1]


@pytest.mark.parametrize("changes", [
    lambda ref: ref.update(version=True),
    lambda ref: ref.update(version=1.0),
    lambda ref: ref.update(feature_names=["wrong"]),
    lambda ref: ref["samples"][0].update(frame=True),
    lambda ref: ref["samples"][0].update(roles=["page"]),
    lambda ref: ref["samples"][0].update(roles=["core", "extra"]),
    lambda ref: ref["samples"][0].update(features=[0] * 2),
    lambda ref: ref["samples"][0]["features"].__setitem__(0, float("nan")),
])
def test_unreadable_training_data_is_rejected_before_learning(changes):
    reference = _reference()
    changes(reference)
    with pytest.raises(ValueError):
        train_profile([reference])


@pytest.mark.parametrize("holdout", ["missing", "chapter-a"])
def test_a_holdout_must_leave_a_different_group_for_training(holdout):
    with pytest.raises(ValueError, match="validation chapter"):
        train_profile([_reference()], holdout_group=holdout)


@pytest.mark.parametrize("changes", [
    lambda profile: profile.update(version=True),
    lambda profile: profile.update(kind="pickle-model"),
    lambda profile: profile.update(feature_names=["unknown"]),
    lambda profile: profile["roles"]["core"].update(weights=[0]),
    lambda profile: profile["roles"]["core"]["weights"].__setitem__(0, float("inf")),
    lambda profile: profile["roles"]["core"].update(bias=float("nan")),
    lambda profile: profile["roles"]["core"].update(trained=False),
    lambda profile: profile["report"].update(validation_groups=["chapter-a"], validation_unavailable=False),
    lambda profile: profile["report"].update(sample_count=True),
    lambda profile: profile["report"]["roles"]["core"].update(personal_accuracy=1),
])
def test_invalid_profile_weights_or_misleading_reports_are_rejected(changes):
    profile = _profile()
    changes(profile)
    with pytest.raises(ValueError):
        validate_profile(profile)


def test_json_profile_round_trip_is_portable_and_validation_returns_an_independent_copy(tmp_path):
    profile = _profile()
    path = tmp_path / "profile.json"
    assert save_profile(profile, path) == path
    assert load_profile(path) == profile
    assert json.loads(path.read_text(encoding="utf-8"))["kind"] == "vispa-mp-profile"
    copy = validate_profile(profile)
    copy["roles"]["core"]["weights"][0] = 0
    assert copy != profile


def test_a_failed_atomic_save_keeps_the_previous_profile_and_leaves_no_partial_file(tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    save_profile(_profile(), path)
    original = path.read_bytes()
    monkeypatch.setattr("vispa_mp.learning_model.os.replace", lambda *args: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(OSError, match="locked"):
        save_profile(_profile(), path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("data", [b"not json", b"\x80\x04pickle data", b'{"bad":NaN}', b"{}"])
def test_loaded_profiles_are_validated_json_and_never_executable_serialization(tmp_path, data):
    path = tmp_path / "untrusted.profile"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        load_profile(path)


def test_a_large_reference_set_has_bounded_preference_pair_counts():
    references = []
    for group in range(4):
        reference = _reference(f"chapter-{group}")
        samples = []
        for index in range(100):
            added = _reference(f"chapter-{group}", offset=index * 100)
            samples.extend(added["samples"])
        reference["samples"] = samples
        references.append(reference)
    profile = train_profile(references)
    assert 1 <= profile["roles"]["core"]["pairs"] <= 40_000
    assert len(profile["report"]["train_groups"]) == 3
    assert len(profile["report"]["validation_groups"]) == 1
    assert profile["report"]["roles"]["core"]["personal_accuracy"] == 1


@pytest.mark.parametrize("offset,fps", [(0, 24), (90000, 25), (180000, 50), (300000, 29.97)])
def test_indexed_application_exactly_matches_public_features_with_unsorted_overlapping_lines(offset, fps):
    profile = _profile()
    # Shots and candidates are deliberately unordered. Overlapping lines are
    # resolved by the user's input order, independently of their start times.
    shots = [_shot(offset + 100), _shot(offset), _shot(offset + 50)]
    for shot in shots:
        shot["frames"].reverse()
    utterances = [
        {"start": offset + 20, "end": offset + 140},
        {"start": offset, "end": offset + 90},
        {"start": offset + 130, "end": offset + 180},
        {"start": offset + 10, "end": offset + 10},
    ]
    analysis = {"fps": fps, "shots": shots, "utterances": utterances}
    before = deepcopy(analysis)
    applied = apply_profile(analysis, profile)
    model = profile["roles"]["core"]
    for original_shot, result_shot in zip(shots, applied["shots"]):
        for original_frame, result_frame in zip(original_shot["frames"], result_shot["frames"]):
            features = np.asarray(feature_vector(original_frame, original_shot, fps, utterances))
            margin = features @ np.asarray(model["weights"]) + model["bias"]
            expected = float(1 / (1 + np.exp(-np.clip(margin, -40, 40))))
            assert result_frame["personal_core"] == pytest.approx(expected, abs=1e-15)
            assert result_frame["frame"] == original_frame["frame"]
    assert analysis == before


def test_overlapping_line_features_keep_first_input_order_and_exclusive_end_boundaries():
    profile = _profile()
    model = profile["roles"]["core"]
    model["weights"] = [0.0] * len(FEATURE_NAMES)
    model["weights"][FEATURE_NAMES.index("speech_phase")] = 1.0
    model["weights"][FEATURE_NAMES.index("speech")] = 2.0
    model["bias"] = 0.0
    frames = [{"frame": number, "sharpness": 100} for number in (5, 15, 20, 99, 100, 120)]
    shot = {"start": 0, "end": 125, "frames": frames}
    lines = [{"start": 10, "end": 100}, {"start": 0, "end": 20}, {"start": 100, "end": 120}]
    result = apply_profile({"fps": 25, "shots": [shot], "utterances": lines}, profile)
    phases = (5 / 20, 5 / 90, 10 / 90, 89 / 90, 0, 0.5)
    speaking = (1, 1, 1, 1, 1, 0)
    for frame, phase, speech in zip(result["shots"][0]["frames"], phases, speaking):
        assert frame["personal_core"] == pytest.approx(1 / (1 + np.exp(-(phase + 2 * speech))))


def test_public_features_keep_single_frame_quality_when_the_shot_has_no_candidates_yet():
    values = feature_vector({"frame": 1, "sharpness": 500}, {"start": 0, "end": 2, "frames": []})
    assert values[FEATURE_NAMES.index("relative_sharpness")] == 1


def _cross_report():
    return cross_validate([_reference("chapter-a"), _reference("chapter-b"), _reference("chapter-c")])


def test_cross_validation_holds_out_every_whole_chapter_and_all_its_versions_once():
    references = [_reference("a", "a-v1"), _reference("a", "a-v2", offset=100),
                  _reference("b"), _reference("c")]
    original = deepcopy(references)
    report = cross_validate(references)
    assert report["kind"] == "vispa-mp-cross-validation"
    assert report["method"] == "leave_one_group_out"
    assert report["metric"] == "pairwise_preference_accuracy"
    assert report["baseline"] == "standard_visual_weights_v1"
    assert report["aggregation"] == "macro_by_group"
    assert report["groups"] == ["a", "b", "c"]
    assert report["reference_count"] == 4
    assert report["sample_count"] == 8
    assert report["fold_count"] == 3
    assert report["group_names"]["a"] == ["a"]
    for fold in report["folds"]:
        assert fold["heldout_group"] not in fold["train_groups"]
        assert set(fold["train_groups"]) == set(report["groups"]) - {fold["heldout_group"]}
        assert fold["roles"]["core"]["personal_accuracy"] == 1
        assert fold["roles"]["core"]["baseline_accuracy"] == 0
    assert report["folds"][0]["roles"]["core"]["validation_pairs"] == 2
    assert report["roles"]["core"]["groups_evaluated"] == 3
    assert report["roles"]["core"]["validation_pairs"] == 4
    assert report["roles"]["core"]["personal_accuracy"] == 1
    assert references == original
    assert all("weights" not in entry for fold in report["folds"] for entry in fold["roles"].values())
    assert any("not measure final page quality" in warning for warning in report["warnings"])


def test_the_held_out_chapters_labels_never_change_its_fold_weights(monkeypatch):
    import vispa_mp.learning_model as model
    fitted = []
    real_fit = model._fit

    def record_fit(*args, **kwargs):
        weights = real_fit(*args, **kwargs)
        fitted.append(weights.copy())
        return weights

    monkeypatch.setattr(model, "_fit", record_fit)
    first = cross_validate([_reference("a"), _reference("b"), _reference("c")])
    first_weights = fitted[0]
    fitted.clear()
    second = cross_validate([_reference("a", reverse=True), _reference("b"), _reference("c")])
    assert np.array_equal(fitted[0], first_weights)
    assert first["folds"][0]["heldout_group"] == second["folds"][0]["heldout_group"] == "a"
    assert first["folds"][0]["roles"]["core"]["personal_accuracy"] == 1
    assert second["folds"][0]["roles"]["core"]["personal_accuracy"] == 0


def test_cross_validation_does_not_save_or_activate_a_profile(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Cross-validation is an evaluation, not a profile save or activation")

    monkeypatch.setattr("vispa_mp.learning_model.train_profile", forbidden)
    monkeypatch.setattr("vispa_mp.learning_model.save_profile", forbidden)
    report = _cross_report()
    assert report["roles"]["core"]["groups_evaluated"] == 3


def test_cross_validation_is_deterministic_when_reference_order_changes():
    references = [_reference("z"), _reference("a"), _reference("b")]
    assert cross_validate(references) == cross_validate(list(reversed(references)))


def test_disabled_references_do_not_train_validate_or_trigger_spurious_media_leakage():
    enabled = [_reference("a"), _reference("b")]
    enabled[0]["source"] = {"media": ["I:/films/shared.mov"]}
    disabled = _reference("another-group")
    disabled.update(enabled=False, kind="old-unreadable-reference", samples="old cache")
    disabled["source"] = {"media": ["I:/films/shared.mov"]}
    original = deepcopy(disabled)
    assert cross_validate(enabled + [disabled]) == cross_validate(enabled)
    assert train_profile(enabled + [disabled]) == train_profile(enabled)
    assert disabled == original


def test_disabled_versions_are_ignored_before_duplicate_ids_are_resolved():
    enabled = [_reference("a"), _reference("b")]
    disabled = deepcopy(enabled[0])
    disabled.update(enabled=False, samples=[])
    assert cross_validate([disabled] + enabled) == cross_validate(enabled)


@pytest.mark.parametrize("operation", [cross_validate, train_profile])
def test_an_empty_enabled_corpus_is_reported_without_a_fake_model_or_score(operation):
    disabled = _reference()
    disabled["enabled"] = False
    with pytest.raises(ValueError, match="Enable at least one"):
        operation([disabled])


@pytest.mark.parametrize("operation", [cross_validate, train_profile])
def test_an_enabled_flag_must_be_boolean(operation):
    invalid = _reference()
    invalid["enabled"] = "false"
    with pytest.raises(ValueError, match="enabled state"):
        operation([invalid])


def test_cross_validation_requires_two_enabled_independent_groups():
    with pytest.raises(ValueError, match="at least two"):
        cross_validate([_reference("same", "v1"), _reference("same", "v2")])
    disabled = _reference("other")
    disabled["enabled"] = False
    with pytest.raises(ValueError, match="at least two"):
        cross_validate([_reference(), disabled])


def test_cross_validation_reuses_the_source_video_group_leakage_guard():
    first, second = _reference("a"), _reference("b")
    first["source"] = {"media": [{"path": "I:/films/chapter.mov", "size": 100}]}
    second["source"] = {"media": ["i:/FILMS/./chapter.mov"]}
    with pytest.raises(ValueError, match="same chapter group"):
        cross_validate([first, second])


def test_cross_validation_excludes_uncomparable_folds_instead_of_scoring_them_zero():
    report = cross_validate([_reference("a"), _reference("b"), _reference("c", role="extra")])
    core = report["roles"]["core"]
    assert core["personal_accuracy"] == 1
    assert core["groups_evaluated"] == 2
    assert core["groups_skipped"] == 1
    assert core["validation_pairs"] == 2
    extra = report["roles"]["extra"]
    assert extra["personal_accuracy"] is extra["baseline_accuracy"] is None
    assert extra["groups_evaluated"] == 0
    extra_folds = [fold["roles"]["extra"] for fold in report["folds"]]
    assert [entry["reason"] for entry in extra_folds] == ["no_validation_pairs", "no_validation_pairs", "no_training_pairs"]
    assert all(entry["personal_accuracy"] is None and entry["trained"] is False for entry in extra_folds)


def test_a_corpus_without_comparable_choices_gets_an_explicit_unavailable_report():
    references = [_reference("a"), _reference("b")]
    for reference in references:
        reference["samples"][1]["roles"] = ["extra"]
    report = cross_validate(references)
    assert report["validation_unavailable"] is True
    assert all(entry["personal_accuracy"] is None and entry["groups_evaluated"] == 0
               for entry in report["roles"].values())


def test_cross_validation_macro_average_weights_chapters_equally_not_their_frame_counts():
    report = _cross_report()
    baseline = (0.0, 1.0, 0.0)
    personal = (1.0, 1.0, 0.0)
    counts = (6, 2, 20)
    for fold, base, learned, count in zip(report["folds"], baseline, personal, counts):
        fold["roles"]["core"].update(baseline_accuracy=base, personal_accuracy=learned, validation_pairs=count)
    report["roles"]["core"].update(
        baseline_accuracy=1 / 3, personal_accuracy=2 / 3, delta=1 / 3, validation_pairs=28,
        groups_improved=1, groups_regressed=0, groups_unchanged=2,
    )
    assert validate_cross_validation_report(report)["roles"]["core"]["personal_accuracy"] == 2 / 3
    report["roles"]["core"]["personal_accuracy"] = 8 / 28
    with pytest.raises(ValueError, match="aggregates"):
        validate_cross_validation_report(report)


def test_cross_validation_cancellation_is_responsive_between_folds_and_has_no_partial_output():
    progress = []
    stopped = False

    def update(message):
        nonlocal stopped
        progress.append(message)
        if "Cross-validation 2/" in message:
            stopped = True

    with pytest.raises(InterruptedError, match="stopped"):
        cross_validate([_reference("a"), _reference("b"), _reference("c")],
                       progress=update, cancel=lambda: stopped)
    assert any("Cross-validation 1/3" in item for item in progress)
    assert not any("finished" in item for item in progress)
    with pytest.raises(InterruptedError, match="stopped"):
        cross_validate([_reference("a"), _reference("b")], cancel=lambda: True)


def test_cross_validation_bounds_the_number_of_folds_before_fitting(monkeypatch):
    monkeypatch.setattr("vispa_mp.learning_model._fit", lambda *args: pytest.fail("Too many folds must fail before fitting"))
    with pytest.raises(ValueError, match="at most 64"):
        cross_validate([_reference(f"chapter-{index:03d}") for index in range(65)])


@pytest.mark.parametrize("changes", [
    lambda report: report.update(kind="page-quality-score"),
    lambda report: report.update(version=True),
    lambda report: report.update(metric="complete_marker_accuracy"),
    lambda report: report.update(aggregation="micro_by_frame"),
    lambda report: report.update(fold_count=99),
    lambda report: report["folds"][0].update(train_groups=list(report["groups"])),
    lambda report: report["folds"].__setitem__(1, deepcopy(report["folds"][0])),
    lambda report: report["folds"][0]["roles"]["core"].update(personal_accuracy=float("nan")),
    lambda report: report["folds"][0]["roles"]["core"].update(validation_pairs=True),
    lambda report: report["folds"][0]["roles"]["extra"].update(personal_accuracy=0),
    lambda report: report["roles"]["core"].update(groups_evaluated=0),
    lambda report: report.update(validation_unavailable=True),
    lambda report: report.update(warnings=[]),
])
def test_cross_validation_report_rejects_leakage_fake_scores_or_inconsistent_aggregates(changes):
    report = _cross_report()
    changes(report)
    with pytest.raises(ValueError):
        validate_cross_validation_report(report)


def test_cross_validation_report_is_portable_independent_json(tmp_path):
    report = _cross_report()
    path = tmp_path / "validation" / "last.json"
    assert save_cross_validation_report(report, path) == path
    restored = load_cross_validation_report(path)
    assert restored == report
    restored["folds"][0]["roles"]["core"]["personal_accuracy"] = 0
    assert restored != report


def test_failed_cross_validation_save_keeps_the_previous_report_and_cleans_tempfiles(tmp_path, monkeypatch):
    report = _cross_report()
    path = tmp_path / "last.json"
    save_cross_validation_report(report, path)
    before = path.read_bytes()
    monkeypatch.setattr("vispa_mp.learning_model.os.replace", lambda *args: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(OSError, match="locked"):
        save_cross_validation_report(report, path)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("data", [b"not json", b"\x80\x04pickle data", b'{"score":NaN}', b"{}"])
def test_cross_validation_load_accepts_only_validated_json_reports(tmp_path, data):
    path = tmp_path / "last.json"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        load_cross_validation_report(path)

"""Approved Core/Extra roles teach a separate head, never fake quality losers."""

from copy import deepcopy

import numpy as np
import pytest

from vispa_mp.learning_model import (
    FEATURE_NAMES, apply_profile, load_profile, save_profile, train_profile, validate_profile,
)
from vispa_mp.role_learning import role_scores, train_role_assignment


def reference(group="chapter-a", identifier=None, reverse=False, copies=1):
    samples = []
    for index in range(copies):
        for label in (0, 1):
            features = [0.5] * len(FEATURE_NAMES)
            features[FEATURE_NAMES.index("expression")] = float(label)
            samples.append({"frame": index * 100 + label * 30 + 10, "shot": index * 100,
                            "features": features, "roles": ["extra"] if label != reverse else ["core"]})
    return {"kind": "vispa-mp-reference", "version": 1, "id": identifier or group,
            "name": group, "group_id": group, "feature_names": list(FEATURE_NAMES), "samples": samples}


def profile():
    return train_profile([reference()])


def test_explicit_roles_train_even_when_every_image_is_already_selected():
    ref = reference()
    original = deepcopy(ref)
    trained = train_profile([ref])
    assert not any(model["trained"] for model in trained["roles"].values())
    model = trained["role_assignment"]
    scores = role_scores([sample["features"] for sample in ref["samples"]], model)
    assert scores[0] < 0.35 and scores[1] > 0.65
    assert model["report"]["train_balanced_accuracy"] == 1
    assert ref == original
    reversed_model = train_profile([reference(reverse=True)])["role_assignment"]
    reversed_scores = role_scores([sample["features"] for sample in ref["samples"]], reversed_model)
    assert reversed_scores[0] > 0.65 and reversed_scores[1] < 0.35


def test_page_start_is_an_explicit_core_example_not_a_third_role_label():
    ref = reference()
    ref["samples"][0]["roles"] = ["core", "page"]
    model = train_profile([ref])["role_assignment"]
    assert model["report"]["train_counts"] == {"core": 1, "extra": 1}
    assert model["report"]["train_balanced_accuracy"] == 1


def test_unlabelled_images_never_change_binary_weights_or_counts():
    ref = reference()
    baseline = train_profile([ref])["role_assignment"]
    for number in range(100):
        ref["samples"].append({"frame": number + 1000, "shot": 0,
                               "features": [number / 100] * len(FEATURE_NAMES), "roles": []})
    model = train_profile([ref])["role_assignment"]
    assert model == baseline


def test_duplicate_edits_in_one_group_cannot_dominate_other_groups():
    first = reference("a")
    second = reference("b", reverse=True)
    held = reference("z")
    before = train_profile([first, second, held])["role_assignment"]
    repeated = reference("b", identifier="b-edit", reverse=True, copies=100)
    after = train_profile([first, second, repeated, held])["role_assignment"]
    assert np.allclose(before["weights"], after["weights"], atol=1e-12)
    assert before["bias"] == pytest.approx(after["bias"], abs=1e-12)
    assert before["report"]["train_groups"] == after["report"]["train_groups"] == ["a", "b"]


def test_an_abundant_class_does_not_drown_out_the_other_role():
    ref = reference()
    before = train_profile([ref])["role_assignment"]
    for index in range(100):
        added = deepcopy(ref["samples"][1])
        added["frame"] = 1000 + index
        ref["samples"].append(added)
    after = train_profile([ref])["role_assignment"]
    assert np.allclose(before["weights"], after["weights"], atol=1e-12)
    assert before["bias"] == pytest.approx(after["bias"], abs=1e-12)


def test_holdout_labels_affect_evaluation_but_not_weights_or_profile_id():
    first = train_profile([reference("a"), reference("z")], holdout_group="z")
    reversed_held = train_profile([reference("a"), reference("z", reverse=True)], holdout_group="z")
    head, other = first["role_assignment"], reversed_held["role_assignment"]
    assert head["weights"] == other["weights"] and head["bias"] == other["bias"]
    assert first["id"] == reversed_held["id"]
    assert head["report"]["validation_balanced_accuracy"] == 1
    assert other["report"]["validation_balanced_accuracy"] == 0
    assert head["report"]["validation_groups"] == ["z"]


def test_one_group_has_no_invented_independent_validation_score():
    head = profile()["role_assignment"]
    report = head["report"]
    assert report["validation_unavailable"] is True
    assert report["validation_balanced_accuracy"] is None
    assert report["unavailable_reason"] == "no_independent_chapter"
    assert report["validation_counts"] == {"core": 0, "extra": 0}


def test_validation_requires_both_explicit_roles_in_the_held_out_chapter():
    held = reference("z")
    held["samples"][1]["roles"] = []
    report = train_profile([reference("a"), held])["role_assignment"]["report"]
    assert report["validation_unavailable"]
    assert report["validation_balanced_accuracy"] is None
    assert report["unavailable_reason"] == "both_roles_required"


def test_training_one_role_alone_retains_the_legacy_quality_model():
    from tests.test_learning_model import _reference

    trained = train_profile([_reference()])
    assert "role_assignment" not in trained
    assert trained["roles"]["core"]["trained"]


def test_binary_only_application_preserves_frames_and_clears_stale_rank_scores():
    trained = profile()
    source = {"fps": 24, "shots": [{"start": 0, "end": 100, "frames": [
        {"frame": 10, "sharpness": 100, "expression": 0,
         "personal_core": 0.9, "personal_extra": 0.9, "personal_extra_role": 1},
        {"frame": 70, "sharpness": 100, "expression": 1},
    ]}]}
    before = deepcopy(source)
    result = apply_profile(source, trained)
    frames = result["shots"][0]["frames"]
    assert source == before
    assert [frame["frame"] for frame in frames] == [10, 70]
    assert frames[0]["personal_extra_role"] < 0.35
    assert frames[1]["personal_extra_role"] > 0.65
    assert all("personal_core" not in frame and "personal_extra" not in frame for frame in frames)


def test_old_profiles_round_trip_and_remove_a_previous_binary_preference(tmp_path):
    from tests.test_learning_model import _profile

    trained = _profile()
    assert "role_assignment" not in trained
    path = tmp_path / "legacy.json"
    save_profile(trained, path)
    assert load_profile(path) == trained
    analysis = {"fps": 24, "shots": [{"start": 0, "end": 100, "frames": [
        {"frame": 10, "sharpness": 100, "personal_extra_role": 0.9}]}]}
    assert "personal_extra_role" not in apply_profile(analysis, trained)["shots"][0]["frames"][0]


def test_binary_profile_round_trip_and_validation_keep_independent_copies(tmp_path):
    trained = profile()
    path = tmp_path / "binary.json"
    save_profile(trained, path)
    assert load_profile(path) == trained
    copied = validate_profile(trained)
    copied["role_assignment"]["weights"][0] += 1
    assert copied != trained


@pytest.mark.parametrize("change", [
    lambda model: model.update(kind="pickle"),
    lambda model: model.update(version=True),
    lambda model: model.update(trained=1),
    lambda model: model.update(feature_names=["wrong"]),
    lambda model: model.update(weights=[0]),
    lambda model: model["weights"].__setitem__(0, float("nan")),
    lambda model: model["weights"].__setitem__(0, True),
    lambda model: model["weights"].__setitem__(0, 10 ** 400),
    lambda model: model.update(bias=float("inf")),
    lambda model: model.update(train_samples=True),
    lambda model: model.update(train_samples=3),
    lambda model: model["report"].update(train_groups=["held-out"]),
    lambda model: model["report"].update(validation_groups=["chapter-a"]),
    lambda model: model["report"]["train_counts"].update(extra=0),
    lambda model: model["report"]["train_counts"].update(extra=True),
    lambda model: model["report"].update(train_balanced_accuracy=float("nan")),
    lambda model: model["report"].update(validation_balanced_accuracy=1),
    lambda model: model["report"].update(validation_unavailable=False),
    lambda model: model["report"].update(unavailable_reason=None),
    lambda model: model.update(unknown="unvalidated metadata"),
])
def test_invalid_binary_metadata_or_misleading_reports_are_rejected(change):
    trained = profile()
    change(trained["role_assignment"])
    with pytest.raises(ValueError, match="role model"):
        validate_profile(trained)


def test_binary_sampling_is_bounded_and_deterministic(monkeypatch):
    monkeypatch.setattr("vispa_mp.role_learning.MAX_SAMPLES", 20)
    refs = [reference("a", copies=30), reference("b", copies=40), reference("z", copies=25)]
    model = train_role_assignment(refs, "z", FEATURE_NAMES)
    again = train_role_assignment(refs, "z", FEATURE_NAMES)
    assert model == again
    assert model["train_samples"] == 20
    assert sum(model["report"]["validation_counts"].values()) == 20


def test_binary_training_is_cancellable_without_mutating_references():
    ref = reference()
    before = deepcopy(ref)
    messages = []
    with pytest.raises(InterruptedError, match="stopped"):
        train_profile([ref], progress=messages.append,
                      cancel=lambda: any("Core/Extra role" in message for message in messages))
    assert ref == before

"""Local preference learning above the existing visual and speech analyses.

Marked images are examples of a choice, rather than proof that every other
image is bad. The learner therefore compares them with a small, weakly weighted
set of alternatives in the same shot (or nearby shots for a page boundary).
An optional supervised head also learns Core/Extra role preferences from
explicitly labelled examples. It never changes marker limits, source frames,
or any existing visual model.
"""

from copy import deepcopy
import hashlib
import heapq
import json
from math import isfinite, log1p, sqrt
import os
from pathlib import Path
import tempfile

import numpy as np


PROFILE_KIND = "vispa-mp-profile"
REFERENCE_KIND = "vispa-mp-reference"
CROSS_VALIDATION_KIND = "vispa-mp-cross-validation"
VERSION = 1
ROLES = ("core", "extra", "page")
FEATURE_NAMES = (
    "sharpness", "relative_sharpness", "open_mouth", "closed_mouth", "mouth_interior",
    "teeth", "motion_blur", "expression", "from_behind", "face", "group", "solo",
    "held_drawing", "shot_phase", "short_shot", "motion", "cut_brightness", "cut_colour",
    "cut_structure", "speech", "speech_phase", "mouth_with_teeth", "mouth_advantage",
)
_FEATURE_COUNT = len(FEATURE_NAMES)
_MAX_PROFILE_BYTES = 2_000_000
_MAX_ROLE_PAIRS = 40_000
_MAX_REFERENCE_PAIRS = 4_000
_MAX_CROSS_VALIDATION_GROUPS = 64
_STOPPED = "Personal profile training was stopped."


def _finite(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if isfinite(number) else default


def _unit(value):
    return min(1.0, max(0.0, _finite(value)))


def _feature_context(shot, fps):
    """Measurements shared by all candidates of one shot."""
    fps = max(0.001, _finite(fps, 24))
    start = _finite(shot.get("start"))
    span = max(1.0, _finite(shot.get("end"), start + 1) - start)
    best = max((max(0.0, _finite(item.get("sharpness"))) for item in shot.get("frames", ())),
               default=None)
    neighbours = [_finite(item.get("neighbor")) for item in shot.get("frames", ())]
    median = float(np.median(neighbours)) if neighbours else 0.0
    return start, span, fps, best, median * 1.15 + 0.75, shot


def _frame_features(frame, context, line):
    start, span, fps, best, hold_limit, shot = context
    number = _finite(frame.get("frame"), start)
    sharpness = max(0.0, _finite(frame.get("sharpness")))
    best = sharpness if best is None else best
    opened = _unit(frame.get("open_mouth", frame.get("mouth", 0)))
    closed = _unit(frame.get("closed_mouth"))
    interior = max(opened, _unit(frame.get("tongue")), _unit(frame.get("uvula")))
    teeth_only = max(_unit(frame.get(key)) for key in (
        "upper_teeth_only", "lower_teeth_only", "clenched_teeth"))
    cavity = max(0.0, interior - teeth_only)
    teeth = _unit(frame.get("teeth"))
    hold = frame.get("hold")
    if hold is None:
        hold = _finite(frame.get("neighbor")) <= hold_limit
    speech_phase = ((number - _finite(line.get("start"))) /
                    max(1.0, _finite(line.get("end")) - _finite(line.get("start")))) if line else 0.5
    values = (
        log1p(sharpness) / log1p(10_000), sharpness / max(1.0, best), opened, closed,
        cavity, teeth, frame.get("motion_blur", 0), frame.get("expression", 0),
        frame.get("from_behind", 0), frame.get("face", 0), frame.get("group", 0),
        frame.get("solo", 0), float(bool(hold)), (number - start) / span,
        1.0 / (1.0 + span / fps), _finite(shot.get("motion")) / 40,
        _finite(shot.get("cut_grey")) / 120, shot.get("cut_colour", 0),
        _finite(shot.get("cut_shape")) / 2, float(line is not None), speech_phase,
        cavity * teeth, (opened - closed + 1) / 2,
    )
    return [_unit(value) for value in values]


def feature_vector(frame, shot, fps=24, utterances=()):
    """Bounded relative features; neither absolute timecode nor chapter ID leaks in."""
    context = _feature_context(shot, fps)
    number = _finite(frame.get("frame"), context[0])
    line = next((line for line in utterances or ()
                 if _finite(line.get("start")) <= number < _finite(line.get("end"))), None)
    return _frame_features(frame, context, line)


def _first_lines(numbers, utterances):
    """Index first matching input-order line for all queried frames in one sweep.

    Overlapping lines keep the exact public ``feature_vector`` semantics: the
    first line in the supplied sequence wins, rather than the earliest start.
    Frames and shots may themselves arrive in arbitrary order.
    """
    if not utterances:
        return {}
    intervals = []
    for index, line in enumerate(utterances):
        start, end = _finite(line.get("start")), _finite(line.get("end"))
        if start < end:
            intervals.append((start, index, end))
    intervals.sort()
    found, active, cursor = {}, [], 0
    for number in sorted(set(numbers)):
        while cursor < len(intervals) and intervals[cursor][0] <= number:
            _start, index, end = intervals[cursor]
            heapq.heappush(active, (index, end))
            cursor += 1
        while active and active[0][1] <= number:
            heapq.heappop(active)
        if active:
            found[number] = utterances[active[0][0]]
    return found


def _baseline(role):
    """A named, reproducible comparison baseline; not the entire rule engine."""
    weights = np.zeros(_FEATURE_COUNT, dtype=np.float64)
    choices = {
        "core": {"sharpness": 1.6, "relative_sharpness": 1.3, "mouth_interior": 1.2,
                 "expression": 0.4, "motion_blur": -2, "from_behind": -0.8,
                 "held_drawing": 0.4, "shot_phase": 0.3, "mouth_with_teeth": 0.5},
        "extra": {"sharpness": 1.2, "relative_sharpness": 1, "motion_blur": -2,
                  "expression": 0.6, "motion": 0.5, "short_shot": 0.4},
        "page": {"sharpness": 0.6, "motion_blur": -1.2, "cut_brightness": 1.2,
                 "cut_colour": 1.2, "cut_structure": 0.7, "group": 0.6},
    }
    for name, value in choices[role].items():
        weights[FEATURE_NAMES.index(name)] = value
    return weights


def _check_cancel(cancel):
    if cancel is not None and cancel():
        raise InterruptedError(_STOPPED)


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _vector(values):
    if (not isinstance(values, (list, tuple)) or len(values) != _FEATURE_COUNT
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not isfinite(value) or not 0 <= value <= 1 for value in values)):
        raise ValueError("A learning sample has incompatible or unreadable visual features.")
    return tuple(float(value) for value in values)


def _references(references):
    if not isinstance(references, (list, tuple)) or not references:
        raise ValueError("Import at least one validated reference chapter before training.")
    result, seen_ids, total, media_groups = [], set(), 0, {}
    for reference in references:
        # An explicitly disabled chapter is outside the selected corpus. Its
        # old metadata must not influence either fitting or leakage checks.
        if isinstance(reference, dict) and reference.get("enabled") is False:
            continue
        if isinstance(reference, dict) and "enabled" in reference and not isinstance(reference["enabled"], bool):
            raise ValueError("A reference chapter's enabled state cannot be read.")
        if (not isinstance(reference, dict) or reference.get("kind") != REFERENCE_KIND
                or not _integer(reference.get("version")) or reference["version"] != VERSION
                or not isinstance(reference.get("id"), str) or not reference["id"]
                or not isinstance(reference.get("name"), str) or not reference["name"].strip()
                or not isinstance(reference.get("group_id"), str) or not reference["group_id"]
                or not isinstance(reference.get("samples"), list)):
            raise ValueError("A reference chapter cannot be read.")
        if reference.get("feature_names", list(FEATURE_NAMES)) != list(FEATURE_NAMES):
            raise ValueError("A reference uses a different version of the visual features. Import it again.")
        # A reference accidentally selected twice must not count twice.
        if reference["id"] in seen_ids:
            continue
        seen_ids.add(reference["id"])
        source = reference.get("source")
        media = source.get("media", ()) if isinstance(source, dict) else ()
        media = [media] if isinstance(media, str) else media
        if isinstance(media, (list, tuple)):
            for item in media:
                path = item.get("path") if isinstance(item, dict) else item
                if not isinstance(path, str) or not path:
                    continue
                key = os.path.normcase(os.path.abspath(path))
                group = media_groups.setdefault(key, reference["group_id"])
                if group != reference["group_id"]:
                    raise ValueError(
                        "Reference chapters sharing a source video must use the same chapter group, "
                        "so the same footage cannot enter both training and validation.")
        copied, frames = [], set()
        for sample in reference["samples"]:
            if (not isinstance(sample, dict) or not _integer(sample.get("frame"))
                    or not _integer(sample.get("shot")) or not isinstance(sample.get("roles"), list)
                    or any(role not in ROLES for role in sample["roles"])
                    or len(set(sample["roles"])) != len(sample["roles"])):
                raise ValueError("A reference image or its role cannot be read.")
            roles = set(sample["roles"])
            if "page" in roles and "core" not in roles or "extra" in roles and len(roles) > 1:
                raise ValueError("A reference image has conflicting roles.")
            if sample["frame"] in frames:
                raise ValueError("A reference chapter contains the same frame twice.")
            frames.add(sample["frame"])
            copied.append(dict(sample, features=_vector(sample.get("features"))))
        copied.sort(key=lambda sample: sample["frame"])
        total += len(copied)
        if total > 200_000 or len(result) > 2_000:
            raise ValueError("This learning corpus is too large for one local training run.")
        result.append(dict(reference, samples=copied))
    if not result:
        raise ValueError("Enable at least one validated reference chapter before training.")
    return sorted(result, key=lambda item: (item["group_id"], item["id"]))


def _near_equivalent(winner, alternative, fps):
    if winner["shot"] != alternative["shot"]:
        return False
    if abs(winner["frame"] - alternative["frame"]) <= max(1, round(fps * 0.04)):
        return True
    first, second = winner.get("signature"), alternative.get("signature")
    if (isinstance(first, list) and isinstance(second, list) and first and len(first) == len(second)
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
                    for value in first + second)):
        if sum(abs(a - b) for a, b in zip(first, second)) / len(first) < 0.5:
            return True
    # Repeated drawings can have a different timestamp but no meaningful visual
    # difference. Time/shot-only features must not manufacture a preference.
    visual = range(FEATURE_NAMES.index("shot_phase"))
    return max(abs(winner["features"][index] - alternative["features"][index])
               for index in visual) < 1e-5


def _spread_indices(length, maximum):
    if maximum < 1:
        return []
    if maximum == 1:
        return [length // 2] if length else []
    if length <= maximum:
        return list(range(length))
    return sorted({round(index * (length - 1) / (maximum - 1)) for index in range(maximum)})


def _pairs(references, role, cancel=None):
    rows, weights, group_names = [], [], []
    reference_limit = min(_MAX_REFERENCE_PAIRS, max(1, _MAX_ROLE_PAIRS // max(1, len(references))))
    for reference in references:
        _check_cancel(cancel)
        samples = reference["samples"]
        clock = reference.get("timebase")
        fps = max(1.0, _finite(clock.get("fps") if isinstance(clock, dict) else None, 24))
        shots = sorted({sample["shot"] for sample in samples})
        shot_order = {shot: index for index, shot in enumerate(shots)}
        by_shot = {shot: [] for shot in shots}
        for sample in samples:
            by_shot[sample["shot"]].append(sample)
        positives = [sample for sample in samples if role in sample["roles"]]
        local_rows = []
        for winner_index in _spread_indices(len(positives), 500):
            _check_cancel(cancel)
            winner = positives[winner_index]
            alternatives = []
            if role == "page":
                centre = shot_order[winner["shot"]]
                pool = [sample for shot in shots[max(0, centre - 2):centre + 3] for sample in by_shot[shot]]
            else:
                pool = by_shot[winner["shot"]]
            for alternative in pool:
                if role in alternative["roles"]:
                    continue
                if role == "page":
                    # Non-start Core images are weak alternatives for a boundary,
                    # never negative examples of image quality.
                    if "extra" in alternative["roles"] or abs(shot_order[winner["shot"]] - shot_order[alternative["shot"]]) > 2:
                        continue
                elif alternative["roles"] or alternative["shot"] != winner["shot"]:
                    continue
                if _near_equivalent(winner, alternative, fps):
                    continue
                difference = np.asarray(winner["features"]) - np.asarray(alternative["features"])
                if np.linalg.norm(difference) > 1e-6:
                    alternatives.append(difference)
            for index in _spread_indices(len(alternatives), 16):
                local_rows.append(alternatives[index])
        indices = _spread_indices(len(local_rows), reference_limit)
        local_rows = [local_rows[index] for index in indices]
        if local_rows:
            # References and near-duplicate versions cannot dominate merely by
            # having many unlabelled frames. Group balancing follows below.
            rows.extend(local_rows)
            weights.extend([0.25 / len(local_rows)] * len(local_rows))
            group_names.extend([reference["group_id"]] * len(local_rows))
    if not rows:
        return np.empty((0, _FEATURE_COUNT)), np.empty(0)
    if len(rows) > _MAX_ROLE_PAIRS:
        indices = _spread_indices(len(rows), _MAX_ROLE_PAIRS)
        rows, weights, group_names = ([rows[index] for index in indices], [weights[index] for index in indices],
                                      [group_names[index] for index in indices])
    group_totals = {}
    for group, weight in zip(group_names, weights):
        group_totals[group] = group_totals.get(group, 0.0) + weight
    weights = np.asarray([0.25 * weight / group_totals[group] for group, weight in zip(group_names, weights)])
    return np.asarray(rows, dtype=np.float64), weights


def _accuracy(pairs, weights):
    if not len(pairs):
        return None
    margins = pairs @ weights
    return float(np.mean(np.where(margins > 1e-9, 1.0, np.where(margins < -1e-9, 0.0, 0.5))))


def _fit(pairs, pair_weights, baseline, cancel):
    weights = baseline.copy()
    # Each media group contributes a quarter-weight preference loss. Keep that
    # scale relative to the regularisation prior instead of cancelling it away.
    normalizer = max(1.0, float(pair_weights.sum()) / 0.25)
    for epoch in range(500):
        if epoch % 10 == 0:
            _check_cancel(cancel)
        margins = np.clip(pairs @ weights, -40, 40)
        error = 1.0 / (1.0 + np.exp(margins))
        gradient = -(pairs.T @ (pair_weights * error)) / normalizer + 0.015 * (weights - baseline)
        length = float(np.linalg.norm(gradient))
        if length < 1e-7:
            break
        rate = 1.0 / sqrt(1.0 + epoch / 100)
        weights -= rate * gradient / max(1.0, length / 5)
        weights = np.clip(weights, -20, 20)
    return weights


def train_profile(references, name="Personal profile", holdout_group=None, progress=None, cancel=None):
    """Fit a deterministic local ranking model, holding out whole media groups.

    Reported accuracy concerns the weak preference comparisons, not a verdict
    that unmarked images are bad, and not the precision of the entire marker
    pipeline. A single chapter can train a draft profile but cannot validate it.
    """
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise ValueError("Choose a profile name between 1 and 200 characters.")
    _check_cancel(cancel)
    references = _references(references)
    groups = sorted({reference["group_id"] for reference in references})
    if holdout_group is not None and holdout_group not in groups:
        raise ValueError("The validation chapter is not in the imported references.")
    if holdout_group is not None and len(groups) < 2:
        raise ValueError("A validation chapter needs at least one different chapter for training.")
    held = holdout_group if holdout_group is not None else groups[-1] if len(groups) > 1 else None
    train = [reference for reference in references if reference["group_id"] != held]
    validation = [reference for reference in references if reference["group_id"] == held]
    report = {
        "reference_count": len(references), "sample_count": sum(len(reference["samples"]) for reference in references),
        "train_groups": [group for group in groups if group != held],
        "validation_groups": [held] if held is not None else [],
        "validation_unavailable": held is None, "roles": {}, "warnings": [],
        "metric": "pairwise_preference_accuracy", "baseline": "standard_visual_weights_v1",
        "alternative_weight": 0.25,
        "group_names": {group: sorted({reference.get("name") or reference["id"] for reference in references
                                       if reference["group_id"] == group}) for group in groups},
    }
    if held is None:
        report["warnings"].append("Only one media group is available. This profile has no independent chapter validation.")
    models = {}
    for role in ROLES:
        _check_cancel(cancel)
        if progress is not None:
            progress(f"Training {role.capitalize()} preferences…")
        pairs, weights = _pairs(train, role, cancel)
        held_pairs, _ = _pairs(validation, role, cancel)
        baseline = _baseline(role)
        learned = _fit(pairs, weights, baseline, cancel) if len(pairs) else baseline
        models[role] = {"weights": learned.tolist(), "bias": float(np.clip(-learned.sum() / 2, -100, 100)),
                        "trained": bool(len(pairs)), "pairs": len(pairs)}
        report["roles"][role] = {
            "trained": bool(len(pairs)), "train_pairs": len(pairs), "validation_pairs": len(held_pairs),
            "baseline_accuracy": _accuracy(held_pairs, baseline) if len(pairs) else None,
            "personal_accuracy": _accuracy(held_pairs, learned) if len(pairs) else None,
            "train_accuracy": _accuracy(pairs, learned),
        }
        if not len(pairs):
            report["warnings"].append(f"No usable {role} preference pairs: standard rules remain in charge for this role.")
        elif not len(held_pairs) and held is not None:
            report["warnings"].append(f"The held-out chapter has no comparable {role} choices; this role is not independently validated.")
    from vispa_mp.role_learning import train_role_assignment
    role_assignment = train_role_assignment(references, held, FEATURE_NAMES, progress, cancel)
    if not any(model["trained"] for model in models.values()) and role_assignment is None:
        raise ValueError("These references contain no usable preference comparisons. Import marked images and distinct alternatives.")
    profile = {"kind": PROFILE_KIND, "version": VERSION, "name": name.strip(),
               "feature_names": list(FEATURE_NAMES), "roles": models, "report": report}
    identity = {"name": profile["name"], "roles": models,
                "references": [reference["id"] for reference in train]}
    if role_assignment is not None:
        profile["role_assignment"] = role_assignment
        identity["role_assignment"] = {key: value for key, value in role_assignment.items() if key != "report"}
    identifier = json.dumps(identity,
                            sort_keys=True, separators=(",", ":"), allow_nan=False)
    profile["id"] = "personal-" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:20]
    _check_cancel(cancel)
    if progress is not None:
        progress("Personal profile trained. Review the validation report before activation.")
    return validate_profile(profile)


def _cross_validation_aggregates(folds):
    """Each independently held-out chapter has equal weight in the headline score."""
    result = {}
    for role in ROLES:
        available = [fold["roles"][role] for fold in folds if fold["roles"][role]["reason"] is None]
        baseline = sum(entry["baseline_accuracy"] for entry in available) / len(available) if available else None
        personal = sum(entry["personal_accuracy"] for entry in available) / len(available) if available else None
        deltas = [entry["personal_accuracy"] - entry["baseline_accuracy"] for entry in available]
        result[role] = {
            "baseline_accuracy": baseline, "personal_accuracy": personal,
            "delta": personal - baseline if available else None,
            "groups_evaluated": len(available), "groups_total": len(folds),
            "groups_skipped": len(folds) - len(available),
            "validation_pairs": sum(entry["validation_pairs"] for entry in available),
            "groups_improved": sum(delta > 1e-12 for delta in deltas),
            "groups_regressed": sum(delta < -1e-12 for delta in deltas),
            "groups_unchanged": sum(abs(delta) <= 1e-12 for delta in deltas),
        }
    return result


def cross_validate(references, progress=None, cancel=None):
    """Evaluate every whole media group once, without saving or activating a model.

    Each fold starts afresh from fixed visual weights, using only the remaining
    chapters for fitting. Scores concern the weak preference comparisons, not
    the precision of complete marker placement or the quality of final pages.
    """
    _check_cancel(cancel)
    references = _references(references)
    groups = sorted({reference["group_id"] for reference in references})
    if len(groups) < 2:
        raise ValueError("Cross-validation needs at least two different chapter groups.")
    if len(groups) > _MAX_CROSS_VALIDATION_GROUPS:
        raise ValueError(
            f"One local cross-validation run supports at most {_MAX_CROSS_VALIDATION_GROUPS} chapter groups. "
            "Select fewer groups for this evaluation.")
    sample_count = sum(len(reference["samples"]) for reference in references)
    if not sample_count:
        raise ValueError("Import reference images before running cross-validation.")
    report = {
        "kind": CROSS_VALIDATION_KIND, "version": VERSION, "method": "leave_one_group_out",
        "metric": "pairwise_preference_accuracy", "baseline": "standard_visual_weights_v1",
        "aggregation": "macro_by_group", "reference_count": len(references),
        "sample_count": sample_count, "groups": groups, "fold_count": len(groups),
        "group_names": {group: sorted({reference["name"] for reference in references
                                       if reference["group_id"] == group}) for group in groups},
        "folds": [], "roles": {}, "warnings": [
            "These scores compare weak image preferences against fixed visual weights. "
            "They do not measure final page quality or the complete marker pipeline.",
        ],
    }
    if len(groups) == 2:
        report["warnings"].append("With two chapter groups, each fold learns from only one other group.")
    for number, held in enumerate(groups, 1):
        _check_cancel(cancel)
        train = [reference for reference in references if reference["group_id"] != held]
        validation = [reference for reference in references if reference["group_id"] == held]
        fold = {"heldout_group": held, "train_groups": [group for group in groups if group != held], "roles": {}}
        label = ", ".join(report["group_names"][held])
        for role in ROLES:
            _check_cancel(cancel)
            if progress is not None:
                progress(f"Cross-validation {number}/{len(groups)} · {label} · {role.capitalize()}")
            pairs, pair_weights = _pairs(train, role, cancel)
            held_pairs, _ = _pairs(validation, role, cancel)
            reason = "no_training_pairs" if not len(pairs) else "no_validation_pairs" if not len(held_pairs) else None
            baseline_accuracy = personal_accuracy = None
            if reason is None:
                baseline = _baseline(role)
                # Never warm-start from a previous fold: its weights may have
                # seen the chapter currently being held out.
                learned = _fit(pairs, pair_weights, baseline, cancel)
                baseline_accuracy = _accuracy(held_pairs, baseline)
                personal_accuracy = _accuracy(held_pairs, learned)
            fold["roles"][role] = {
                "trained": reason is None, "train_pairs": len(pairs), "validation_pairs": len(held_pairs),
                "baseline_accuracy": baseline_accuracy, "personal_accuracy": personal_accuracy, "reason": reason,
            }
        report["folds"].append(fold)
    report["roles"] = _cross_validation_aggregates(report["folds"])
    report["validation_unavailable"] = not any(entry["groups_evaluated"] for entry in report["roles"].values())
    for role, entry in report["roles"].items():
        if entry["groups_skipped"]:
            report["warnings"].append(
                f"{role.capitalize()}: {entry['groups_evaluated']}/{len(groups)} chapter groups have comparable "
                "training and held-out choices; uncomparable groups are excluded from the average.")
    _check_cancel(cancel)
    if progress is not None:
        progress("Cross-validation finished. No profile was saved or activated.")
    return validate_cross_validation_report(report)


def _number(value, low=-100.0, high=100.0):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and isfinite(value) and low <= value <= high)


def validate_profile(profile):
    """Validate a portable JSON profile before any score is applied."""
    if (not isinstance(profile, dict) or profile.get("kind") != PROFILE_KIND
            or not _integer(profile.get("version")) or profile["version"] != VERSION
            or profile.get("feature_names") != list(FEATURE_NAMES)
            or not isinstance(profile.get("id"), str) or not 1 <= len(profile["id"]) <= 128
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in profile["id"])
            or not isinstance(profile.get("name"), str) or not profile["name"].strip()
            or len(profile["name"]) > 200):
        raise ValueError("This is not a compatible VISPA MP personal profile.")
    roles = profile.get("roles")
    if not isinstance(roles, dict) or set(roles) != set(ROLES):
        raise ValueError("The personal profile has incompatible image roles.")
    for role in ROLES:
        model = roles[role]
        if (not isinstance(model, dict) or not isinstance(model.get("weights"), list)
                or len(model["weights"]) != _FEATURE_COUNT
                or any(not _number(value) for value in model["weights"])
                or not _number(model.get("bias")) or not isinstance(model.get("trained"), bool)
                or not _integer(model.get("pairs")) or not 0 <= model["pairs"] <= _MAX_ROLE_PAIRS
                or model["trained"] != (model["pairs"] > 0)):
            raise ValueError(f"The personal profile's {role} weights cannot be read.")
    if not any(model["trained"] for model in roles.values()) and "role_assignment" not in profile:
        raise ValueError("This profile contains no learned preferences.")
    report = profile.get("report")
    if not isinstance(report, dict) or not isinstance(report.get("validation_unavailable"), bool):
        raise ValueError("The personal profile has no readable validation report.")
    for key in ("train_groups", "validation_groups"):
        if (not isinstance(report.get(key), list) or any(not isinstance(group, str) or not group
                                                        for group in report[key])
                or len(set(report[key])) != len(report[key])):
            raise ValueError("The profile's chapter groups cannot be read.")
    if (not report["train_groups"] or set(report["train_groups"]) & set(report["validation_groups"])
            or report["validation_unavailable"] != (not report["validation_groups"])):
        raise ValueError("Training and validation chapters must be separate media groups.")
    for key in ("reference_count", "sample_count"):
        if not _integer(report.get(key)) or report[key] < 1:
            raise ValueError("The profile's reference counts cannot be read.")
    if (not isinstance(report.get("warnings"), list)
            or any(not isinstance(warning, str) for warning in report["warnings"])
            or not isinstance(report.get("roles"), dict) or set(report["roles"]) != set(ROLES)):
        raise ValueError("The personal profile's learning report cannot be read.")
    for role in ROLES:
        entry = report["roles"][role]
        if not isinstance(entry, dict) or entry.get("trained") is not roles[role]["trained"]:
            raise ValueError("The profile's role report is inconsistent.")
        for key in ("train_pairs", "validation_pairs"):
            if not _integer(entry.get(key)) or not 0 <= entry[key] <= _MAX_ROLE_PAIRS:
                raise ValueError("The profile's comparison counts cannot be read.")
        if entry["train_pairs"] != roles[role]["pairs"]:
            raise ValueError("The profile's learning counts are inconsistent.")
        for key in ("baseline_accuracy", "personal_accuracy"):
            if key not in entry or entry[key] is not None and not _number(entry[key], 0, 1):
                raise ValueError("The profile's validation metrics cannot be read.")
            if (report["validation_unavailable"] or entry["validation_pairs"] == 0 or not entry["trained"]) and entry[key] is not None:
                raise ValueError("The profile reports a validation score without independent comparisons.")
    if "role_assignment" in profile:
        from vispa_mp.role_learning import validate_role_assignment
        validate_role_assignment(profile["role_assignment"], FEATURE_NAMES,
                                 report["train_groups"], report["validation_groups"])
    try:
        encoded = json.dumps(profile, allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("The personal profile contains unreadable values.") from error
    if len(encoded) > _MAX_PROFILE_BYTES:
        raise ValueError("The personal profile is too large.")
    return deepcopy(profile)


def save_profile(profile, path):
    """Atomically save validated, portable JSON; no executable serialization."""
    profile = validate_profile(profile)
    data = json.dumps(profile, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}-", suffix=".part", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def _reject_constant(_text):
    raise ValueError("The personal profile contains an invalid number.")


def load_profile(path):
    try:
        target = Path(path)
        if target.stat().st_size > _MAX_PROFILE_BYTES:
            raise ValueError("The personal profile is too large.")
        with target.open("r", encoding="utf-8") as handle:
            profile = json.load(handle, parse_constant=_reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("This personal profile cannot be opened.") from error
    return validate_profile(profile)


def _metric_matches(value, expected):
    if expected is None:
        return value is None
    return _number(value, -1, 1) and abs(value - expected) <= 1e-12


def validate_cross_validation_report(report):
    """Validate fold isolation, coverage and macro arithmetic in a saved report."""
    if (not isinstance(report, dict) or report.get("kind") != CROSS_VALIDATION_KIND
            or not _integer(report.get("version")) or report["version"] != VERSION
            or report.get("method") != "leave_one_group_out"
            or report.get("metric") != "pairwise_preference_accuracy"
            or report.get("baseline") != "standard_visual_weights_v1"
            or report.get("aggregation") != "macro_by_group"):
        raise ValueError("This is not a compatible VISPA MP cross-validation report.")
    groups = report.get("groups")
    if (not isinstance(groups, list) or not 2 <= len(groups) <= _MAX_CROSS_VALIDATION_GROUPS
            or any(not isinstance(group, str) or not group for group in groups)
            or len(set(groups)) != len(groups)):
        raise ValueError("The cross-validation chapter groups cannot be read.")
    if (not _integer(report.get("fold_count")) or report["fold_count"] != len(groups)
            or not _integer(report.get("reference_count")) or report["reference_count"] < len(groups)
            or not _integer(report.get("sample_count")) or not 1 <= report["sample_count"] <= 200_000):
        raise ValueError("The cross-validation reference counts cannot be read.")
    names = report.get("group_names")
    if (not isinstance(names, dict) or set(names) != set(groups)
            or any(not isinstance(values, list) or not values
                   or any(not isinstance(value, str) or not value for value in values)
                   for values in names.values())):
        raise ValueError("The cross-validation chapter names cannot be read.")
    folds = report.get("folds")
    if not isinstance(folds, list) or len(folds) != len(groups):
        raise ValueError("The cross-validation folds cannot be read.")
    seen = set()
    for fold in folds:
        if not isinstance(fold, dict):
            raise ValueError("A cross-validation fold cannot be read.")
        held = fold.get("heldout_group")
        train = fold.get("train_groups")
        if (not isinstance(held, str) or held not in groups or held in seen
                or not isinstance(train, list)
                or any(not isinstance(group, str) for group in train)
                or len(train) != len(groups) - 1 or set(train) != set(groups) - {held}):
            raise ValueError("Each chapter must be held out exactly once and kept outside its training fold.")
        seen.add(held)
        roles = fold.get("roles")
        if not isinstance(roles, dict) or set(roles) != set(ROLES):
            raise ValueError("A cross-validation fold has incompatible image roles.")
        for role in ROLES:
            entry = roles[role]
            if not isinstance(entry, dict):
                raise ValueError("A cross-validation role result cannot be read.")
            for key in ("train_pairs", "validation_pairs"):
                if not _integer(entry.get(key)) or not 0 <= entry[key] <= _MAX_ROLE_PAIRS:
                    raise ValueError("A cross-validation comparison count cannot be read.")
            reason = ("no_training_pairs" if not entry["train_pairs"] else
                      "no_validation_pairs" if not entry["validation_pairs"] else None)
            if ("reason" not in entry or entry["reason"] != reason
                    or not isinstance(entry.get("trained"), bool)
                    or entry["trained"] != (reason is None)):
                raise ValueError("A cross-validation role result reports inconsistent coverage.")
            for key in ("baseline_accuracy", "personal_accuracy"):
                if (key not in entry or reason is not None and entry[key] is not None
                        or reason is None and not _number(entry[key], 0, 1)):
                    raise ValueError("A cross-validation score needs comparable training and held-out choices.")
    if seen != set(groups):
        raise ValueError("Each chapter group must appear in a cross-validation fold.")
    roles = report.get("roles")
    expected = _cross_validation_aggregates(folds)
    if not isinstance(roles, dict) or set(roles) != set(ROLES):
        raise ValueError("The cross-validation aggregate roles cannot be read.")
    for role in ROLES:
        entry = roles[role]
        if not isinstance(entry, dict):
            raise ValueError("A cross-validation aggregate cannot be read.")
        for key, value in expected[role].items():
            valid = (_integer(entry.get(key)) and entry[key] == value) if _integer(value) else (
                key in entry and _metric_matches(entry[key], value))
            if not valid:
                raise ValueError("Cross-validation aggregates must match the independent per-chapter scores.")
    unavailable = not any(entry["groups_evaluated"] for entry in expected.values())
    if (not isinstance(report.get("validation_unavailable"), bool)
            or report["validation_unavailable"] != unavailable
            or not isinstance(report.get("warnings"), list)
            or not report["warnings"] or any(not isinstance(warning, str) for warning in report["warnings"])):
        raise ValueError("The cross-validation status or its explanation cannot be read.")
    try:
        encoded = json.dumps(report, allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("The cross-validation report contains unreadable values.") from error
    if len(encoded) > _MAX_PROFILE_BYTES:
        raise ValueError("The cross-validation report is too large.")
    return deepcopy(report)


def save_cross_validation_report(report, path):
    """Save a report atomically, independently of every trained profile."""
    report = validate_cross_validation_report(report)
    data = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}-", suffix=".part", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def _reject_cv_constant(_text):
    raise ValueError("The cross-validation report contains an invalid number.")


def load_cross_validation_report(path):
    try:
        target = Path(path)
        if target.stat().st_size > _MAX_PROFILE_BYTES:
            raise ValueError("The cross-validation report is too large.")
        with target.open("r", encoding="utf-8") as handle:
            report = json.load(handle, parse_constant=_reject_cv_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("This cross-validation report cannot be opened.") from error
    return validate_cross_validation_report(report)


def apply_profile(analysis, profile):
    """Return a scored copy. Untrained roles emit no score and keep legacy rules."""
    profile = validate_profile(profile)
    result = deepcopy(analysis)
    fps = _finite(result.get("fps"), 24)
    utterances = result.get("utterances") or ()
    trained = [(role, model) for role, model in profile["roles"].items() if model["trained"]]
    weights = np.asarray([model["weights"] for _role, model in trained], dtype=np.float64).T if trained else None
    biases = np.asarray([model["bias"] for _role, model in trained], dtype=np.float64) if trained else None
    role_assignment = profile.get("role_assignment")
    prepared, queries = [], []
    for shot in result.get("shots") or ():
        frames = shot.get("frames") or ()
        if not frames:
            continue
        context = _feature_context(shot, fps)
        numbers = [_finite(frame.get("frame"), context[0]) for frame in frames]
        prepared.append((frames, context, numbers))
        queries.extend(numbers)
    lines = _first_lines(queries, utterances)
    for frames, context, numbers in prepared:
        features = np.asarray([_frame_features(frame, context, lines.get(number))
                               for frame, number in zip(frames, numbers)], dtype=np.float64)
        scores = 1.0 / (1.0 + np.exp(-np.clip(features @ weights + biases, -40, 40))) if trained else None
        if role_assignment is not None:
            from vispa_mp.role_learning import role_scores
            extra_roles = role_scores(features, role_assignment)
        for index, frame in enumerate(frames):
            frame.pop("personal_extra_role", None)
            for role in ROLES:
                frame.pop(f"personal_{role}", None)
            for column, (role, _model) in enumerate(trained):
                frame[f"personal_{role}"] = float(scores[index, column])
            if role_assignment is not None:
                frame["personal_extra_role"] = float(extra_roles[index])
    return result

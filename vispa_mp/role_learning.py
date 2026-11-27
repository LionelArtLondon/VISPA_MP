"""Optional, supervised Core/Extra role preferences from approved markers.

Unmarked alternatives teach the existing quality rankers, never this head.
Here both classes are explicit editorial choices; Extra is not a bad Core.
"""

from math import isfinite, sqrt

import numpy as np

KIND = "extra_vs_core"
VERSION = 1
MAX_SAMPLES = 20_000
_STOPPED = "Personal profile training was stopped."


def _check_cancel(cancel):
    if cancel is not None and cancel():
        raise InterruptedError(_STOPPED)


def _spread(length, count):
    if length <= count:
        return list(range(length))
    if count == 1:
        return [length // 2]
    return [round(index * (length - 1) / (count - 1)) for index in range(count)]


def _labelled(references, cancel):
    """Bounded, deterministic sampling; every group/class gets a fair share."""
    pools = {}
    for reference in references:
        _check_cancel(cancel)
        for index, sample in enumerate(reference["samples"]):
            if index % 256 == 0:
                _check_cancel(cancel)
            roles = sample["roles"]
            if "extra" in roles:
                label = 1
            elif "core" in roles:
                label = 0
            else:
                continue
            pools.setdefault((reference["group_id"], label), []).append(sample["features"])
    if not pools:
        return np.empty((0, 0)), np.empty(0), [], {"core": 0, "extra": 0}
    # Deterministic equal allocation, redistributing unused small-pool capacity.
    keys = sorted(pools)
    allocation = {key: 0 for key in keys}
    remaining = MAX_SAMPLES
    active = list(keys)
    while remaining and active:
        share = max(1, remaining // len(active))
        for key in active:
            take = min(share, remaining, len(pools[key]) - allocation[key])
            allocation[key] += take
            remaining -= take
            if not remaining:
                break
        active = [key for key in active if allocation[key] < len(pools[key])]
    features, labels, groups = [], [], []
    for key in keys:
        group, label = key
        for index in _spread(len(pools[key]), allocation[key]) if allocation[key] else ():
            features.append(pools[key][index])
            labels.append(label)
            groups.append(group)
    labels = np.asarray(labels, dtype=np.float64)
    counts = {"core": int((labels == 0).sum()), "extra": int((labels == 1).sum())}
    return np.asarray(features, dtype=np.float64), labels, groups, counts


def _sample_weights(labels, groups):
    # Each explicit class contributes half the loss. Inside each class, source
    # groups contribute equally, regardless of chapter length or duplicate edits.
    sizes = {}
    for label, group in zip(labels, groups):
        key = (group, int(label))
        sizes[key] = sizes.get(key, 0) + 1
    group_counts = {label: sum(key[1] == label for key in sizes) for label in (0, 1)}
    return np.asarray([1.0 / (2 * group_counts[int(label)] * sizes[group, int(label)])
                       for label, group in zip(labels, groups)], dtype=np.float64)


def role_scores(features, model):
    """Extra preference score; independent of the three quality rankers."""
    margins = np.asarray(features) @ np.asarray(model["weights"]) + model["bias"]
    return 1.0 / (1.0 + np.exp(-np.clip(margins, -40, 40)))


def _fit(features, labels, sample_weights, cancel):
    centered = features - 0.5
    weights = np.zeros(features.shape[1], dtype=np.float64)
    bias = 0.0
    for epoch in range(600):
        if epoch % 10 == 0:
            _check_cancel(cancel)
        predictions = 1.0 / (1.0 + np.exp(-np.clip(centered @ weights + bias, -40, 40)))
        residuals = sample_weights * (predictions - labels)
        gradient = centered.T @ residuals + 0.015 * weights
        intercept_gradient = float(residuals.sum())
        if float(np.linalg.norm(gradient)) + abs(intercept_gradient) < 1e-7:
            break
        rate = 1.0 / sqrt(1.0 + epoch / 100)
        weights = np.clip(weights - rate * gradient, -20, 20)
        bias = float(np.clip(bias - rate * intercept_gradient, -20, 20))
    return weights.tolist(), float(np.clip(bias - weights.sum() / 2, -100, 100))


def _balanced_accuracy(features, labels, groups, model):
    if not len(labels) or not (labels == 0).any() or not (labels == 1).any():
        return None
    correct = (role_scores(features, model) >= 0.5) == labels
    return float(np.clip(_sample_weights(labels, groups) @ correct, 0, 1))


def train_role_assignment(references, held, feature_names, progress=None, cancel=None):
    """An optional head; no weights are fit with unlabelled or held-out frames."""
    train = [reference for reference in references if reference["group_id"] != held]
    validation = [reference for reference in references if reference["group_id"] == held]
    features, labels, groups, counts = _labelled(train, cancel)
    if not counts["core"] or not counts["extra"]:
        return None
    if progress is not None:
        progress("Training Core/Extra role preferences…")
    weights, bias = _fit(features, labels, _sample_weights(labels, groups), cancel)
    model = {"kind": KIND, "version": VERSION, "feature_names": list(feature_names),
             "weights": weights, "bias": bias, "trained": True, "train_samples": len(labels)}
    held_features, held_labels, held_groups, held_counts = _labelled(validation, cancel)
    reason = "no_independent_chapter" if held is None else (
        "both_roles_required" if not held_counts["core"] or not held_counts["extra"] else None)
    model["report"] = {
        "metric": "balanced_accuracy",
        "train_groups": sorted({reference["group_id"] for reference in train}),
        "validation_groups": [] if held is None else [held],
        "train_counts": counts, "validation_counts": held_counts,
        "train_balanced_accuracy": _balanced_accuracy(features, labels, groups, model),
        "validation_balanced_accuracy": None if reason else _balanced_accuracy(held_features, held_labels, held_groups, model),
        "validation_unavailable": reason is not None, "unavailable_reason": reason,
    }
    _check_cancel(cancel)
    return model


def _number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value) and low <= value <= high
    except OverflowError:
        return False


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_SAMPLES


def validate_role_assignment(model, feature_names, train_groups, validation_groups):
    """Validate optional portable metadata against the enclosing profile split."""
    error = "The personal profile's Core/Extra role model cannot be read."
    expected = {"kind", "version", "feature_names", "weights", "bias", "trained", "train_samples", "report"}
    if (not isinstance(model, dict) or set(model) != expected or model.get("kind") != KIND
            or type(model.get("version")) is not int or model["version"] != VERSION
            or model.get("feature_names") != list(feature_names) or model.get("trained") is not True
            or not isinstance(model.get("weights"), list) or len(model["weights"]) != len(feature_names)
            or any(not _number(value, -20, 20) for value in model["weights"])
            or not _number(model.get("bias"), -100, 100) or not _count(model.get("train_samples"))
            or model["train_samples"] < 2):
        raise ValueError(error)
    report = model["report"]
    fields = {"metric", "train_groups", "validation_groups", "train_counts", "validation_counts",
              "train_balanced_accuracy", "validation_balanced_accuracy", "validation_unavailable", "unavailable_reason"}
    if (not isinstance(report, dict) or set(report) != fields or report.get("metric") != "balanced_accuracy"
            or report.get("train_groups") != train_groups or report.get("validation_groups") != validation_groups
            or not _number(report.get("train_balanced_accuracy"), 0, 1)
            or not isinstance(report.get("validation_unavailable"), bool)):
        raise ValueError(error)
    for key in ("train_counts", "validation_counts"):
        counts = report[key]
        if (not isinstance(counts, dict) or set(counts) != {"core", "extra"}
                or any(not _count(value) for value in counts.values()) or sum(counts.values()) > MAX_SAMPLES):
            raise ValueError(error)
    train_counts, held_counts = report["train_counts"], report["validation_counts"]
    if (not train_counts["core"] or not train_counts["extra"]
            or sum(train_counts.values()) != model["train_samples"]):
        raise ValueError(error)
    reason = "no_independent_chapter" if not validation_groups else (
        "both_roles_required" if not held_counts["core"] or not held_counts["extra"] else None)
    if (report["unavailable_reason"] != reason or report["validation_unavailable"] != (reason is not None)
            or (not validation_groups and sum(held_counts.values()))
            or (report["validation_balanced_accuracy"] is not None if reason else
                not _number(report["validation_balanced_accuracy"], 0, 1))):
        raise ValueError(error)

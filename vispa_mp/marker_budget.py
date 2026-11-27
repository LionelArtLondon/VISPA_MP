"""Pure duration, bounds and unique-image counts for a global marker budget.

The budget counts Page starts, Core and Extra together. A Page start is one
image, even though its editorial role also includes Core. No project, Resolve
state or settings are changed here.
"""

import math


MAX_MARKERS = 2 ** 31 - 1
REFERENCE_RATES = (12.0, 30.0, 45.0)
BUDGET_DEFAULTS = {
    "global_markers_enabled": True,
    "global_markers_auto": True,
    "global_markers_per_min_min": 12.0,
    "global_markers_per_min_target": 30.0,
    "global_markers_per_min_max": 45.0,
    "global_markers_min": 0,
    "global_markers_target": 0,
    "global_markers_max": 0,
}
_BOOLEAN_KEYS = {"global_markers_enabled", "global_markers_auto"}
_RATE_KEYS = {f"global_markers_per_min_{part}" for part in ("min", "target", "max")}
_TOTAL_KEYS = {f"global_markers_{part}" for part in ("min", "target", "max")}
_MARKER_COLORS = {"Green", "Blue", "Cyan"}


def _finite(value):
    try:
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value))
    except OverflowError:
        return False


def valid_budget_value(key, value):
    """Strict type/range validation shared with settings and project loaders."""
    if key in _BOOLEAN_KEYS:
        return isinstance(value, bool)
    if key in _RATE_KEYS:
        return _finite(value) and 0 <= value <= MAX_MARKERS
    if key in _TOTAL_KEYS:
        return type(value) is int and 0 <= value <= MAX_MARKERS
    return True


def _span(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(frame) is not int for frame in value) or value[1] < value[0]):
        return None
    return list(value)


def _duration(analysis):
    """Use analyzed In/Out, full timeline including gaps, then the shot span."""
    if analysis is None:
        return None, 0.0, "unknown", None
    if not isinstance(analysis, dict):
        raise ValueError("The analyzed timeline duration cannot be read.")
    base = analysis.get("timebase")
    base = base if isinstance(base, dict) else {}
    fps = analysis.get("fps", base.get("fps"))
    if not _finite(fps) or fps <= 0:
        return None, 0.0, "unknown", "The analyzed timeline frame rate is unavailable; automatic marker totals are zero."
    source, raw = "unknown", None
    if analysis.get("range") is not None:
        source, raw = "range", analysis["range"]
    elif analysis.get("timeline_range") is not None:
        source, raw = "timeline", analysis["timeline_range"]
    elif analysis.get("end_frame") is not None:
        source, raw = "timeline", [analysis.get("start_frame", base.get("start_frame")), analysis["end_frame"]]
    else:
        shots = analysis.get("shots") or []
        if not isinstance(shots, (list, tuple)):
            return None, 0.0, "unknown", "The analyzed shot duration is unavailable; automatic marker totals are zero."
        spans = [_span([shot.get("start"), shot.get("end")]) if isinstance(shot, dict) else None for shot in shots]
        if spans and all(span is not None for span in spans):
            source, raw = "shots", [min(span[0] for span in spans), max(span[1] for span in spans)]
        elif spans:
            return None, 0.0, "unknown", "The analyzed shot duration is unavailable; automatic marker totals are zero."
    if raw is None:
        return None, 0.0, "unknown", None
    span = _span(raw)
    if span is None:
        return None, 0.0, "unknown", "The analyzed frame range is invalid; automatic marker totals are zero."
    try:
        seconds = (span[1] - span[0]) / fps
    except OverflowError:
        seconds = float("inf")
    if not math.isfinite(seconds):
        return None, 0.0, "unknown", "The analyzed duration is invalid; automatic marker totals are zero."
    return span, seconds, source, None


def _ordered(values, label, warnings):
    low, target, high = values
    if low > high:
        low, high = high, low
        warnings.append(f"The {label} minimum and maximum were reversed; their order was corrected.")
    bounded = max(low, min(high, target))
    if bounded != target:
        warnings.append(f"The {label} target was limited to its minimum and maximum.")
    return low, bounded, high


def budget_settings(settings, analysis):
    """Resolve explicit settings to coherent global marker totals.

    Missing activation preserves legacy behavior even though new GUI defaults
    enable the feature. Rates use timeline frames / fps, including 50 fields/s;
    displayed timecode_fps must never halve the duration. Automatic totals use
    ceil(min), nearest target (halves upward) and ceil(max). Manual totals are
    independent of duration. Requested settings remain unchanged.
    """
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError("The global marker budget settings cannot be read.")
    for key in BUDGET_DEFAULTS:
        if key in settings and not valid_budget_value(key, settings[key]):
            raise ValueError(f"The global marker budget setting {key} is invalid.")
    values = {**BUDGET_DEFAULTS, **{key: settings[key] for key in BUDGET_DEFAULTS if key in settings}}
    legacy = "global_markers_enabled" not in settings
    enabled = values["global_markers_enabled"] and not legacy
    automatic = values["global_markers_auto"]
    warnings = []
    rate_values = [float(values[f"global_markers_per_min_{part}"]) for part in ("min", "target", "max")]
    rates = dict(zip(("min", "target", "max"), _ordered(rate_values, "markers-per-minute", warnings)))
    span, seconds, source, duration_warning = _duration(analysis)
    minutes = seconds / 60
    if duration_warning and enabled and automatic:
        warnings.append(duration_warning)
    if automatic:
        scaled = [rates[part] * minutes for part in ("min", "target", "max")]
        if any(not math.isfinite(value) or value > MAX_MARKERS for value in scaled):
            warnings.append("Automatic marker totals exceed the supported limit and were capped.")
        scaled = [min(MAX_MARKERS, value) if math.isfinite(value) else MAX_MARKERS for value in scaled]
        low, target, high = math.ceil(scaled[0]), math.floor(scaled[1] + 0.5), math.ceil(scaled[2])
        bounded = max(low, min(high, target))
        if target != bounded:
            warnings.append("The rounded global marker target was limited to its minimum and maximum.")
        target = bounded
    else:
        low, target, high = _ordered([values[f"global_markers_{part}"] for part in ("min", "target", "max")],
                                    "global marker", warnings)
    return {"enabled": enabled, "automatic": automatic, "legacy": legacy,
            "minutes": minutes, "seconds": seconds, "duration_source": source, "span": span,
            "rates": rates, "min": low, "target": target, "max": high,
            "corrected": any("corrected" in warning or "limited" in warning or "capped" in warning for warning in warnings),
            "warnings": warnings}


def marker_frames(proposals, manual_frames=(), span=None):
    """Unique Page/Core/Extra images plus explicitly supplied reserved frames.

    ``span`` is half-open, just like the analyzed range. Manual frame positions
    have already been selected by the caller; repeated roles or records cannot
    count the same image twice.
    """
    if span is not None:
        span = _span(span)
        if span is None:
            raise ValueError("The marker counting range is invalid.")
    if proposals is None:
        proposals = ()
    if manual_frames is None:
        manual_frames = ()
    if not isinstance(proposals, (list, tuple)) or not isinstance(manual_frames, (list, tuple, set, frozenset)):
        raise ValueError("The marker image list cannot be read.")
    frames = set()
    for marker in proposals:
        if not isinstance(marker, dict):
            raise ValueError("A proposed marker image cannot be read.")
        if not isinstance(marker.get("color"), str) or marker["color"] not in _MARKER_COLORS:
            continue
        frame = marker.get("frame")
        if type(frame) is not int:
            raise ValueError("A proposed marker image has an invalid frame.")
        frames.add(frame)
    for frame in manual_frames:
        if type(frame) is not int:
            raise ValueError("A reserved marker image has an invalid frame.")
        frames.add(frame)
    return {frame for frame in frames if span is None or span[0] <= frame < span[1]}


def count_markers(proposals, manual_frames=(), span=None):
    """Count each marked image once across all roles and reserved markers."""
    return len(marker_frames(proposals, manual_frames, span))


def target_window(budget):
    """A soft total target, never a quota for individual minutes or scenes."""
    target = int(budget["target"])
    return (max(int(budget["min"]), math.ceil(target * 0.9)),
            min(int(budget["max"]), math.floor(target * 1.1)))


def _band(values):
    if (not isinstance(values, (list, tuple)) or len(values) != 3
            or any(not _finite(value) or not 0 <= value <= MAX_MARKERS for value in values)):
        raise ValueError("The marker density band is invalid.")
    low, high = sorted((float(values[0]), float(values[2])))
    return low, max(low, min(high, float(values[1]))), high


def compression_for_band(values, reference=REFERENCE_RATES):
    """Position the slider from the whole band, with the reference at 50%."""
    volume, baseline = sum(_band(values)), sum(_band(reference))
    if baseline <= 0:
        raise ValueError("The reference marker density must be positive.")
    if volume <= 0:
        return 1.0
    return max(0.0, min(1.0, (1.0 - math.log2(volume / baseline)) / 2.0))


def band_for_compression(values, compression, reference=REFERENCE_RATES, *, integer=False):
    """Move the entire band together, retaining its shape after custom edits.

    At 0/50/100% the reference volume is doubled/unchanged/halved. All values
    describe the entire analyzed duration; this never partitions it into minutes.
    """
    current, baseline = _band(values), _band(reference)
    if not _finite(compression) or not isinstance(integer, bool) or sum(baseline) <= 0:
        raise ValueError("The marker density compression is invalid.")
    desired = sum(baseline) * 2 ** (1.0 - 2.0 * max(0.0, min(1.0, compression)))
    source = current if sum(current) > 0 else baseline
    factor = desired / sum(source)
    result = [min(MAX_MARKERS, value * factor) for value in source]
    if integer:
        result = [math.floor(value + 0.5) for value in result]
    return tuple(result)


def _compression_bounds(low, high):
    if any(not _finite(value) or not 0 <= value <= MAX_MARKERS for value in (low, high)):
        raise ValueError("The marker budget compression bounds are invalid.")
    return min(low, high), max(low, high)


def compression_for_target(low, target, high, previous=0.35):
    """0 selects the maximum, 1 the minimum; equal bounds preserve the slider."""
    low, high = _compression_bounds(low, high)
    if not _finite(target) or not _finite(previous):
        raise ValueError("The marker budget compression target is invalid.")
    if low == high:
        return max(0.0, min(1.0, float(previous)))
    return max(0.0, min(1.0, (high - max(low, min(high, target))) / (high - low)))


def target_for_compression(low, high, compression, *, integer=False):
    """Map a slider value back to a target, rounding manual totals half upward."""
    low, high = _compression_bounds(low, high)
    if not _finite(compression) or not isinstance(integer, bool):
        raise ValueError("The marker budget compression value is invalid.")
    value = high - max(0.0, min(1.0, compression)) * (high - low)
    if integer:
        # Total budgets use integer bounds; do not return a count outside them.
        lower, upper = math.ceil(low), math.floor(high)
        if lower > upper:
            raise ValueError("The marker budget has no integer target between its bounds.")
        return max(lower, min(upper, math.floor(value + 0.5)))
    return value

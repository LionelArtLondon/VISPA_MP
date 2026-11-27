"""Give intermediate local movements an Extra role without changing selection.

This is intentionally conservative: a shared, stable background and distinct
local changes are required. Speech, explicit edits and page boundaries remain
Core choices; neither a quota nor a personal score can bypass those safeguards.
"""

from bisect import bisect_right
from math import isfinite

import numpy as np

from vispa_mp.markers import CORE, EXTRA, NAMES, PAGE
from vispa_mp.preset import setting


def _signature(frame):
    values = frame.get("signature")
    if not isinstance(values, (list, tuple)) or len(values) != 64:
        return None
    try:
        signature = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):
        return None
    return signature if signature.shape == (64,) and np.isfinite(signature).all() else None


def _local_change(first, second):
    """(same composition, distinct drawing) from the existing 8x8 signatures."""
    delta = second - first
    differences = np.abs(delta)
    # Median background movement rejects relighting and gradual exposure shifts,
    # whereas a moving hand/object may change a few blocks considerably.
    same_composition = (abs(float(np.median(delta))) <= 4.0
                        and float((differences < 8.0).mean()) >= 0.60
                        and float((differences >= 12.0).mean()) <= 0.35)
    distinct = float((differences >= 12.0).sum()) >= 2 and float(differences.mean()) >= 0.75
    return same_composition, distinct


def _extra_preference(item, source):
    value = source.get("personal_extra_role", item.get("personal_extra_role"))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if isfinite(number) and 0 <= number <= 1 else None


def refine_roles(proposals, analysis, settings):
    """Copy proposals, changing only eligible intermediate Core roles to Extra.

    No image, frame, page start or source measurement is added or removed. Each
    actual shot is examined independently, so hard cuts and detected reframings
    cannot accidentally be treated as one continuous small action.
    """
    from vispa_mp.rules import _pages, core_target

    result = [dict(item) for item in proposals]
    ordered = sorted(result, key=lambda item: int(item["frame"]))
    pages = _pages(ordered, include_leading_extras=bool(core_target(settings) or settings.get("_budget_active")))
    core_counts = [sum(item["color"] in (PAGE, CORE) for item in page) for page in pages]
    page_of = {int(item["frame"]): index for index, page in enumerate(pages) for item in page}
    minimum = max(0, int(setting(settings, "core_page_min")))
    protected = {int(frame) for frame in analysis.get("manual_frames") or []}
    protected.update(int(frame) for frame in settings.get("_budget_protected_frames", ()))
    shots = sorted(analysis.get("shots") or [], key=lambda shot: int(shot["start"]))
    starts = [int(shot["start"]) for shot in shots]
    groups = {}
    for item in ordered:
        if item["color"] not in (PAGE, CORE):
            continue
        number = int(item["frame"])
        index = bisect_right(starts, number) - 1
        if index >= 0 and number < int(shots[index]["end"]):
            groups.setdefault(index, []).append(item)
    eligible = []
    for index, cores in groups.items():
        if len(cores) < 3:
            continue
        sources = {int(frame["frame"]): frame for frame in shots[index].get("frames") or []}
        first = _signature(sources.get(int(cores[0]["frame"]), {}))
        last = _signature(sources.get(int(cores[-1]["frame"]), {}))
        if first is None or last is None or not _local_change(first, last)[0]:
            continue
        for item in cores[1:-1]:
            number = int(item["frame"])
            if (item["color"] != CORE or number in protected or item.get("user_role")
                    or item.get("speech_quality_ok")
                    or item.get("rule") not in ("body", "speech_unverified")):
                continue
            source = sources.get(number, {})
            signature = _signature(source)
            if signature is None:
                continue
            before, after = _local_change(first, signature), _local_change(last, signature)
            # An exact hold is not another movement. Both story anchors must
            # differ locally from this image before it becomes an Extra.
            if not (all(before) and all(after)):
                continue
            preference = _extra_preference(item, source) if settings.get("_personal_role_assignment") else None
            if preference is not None and preference <= 0.35:
                continue
            eligible.append((preference if preference is not None else 0.5, item))
    # When a Core floor limits refinement, explicit learned Extra preferences
    # choose which of the otherwise equally safe intermediate roles to change.
    for _preference, item in sorted(eligible, key=lambda entry: (-entry[0], int(entry[1]["frame"]))):
        index = page_of[int(item["frame"])]
        if core_counts[index] <= minimum:
            continue
        item.update(color=EXTRA, name=NAMES[EXTRA], rule="intermediate", note="Extra, intermediate movement")
        core_counts[index] -= 1
    return result

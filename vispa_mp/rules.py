"""Rules that turn measured frames into green, blue and cyan markers."""

from math import ceil, floor, isfinite, sqrt
from statistics import median

from vispa_mp.markers import CORE, EXTRA, NAMES, PAGE
from vispa_mp.preset import setting

HOLD_EPSILON = 0.75


def mark_holds(frames, ratio):
    """A hold sits close to a neighbour. Limited animation lives on those frames."""
    if not frames:
        return frames
    diffs = [float(frame.get("neighbor") or 0.0) for frame in frames]
    limit = median(diffs) * float(ratio) + HOLD_EPSILON
    for frame, diff in zip(frames, diffs):
        frame["hold"] = diff <= limit
    return frames


def gap_frames(settings, key):
    """A gap set in seconds, as frames of the analyzed timeline (24 fps when unknown)."""
    fps = float((settings or {}).get("_fps") or 24)
    return max(0, int(round(float(setting(settings, key)) * fps)))


def _number(frame, key):
    value = frame.get(key)
    return 0.0 if value is None else float(value)


def mouth_state(frame, settings):
    """open, closed, or hidden (back of the head, empty frame, no face)."""
    if _number(frame, "from_behind") >= float(setting(settings, "behind_min")):
        return "hidden"
    face = _number(frame, "face")
    opened = _number(frame, "open_mouth")
    closed = _number(frame, "closed_mouth")
    minimum = float(setting(settings, "face_min"))
    if face < minimum and opened < minimum and closed < minimum:
        return "hidden"
    if opened > closed and opened >= float(setting(settings, "mouth_min")):
        return "open"
    return "closed"


def _shot_best(frames):
    return max((_number(frame, "sharpness") for frame in frames), default=0.0)


def quality_ok(frame, settings, best):
    if _number(frame, "motion_blur") > float(setting(settings, "motion_blur_max")):
        return False
    sharpness = _number(frame, "sharpness")
    if sharpness < float(setting(settings, "sharpness_floor")):
        return False
    return sharpness >= float(setting(settings, "sharpness_ratio")) * best


def _expression_score(frame, settings):
    weight = float(setting(settings, "expression_weight"))
    return _number(frame, "sharpness") * (1.0 + weight * _number(frame, "expression"))


def _alike(left, right, limit):
    first, second = left.get("signature") or [], right.get("signature") or []
    if not first or len(first) != len(second):
        return False
    return sum(abs(a - b) for a, b in zip(first, second)) / len(first) < limit


def drawing_change(left, right):
    """Contrast-normalised change in the cached 8×8 drawing signatures.

    Brightness alone is not action. The 8 grey-level stabiliser is the same as
    shot detection uses: near-black noise must not become a large shape change.
    """
    first, second = left.get("signature") or [], right.get("signature") or []
    if not first or len(first) != len(second):
        return 0.0

    def shape(values):
        mean = sum(values) / len(values)
        scale = sqrt(sum((value - mean) ** 2 for value in values) / len(values)) + 8.0
        return [(value - mean) / scale for value in values]

    return sum(abs(a - b) for a, b in zip(shape(first), shape(second))) / len(first)


def action_shot(shot, frames, settings):
    """A short moving shot, including drawings held for several source frames.

    ``neighbor`` deliberately takes the quieter neighbour to recognise holds;
    averaging that number misses A,A,B,B,C,C animation. Adjacent cached drawing
    changes provide an independent signal, without rerunning the image model.
    """
    duration = (shot["end"] - shot["start"]) / float(settings.get("_fps") or 24)
    if duration > float(setting(settings, "action_max_seconds")):
        return False
    if float(shot.get("motion") or 0) >= float(setting(settings, "action_motion")):
        return True
    ordered = sorted(frames, key=lambda frame: frame["frame"])
    changes = sorted(drawing_change(left, right) for left, right in zip(ordered, ordered[1:]))
    if not changes:
        return False
    # The upper tenth retains transitions between held poses, rather than
    # diluting them with all the repeated pictures of limited animation.
    activity = changes[max(0, ceil(0.9 * len(changes)) - 1)]
    return activity >= float(setting(settings, "action_structure"))


def _blocked(frame, taken, manual, minimum):
    return any(abs(int(frame) - int(other)) < minimum for other in list(taken) + list(manual))


def _overlaps(frame, utterances):
    number = int(frame["frame"])
    return any(utterance["start"] <= number < utterance["end"] for utterance in utterances)


def _end_frames(frames, shot, settings):
    span = max(1, shot["end"] - shot["start"])
    cut = shot["start"] + (1 - float(setting(settings, "end_fraction"))) * span
    end = [frame for frame in frames if frame["frame"] >= cut]
    return end or frames[-1:]


def _pick_body(frames, shot, utterances, settings, best):
    region = _end_frames(frames, shot, settings)
    usable = [frame for frame in region if quality_ok(frame, settings, best)]
    holds = [frame for frame in usable if frame.get("hold")]
    pool = holds or usable
    if not pool:
        return None

    def score(frame):
        mouth = 1.0
        if _overlaps(frame, utterances):
            mouth = 0.35 + _number(frame, "open_mouth")
        return _expression_score(frame, settings) * mouth

    return max(pool, key=lambda frame: (score(frame), frame["frame"]))


def _eligible(frames, settings):
    """Blur and the absolute sharpness floor. The relative floor is applied later, among equals."""
    return [frame for frame in frames
            if _number(frame, "motion_blur") <= float(setting(settings, "motion_blur_max"))
            and _number(frame, "sharpness") >= float(setting(settings, "sharpness_floor"))]


def _sharp_enough(frames, settings):
    if not frames:
        return []
    best = max(_number(frame, "sharpness") for frame in frames)
    floor = float(setting(settings, "sharpness_ratio")) * best
    kept = [frame for frame in frames if _number(frame, "sharpness") >= floor]
    return kept or frames


def _cavity(frame):
    """Dark inside of the mouth. A drawing that only shows teeth scores nothing."""
    interior = max(_number(frame, "open_mouth"), _number(frame, "tongue"), _number(frame, "uvula"))
    teeth_only = max(
        _number(frame, "upper_teeth_only"),
        _number(frame, "lower_teeth_only"),
        _number(frame, "clenched_teeth"),
    )
    return max(0.0, interior - teeth_only)


def _with_interior(frames):
    """Keep the poses where the inside of the mouth is actually drawn."""
    if not frames:
        return []
    best = max(_cavity(frame) for frame in frames)
    if best < 0.2:
        return frames
    floor = max(0.15, 0.5 * best)
    kept = [frame for frame in frames if _cavity(frame) >= floor]
    return kept or frames


def _speaking_key(frame, middle, use_teeth):
    """Inside the mouth first. Teeth only count once that inside is visible."""
    cavity = _cavity(frame)
    teeth = _number(frame, "teeth") if use_teeth and cavity >= 0.15 else 0.0
    mouth = _number(frame, "open_mouth") * (1 - _number(frame, "closed_mouth")) * (1 - _number(frame, "from_behind"))
    return (
        teeth,
        cavity,
        1 if frame.get("hold") else 0,
        _number(frame, "sharpness") * (0.2 + mouth),
        -abs(frame["frame"] - middle),
    )


def _pick_speech(frames, utterance, settings, best):
    inside = [frame for frame in frames if utterance["start"] <= frame["frame"] < utterance["end"]]
    if not inside:
        return None, "missing"
    eligible = _eligible(inside, settings) or inside
    middle = (utterance["start"] + utterance["end"]) / 2
    if not setting(settings, "require_open_mouth"):
        holds = [frame for frame in eligible if frame.get("hold")] or eligible
        pool = _sharp_enough(holds, settings)
        return max(pool, key=lambda frame: (_expression_score(frame, settings), -abs(frame["frame"] - middle))), "speech_plain"

    opens = [frame for frame in eligible if mouth_state(frame, settings) == "open"]
    if opens:
        rich = _with_interior(opens)
        pool = _sharp_enough(rich, settings)
        use_teeth = max(_cavity(frame) for frame in opens) >= 0.2
        return max(pool, key=lambda frame: _speaking_key(frame, middle, use_teeth)), "speech"
    if setting(settings, "mouth_fallback") == "none":
        return None, "missing"
    return max(eligible, key=lambda frame: (_number(frame, "sharpness"), -abs(frame["frame"] - middle))), "speech_unverified"


def _spread(frames, shot, count, taken, settings, cores, best, manual=()):
    if count <= 0:
        return []
    usable = [frame for frame in frames if quality_ok(frame, settings, best)]
    points = [shot["start"] + (index + 1) * (shot["end"] - shot["start"]) / (count + 1) for index in range(count)]
    chosen, used = [], set(taken)
    limit = float(setting(settings, "duplicate_diff"))
    minimum = gap_frames(settings, "min_extra_seconds")
    manual = {int(frame) for frame in manual}
    structure = float(setting(settings, "action_structure"))
    for point in points:
        pool = []
        for frame in usable:
            if frame["frame"] in used or frame["frame"] in manual or _blocked(frame["frame"], used, manual, minimum):
                continue
            if any(_alike(frame, core, limit) and drawing_change(frame, core) < structure
                   and not _mouth_saves(frame, core, settings) for core in list(cores) + chosen):
                continue
            pool.append(frame)
        if not pool:
            continue
        best = min(pool, key=lambda frame: (abs(frame["frame"] - point), not frame.get("hold"), -frame["sharpness"]))
        chosen.append(best)
        used.add(best["frame"])
    return chosen


def _mouth_saves(frame, core, settings):
    return mouth_state(frame, settings) == "open" and mouth_state(core, settings) != "open"


def _is_scene(shot, settings):
    if shot.get("opening"):
        return True
    return (float(shot.get("cut_grey") or 0) >= float(setting(settings, "scene_grey"))
            or float(shot.get("cut_colour") or 0) >= float(setting(settings, "scene_colour")))


def _is_group(frame, settings):
    return frame is not None and _number(frame, "group") >= float(setting(settings, "group_min")) and _number(frame, "group") > _number(frame, "solo")


def _note(kind):
    return {
        "body": "Core, end of shot",
        "speech": "Line, mouth open",
        "speech_plain": "Line",
        "speech_unverified": "Line, mouth not verified",
        "action": "Extra, action",
        "speech_extra": "Extra, second mouth",
    }[kind]


def _page_note(kind, group):
    if group:
        return "Page start, group shot"
    if kind == "speech":
        return "Page start, mouth open"
    if kind == "speech_unverified":
        return "Page start, mouth not verified"
    if kind == "speech_plain":
        return "Page start, line"
    return "Page start"


def _proposal(frame, color, kind, note, strength=0):
    return {
        "frame": int(frame["frame"]),
        "color": color,
        "name": NAMES[color],
        "note": note,
        "rule": kind,
        "mouth": round(_number(frame, "open_mouth"), 4),
        "cavity": round(_cavity(frame), 4),
        "teeth": round(_number(frame, "teeth"), 4),
        "sharpness": round(_number(frame, "sharpness"), 3),
        "image": frame.get("image") or "",
        "strength": float(strength),
    }


def page_goal(settings, minutes=None):
    """Pages asked for by the slider, before the shot count limits it.

    Low (0) is the high end of the range. High (1) is the low end. The range is
    for an episode of ``episode_minutes``; ``minutes`` analyzed get their share.
    """
    low = max(1, int(setting(settings, "target_pages_min")))
    high = max(1, int(setting(settings, "target_pages_max")))
    if low > high:
        low, high = high, low
    compression = min(1.0, max(0.0, float(setting(settings, "compression"))))
    goal = high - compression * (high - low)
    episode = float(setting(settings, "episode_minutes") or 0)
    if minutes and episode > 0:
        goal *= float(minutes) / episode
    return max(1, int(round(goal)))


def target_pages(settings, shot_count, minutes=None):
    """How many page opens to keep. Never more than one per shot."""
    return max(1, min(page_goal(settings, minutes), max(1, int(shot_count or 1))))


def analyzed_minutes(analysis):
    """Length of what was analyzed: the In/Out range, or the span of its shots."""
    fps = float(analysis.get("fps") or 0)
    if fps <= 0:
        return None
    span = analysis.get("range")
    if not span:
        shots = analysis.get("shots") or []
        if not shots:
            return None
        span = (min(int(shot["start"]) for shot in shots), max(int(shot["end"]) for shot in shots))
    frames = int(span[1]) - int(span[0])
    return frames / fps / 60 if frames > 0 else None


_DROP = {"action": 0, "speech_extra": 1, "speech_unverified": 2, "speech_plain": 3, "speech": 4, "body": 5, "page": 9}


def _bounds(settings, low_key, high_key):
    low = max(0, int(setting(settings, low_key)))
    high = max(1, int(setting(settings, high_key)))
    return low, high


def core_target(settings):
    """The optional Core average, bounded by the per-page Core limits."""
    value = float(setting(settings, "core_page_target"))
    if not isfinite(value) or value <= 0:
        return 0.0
    low, high = _bounds(settings, "core_page_min", "core_page_max")
    low = max(1, low)
    return min(max(value, low), max(low, high))


def _pages(proposals, include_leading_extras=False):
    pages, current = [], []
    for proposal in proposals:
        if (proposal["color"] == PAGE and current
                and (not include_leading_extras or any(item["color"] in (PAGE, CORE) for item in current))):
            pages.append(current)
            current = []
        current.append(proposal)
    if current:
        pages.append(current)
    return pages


def _page_limits(settings, minutes):
    low = max(1, int(setting(settings, "target_pages_min")))
    high = max(1, int(setting(settings, "target_pages_max")))
    low, high = min(low, high), max(low, high)
    episode = float(setting(settings, "episode_minutes") or 0)
    scale = float(minutes) / episode if minutes and episode > 0 else 1.0
    return max(1, int(round(low * scale))), max(1, int(round(high * scale)))


def _page_priority(item, settings):
    # A strong visual cut wins when two divisions balance the Core count equally.
    strength = float(item.get("strength") or 0) / max(1.0, float(setting(settings, "scene_grey")))
    return min(4.0, max(0.0, strength)) + (0.25 if item["color"] == PAGE else 0.0)


def _balanced_boundaries(cores, count, low, high, gap, settings):
    """Partition existing Core images; count balance comes before scene preference."""
    total = len(cores)
    costs, parents = {0: (0, 0.0)}, []
    for page in range(count):
        remaining = count - page - 1
        following, previous = {}, {}
        for start, cost in costs.items():
            first = max(start + low, total - remaining * high)
            last = min(start + high, total - remaining * low)
            for end in range(first, last + 1):
                if end < total and int(cores[end]["frame"]) - int(cores[start]["frame"]) < gap:
                    continue
                priority = _page_priority(cores[end], settings) if end < total else 0.0
                candidate = (cost[0] + ((end - start) * count - total) ** 2, cost[1] - priority)
                if end not in following or candidate < following[end]:
                    following[end], previous[end] = candidate, start
        costs = following
        parents.append(previous)
        if not costs:
            return None
    if total not in costs:
        return None
    starts, end = [], total
    for previous in reversed(parents):
        end = previous[end]
        starts.append(end)
    return sorted(starts)


def _spaced_boundaries(cores, count, gap, settings):
    """Fallback when the time gap prevents a division within the Core bounds."""
    latest = [len(cores) - 1]
    for _ in range(count - 1):
        end = latest[-1]
        latest.append(max(index for index in range(end)
                          if int(cores[end]["frame"]) - int(cores[index]["frame"]) >= gap))
    latest.reverse()
    starts = [0]
    for page in range(1, count):
        first = starts[-1] + 1
        pool = [index for index in range(first, latest[page] + 1)
                if int(cores[index]["frame"]) - int(cores[starts[-1]]["frame"]) >= gap]
        ideal = page * len(cores) / count
        starts.append(min(pool, key=lambda index: (abs(index - ideal), -_page_priority(cores[index], settings))))
    return starts


def _fit_core_story(proposals, settings, shot_count, minutes):
    cores = [item for item in proposals if item["color"] in (PAGE, CORE)]
    if not cores:
        return proposals, []
    average = core_target(settings)
    low, high = _page_limits(settings, minutes)
    ratio = len(cores) / average
    wanted = min({max(1, floor(ratio)), max(1, ceil(ratio))},
                 key=lambda pages: (abs(len(cores) / pages - average), pages))
    count = max(low, min(wanted, high))
    core_low, core_high = _bounds(settings, "core_page_min", "core_page_max")
    core_low, core_high = max(1, core_low), max(1, core_low, core_high)
    feasible_low = max(low, ceil(len(cores) / core_high))
    feasible_high = min(high, len(cores) // core_low)
    if feasible_low <= feasible_high:
        count = max(feasible_low, min(wanted, feasible_high))
    # The mean sets the low-compression density. Stronger compression still
    # reduces page count toward the configured lower bound; per-page selection
    # can discard Core candidates rather than forcing more pages to hold them.
    compression = min(1.0, max(0.0, float(setting(settings, "compression"))))
    count = max(low, min(high, int(round(count + (low - count) * compression))))
    warnings = []
    if wanted < low or wanted > high:
        warnings.append(
            f"Keeping all {len(cores)} Core candidates near {average:g} per page suggests {wanted} pages; "
            f"the page limits allow {low}–{high}. Core selection adapts within the per-page limits."
        )
    gap = gap_frames(settings, "min_green_seconds")
    spaced = [0]
    for index in range(1, len(cores)):
        if int(cores[index]["frame"]) - int(cores[spaced[-1]]["frame"]) >= gap:
            spaced.append(index)
    available = min(len(cores), max(1, int(shot_count or 1)), len(spaced))
    if count > available:
        warnings.append(f"{available} pages instead of {count}: available images, shots or the minimum page gap stop there.")
        count = available
    # If the page range makes the Core limits impossible, retain all candidates
    # here. Only the existing Core/total ceilings may remove them afterwards.
    split_low = min(core_low, max(1, len(cores) // count))
    split_high = max(core_high, ceil(len(cores) / count))
    # The floor/ceiling lengths attain the best possible balance. Try that small
    # search first; widening is only useful when timestamps prevent those sizes.
    starts = _balanced_boundaries(cores, count, max(split_low, len(cores) // count),
                                  min(split_high, ceil(len(cores) / count)), gap, settings)
    if starts is None:
        starts = _balanced_boundaries(cores, count, split_low, split_high, gap, settings)
    if starts is None:
        starts = _spaced_boundaries(cores, count, gap, settings)
        warnings.append("The minimum page gap prevents an even Core distribution; per-page bounds may limit the result.")
    chosen = {int(cores[index]["frame"]) for index in starts}
    fitted = []
    for item in proposals:
        updated = dict(item)
        if item["color"] == PAGE and int(item["frame"]) not in chosen:
            updated.update(color=CORE, name=NAMES[CORE], rule="body", note="Core")
        elif item["color"] == CORE and int(item["frame"]) in chosen:
            updated.update(color=PAGE, name=NAMES[PAGE], rule="page", note="Page start")
        fitted.append(updated)
    return fitted, warnings


def _fit_story(proposals, settings, shot_count, minutes=None):
    """Keep about as many page opens as the compression slider asks for."""
    if core_target(settings):
        return _fit_core_story(proposals, settings, shot_count, minutes)
    greens = [proposal for proposal in proposals if proposal["color"] == PAGE]
    if len(greens) < 1:
        return proposals, []
    target = target_pages(settings, shot_count, minutes)
    gap = gap_frames(settings, "min_green_seconds")
    chosen = {greens[0]["frame"]}
    pool = [proposal["frame"] for proposal in greens[1:]]
    while len(chosen) < target and pool and len(chosen) < len(greens):
        nxt = max(pool, key=lambda frame: min(abs(frame - kept) for kept in chosen))
        pool.remove(nxt)
        chosen.add(nxt)
    warnings = []
    if len(chosen) < target:
        while len(chosen) < target:
            ranked = sorted(
                (item for item in proposals if item["color"] == CORE and item["frame"] not in chosen
                 and all(abs(item["frame"] - kept) >= gap for kept in chosen)),
                key=lambda item: (min(abs(item["frame"] - kept) for kept in chosen), item.get("strength") or 0),
                reverse=True,
            )
            if not ranked:
                break
            chosen.add(ranked[0]["frame"])
        if len(chosen) < target:
            warnings.append(
                f"{len(chosen)} pages instead of {target}: the minimum gap between pages stops there."
            )
    fitted = []
    for proposal in proposals:
        updated = dict(proposal)
        if proposal["color"] == PAGE and proposal["frame"] not in chosen:
            updated["color"] = CORE
            updated["name"] = NAMES[CORE]
            updated["rule"] = "body"
            updated["note"] = "Core"
        elif proposal["color"] == CORE and proposal["frame"] in chosen:
            updated["color"] = PAGE
            updated["name"] = NAMES[PAGE]
            updated["rule"] = "page"
            updated["note"] = "Page start"
        fitted.append(updated)
    return fitted, warnings


def _trim_pages(proposals, settings):
    """A floor and a ceiling for corps images, and for every image on the page."""
    core_min, core_max = _bounds(settings, "core_page_min", "core_page_max")
    total_min, total_max = _bounds(settings, "total_page_min", "total_page_max")
    average = core_target(settings)
    # A margin of one image keeps this an average to approach, rather than an
    # exact quota. Existing floors take precedence; only Core images are ranked.
    soft_max = max(core_min, min(core_max, floor(average + 1))) if average else None
    warnings = []
    kept_pages = []
    for page in _pages(proposals, include_leading_extras=bool(core_target(settings))):
        kept = list(page)

        def cores():
            return [item for item in kept if item["color"] in (PAGE, CORE)]

        def sacrifice(pool):
            return min(pool, key=lambda item: (_DROP.get(item["rule"], 4), item["sharpness"], item["frame"]))

        while len(cores()) > core_max:
            pool = [item for item in kept if item["color"] == CORE]
            if not pool or len(cores()) - 1 < core_min:
                break
            kept.remove(sacrifice(pool))
        if soft_max is not None:
            while len(cores()) > soft_max:
                pool = [item for item in kept if item["color"] == CORE]
                if not pool or len(cores()) - 1 < core_min or len(kept) - 1 < total_min:
                    break
                kept.remove(sacrifice(pool))
            if len(cores()) > soft_max:
                warnings.append(
                    f"Page at frame {kept[0]['frame']}: the image minimum keeps the Core average above its target."
                )
        while len(kept) > total_max:
            extras = [item for item in kept if item["color"] == EXTRA]
            pool = extras or [item for item in kept if item["color"] == CORE]
            if not pool or len(kept) - 1 < total_min:
                break
            if not extras and len(cores()) - 1 < core_min:
                break
            kept.remove(sacrifice(pool))
        core_count = len(cores())
        if core_count < core_min or len(kept) < total_min:
            warnings.append(
                f"Page at frame {kept[0]['frame']}: {core_count} Core images, {len(kept)} in all, below the minimum."
            )
        elif core_count > core_max or len(kept) > total_max:
            warnings.append(
                f"Page at frame {kept[0]['frame']}: the minimum keeps the page above the maximum."
            )
        kept_pages.extend(kept)
    if average:
        page_count = sum(item["color"] == PAGE for item in kept_pages)
        core_count = sum(item["color"] in (PAGE, CORE) for item in kept_pages)
        actual = core_count / page_count if page_count else 0.0
        if page_count and abs(actual - average) > 1.000001:
            warnings.append(
                f"Core target {average:g} per page: {core_count} Core images over {page_count} pages "
                f"give {actual:.2f}. Available images, page limits or image minimums prevent a closer average."
            )
    return kept_pages, warnings


def propose(analysis, settings):
    """Proposals and warnings. Does not read video, audio, or a model."""
    fps = float(analysis.get("fps") or 24)
    settings = dict(settings or {})
    settings["_fps"] = fps  # gaps in seconds become frames of this timeline
    manual = [int(frame) for frame in analysis.get("manual_frames") or []]
    utterances = sorted(analysis.get("utterances") or [], key=lambda item: item["start"])
    proposals = []
    warnings = []
    last_green = None
    minimum = gap_frames(settings, "min_marker_seconds")
    green_gap = gap_frames(settings, "min_green_seconds")
    for shot in analysis.get("shots") or []:
        if setting(settings, "skip_marked_shots") and any(shot["start"] <= frame < shot["end"] for frame in manual):
            continue
        frames = [dict(frame) for frame in shot.get("frames") or []]
        if not frames:
            continue
        mark_holds(frames, setting(settings, "hold_ratio"))
        best = _shot_best(frames)
        taken = []
        cores = []
        speech_picks = []
        for utterance in utterances:
            if utterance["end"] <= shot["start"] or utterance["start"] >= shot["end"]:
                continue
            pick, kind = _pick_speech(frames, utterance, settings, best)
            if kind == "missing" and pick is None:
                inside = [frame for frame in frames if utterance["start"] <= frame["frame"] < utterance["end"]]
                if not inside:
                    warnings.append(f"Line at frame {utterance['start']} has no examined image.")
                continue
            if pick is None or _blocked(pick["frame"], taken, manual, minimum):
                continue
            speech_picks.append((pick, kind))
            taken.append(pick["frame"])
            cores.append(pick)
            if kind == "speech" and setting(settings, "keep_second_mouth"):
                second = _second_mouth(frames, utterance, pick, settings, best, taken, manual)
                if second is not None:
                    speech_picks.append((second, "speech_extra"))
                    taken.append(second["frame"])
        body = _pick_body(frames, shot, utterances, settings, best)
        body_kind = "body"
        if body is not None and not _blocked(body["frame"], taken, manual, minimum):
            taken.append(body["frame"])
            cores.append(body)
        else:
            body = None
        records = [(frame, "speech_extra" if kind == "speech_extra" else kind, EXTRA if kind == "speech_extra" else CORE)
                   for frame, kind in speech_picks]
        if body is not None:
            records.append((body, body_kind, CORE))
        if action_shot(shot, frames, settings):
            for extra in _spread(frames, shot, int(setting(settings, "action_extras")), taken, settings, cores, best, manual):
                records.append((extra, "action", EXTRA))
                taken.append(extra["frame"])
        target = body
        target_kind = body_kind if body is not None else None
        if target is None and speech_picks:
            mains = [(frame, kind) for frame, kind in speech_picks if kind != "speech_extra"]
            target, target_kind = max(mains or speech_picks, key=lambda item: item[0]["frame"])
        group = _is_group(target, settings)
        page = None
        if target is not None and (_is_scene(shot, settings) or group):
            far = last_green is None or abs(target["frame"] - last_green) >= green_gap
            if far:
                records = [(frame, kind, color) for frame, kind, color in records if frame is not target]
                records.append((target, "page", PAGE))
                page = (target, target_kind, group)
        for frame, kind, color in records:
            note = _page_note(page[1], page[2]) if page is not None and frame is page[0] else _note(kind)
            proposals.append(_proposal(
                frame, color, "page" if color == PAGE else kind, note, shot.get("cut_grey") or 0))
        greens = [proposal["frame"] for proposal in proposals if proposal["color"] == PAGE]
        if greens:
            last_green = greens[-1]
    collapsed = {}
    rank = {PAGE: 0, CORE: 1, EXTRA: 2}
    for proposal in proposals:
        current = collapsed.get(proposal["frame"])
        if current is None or rank[proposal["color"]] < rank[current["color"]]:
            collapsed[proposal["frame"]] = proposal
    ordered = [collapsed[key] for key in sorted(collapsed)]
    ordered, fit_warnings = _fit_story(ordered, settings, len(analysis.get("shots") or []),
                                       analyzed_minutes(analysis))
    ordered, trim_warnings = _trim_pages(ordered, settings)
    warnings.extend(fit_warnings)
    warnings.extend(trim_warnings)
    return {"proposals": ordered, "warnings": warnings}


def _second_mouth(frames, utterance, first, settings, best, taken, manual):
    inside = [frame for frame in frames
              if utterance["start"] <= frame["frame"] < utterance["end"] and frame["frame"] != first["frame"]]
    opens = [frame for frame in inside if mouth_state(frame, settings) == "open" and quality_ok(frame, settings, best)]
    opens = _sharp_enough(_with_interior(opens), settings)
    if not opens:
        return None
    minimum = gap_frames(settings, "min_marker_seconds")
    middle = (utterance["start"] + utterance["end"]) / 2
    first_score = _cavity(first) + _number(first, "teeth")
    ratio = float(setting(settings, "second_mouth_ratio"))
    pool = [frame for frame in opens
            if _cavity(frame) + _number(frame, "teeth") >= ratio * max(first_score, 1e-6)
            and not _blocked(frame["frame"], taken, manual, minimum)]
    if not pool:
        return None
    use_teeth = max(_cavity(frame) for frame in opens) >= 0.2
    return max(pool, key=lambda frame: _speaking_key(frame, middle, use_teeth))

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


def _personal(frame, role):
    """Rank preferences inside a pool that has already passed the hard filters."""
    return _number(frame, f"personal_{role}")


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
    if setting(settings, "require_open_mouth"):
        speaking = [frame for frame in usable
                    if _overlaps(frame, utterances) and mouth_state(frame, settings) == "open"]
        if speaking:
            # A quiet closed-mouth hold after a line must not displace a good
            # speaking pose still inside the existing end-of-shot region.
            usable = speaking
    holds = [frame for frame in usable if frame.get("hold")]
    pool = holds or usable
    if not pool:
        return None

    def score(frame):
        mouth = 1.0
        if _overlaps(frame, utterances):
            mouth = 0.35 + _number(frame, "open_mouth")
        return _expression_score(frame, settings) * mouth

    return max(pool, key=lambda frame: (_personal(frame, "core"), score(frame), frame["frame"]))


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


def _dialogue_metadata(frame, utterances):
    """Anonymous audio-turn context, never a visual character identification.

    Ambiguous overlap and explicitly uncertain labels do not grant another
    retention priority. Old analyses without speaker labels keep their rules.
    """
    number = int(frame["frame"])
    active = [line for line in utterances if line["start"] <= number < line["end"]]
    if len(active) != 1:
        return {}
    line = active[0]
    confidence = line.get("confidence")
    if confidence is not None:
        try:
            accepted = (not isinstance(confidence, bool) and isinstance(confidence, (int, float))
                        and isfinite(confidence) and 0.5 <= confidence <= 1)
        except OverflowError:
            accepted = False
        if not accepted:
            return {}
    speaker = line.get("speaker")
    named = isinstance(speaker, str) and bool(speaker.strip()) and len(speaker) <= 128
    if not named and line.get("source") != "speaker_change" and not line.get("turn_id"):
        return {}
    result = {"dialogue_turn": int(line["start"])}
    if named:
        result["dialogue_speaker"] = speaker
    return result


def _dialogue_retention(item, page):
    """Soft diversity among verified dialogue images, inside the current page."""
    if item.get("speech_quality_ok") is not True:
        return 0, 0
    speaker, turn = item.get("dialogue_speaker"), item.get("dialogue_turn")
    if not isinstance(turn, int) or isinstance(turn, bool):
        return 0, 0
    if not isinstance(speaker, str) or not speaker:
        return 0, int(sum(other.get("speech_quality_ok") is True
                          and other.get("dialogue_turn") == turn for other in page) == 1)
    same_speaker = [other for other in page if other.get("speech_quality_ok") is True
                    and other.get("dialogue_speaker") == speaker]
    return (int(len(same_speaker) == 1),
            int(sum(other.get("dialogue_turn") == turn for other in same_speaker) == 1))


def _pick_speech(frames, utterance, settings, best):
    inside = [frame for frame in frames if utterance["start"] <= frame["frame"] < utterance["end"]]
    if not inside:
        return None, "missing"
    eligible = _eligible(inside, settings) or inside
    middle = (utterance["start"] + utterance["end"]) / 2
    if not setting(settings, "require_open_mouth"):
        holds = [frame for frame in eligible if frame.get("hold")] or eligible
        pool = _sharp_enough(holds, settings)
        return max(pool, key=lambda frame: (_personal(frame, "core"), _expression_score(frame, settings),
                                            -abs(frame["frame"] - middle))), "speech_plain"

    opens = [frame for frame in eligible if mouth_state(frame, settings) == "open"]
    if opens:
        rich = _with_interior(opens)
        pool = _sharp_enough(rich, settings)
        use_teeth = max(_cavity(frame) for frame in opens) >= 0.2
        # For a known audio turn, strong interior evidence comes before a
        # personal preference for a late pose. Similar verified mouths remain
        # available for the personal quality ranker to distinguish.
        labelled_turn = bool(_dialogue_metadata(pool[0], [utterance]))
        good_cavity = max(0.2, 0.75 * max(_cavity(frame) for frame in pool))
        return max(pool, key=lambda frame: (labelled_turn and _cavity(frame) >= good_cavity,
                                            _personal(frame, "core"),
                                            _speaking_key(frame, middle, use_teeth))), "speech"
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
        best = min(pool, key=lambda frame: (-_personal(frame, "extra"), abs(frame["frame"] - point),
                                            not frame.get("hold"), -frame["sharpness"]))
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


def _proposal(frame, color, kind, note, strength=0, *, speech_quality_ok=False, dialogue=None):
    result = {
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
    if speech_quality_ok:
        # Keep semantic priority through later Page/Core reassignment, without
        # treating the permissive speech fallback as a quality-approved pose.
        result["speech_quality_ok"] = True
        result.update(dialogue or {})
    for role in ("core", "extra", "page"):
        key = f"personal_{role}"
        if key in frame:
            result[key] = float(frame[key])
    return result


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
    return (min(4.0, max(0.0, strength)) + (0.25 if item["color"] == PAGE else 0.0)
            + 8.0 * _personal(item, "page"))


def _budget_protected(item, settings):
    return int(item["frame"]) in settings.get("_budget_protected_frames", ())


def _budget_page_count(count, proposals, settings, minutes):
    """Keep compression's preference inside the page capacities of this pool."""
    if not settings.get("_budget_active") or not proposals:
        return count
    low, high = _page_limits(settings, minutes)
    cores = sum(item["color"] in (PAGE, CORE) for item in proposals)
    core_low, core_high = _bounds(settings, "core_page_min", "core_page_max")
    total_low, total_high = _bounds(settings, "total_page_min", "total_page_max")
    least = max(low, ceil(cores / max(1, core_high)), ceil(len(proposals) / max(1, total_high)))
    most = min(high, cores // max(1, core_low), len(proposals) // max(1, total_low))
    if least <= most:
        return max(least, min(count, most))
    return max(low, min(count, high))


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
    count = _budget_page_count(count, proposals, settings, minutes)
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
        if _budget_protected(item, settings):
            pass
        elif item["color"] == PAGE and int(item["frame"]) not in chosen:
            updated.update(color=CORE, name=NAMES[CORE], rule="body", note="Core")
        elif item["color"] == CORE and int(item["frame"]) in chosen:
            updated.update(color=PAGE, name=NAMES[PAGE], rule="page", note="Page start")
        fitted.append(updated)
    return fitted, warnings


def _fit_story(proposals, settings, shot_count, minutes=None):
    """Keep about as many page opens as the compression slider asks for."""
    if core_target(settings):
        return _fit_core_story(proposals, settings, shot_count, minutes)
    if settings.get("_budget_active") and any(item["color"] == PAGE for item in proposals):
        # A global pool contains several Core candidates per shot. Partition it
        # from the first Core instead of leaving an extra implicit page before
        # a late scene marker, which would evade the per-page ceilings.
        cores = sum(item["color"] in (PAGE, CORE) for item in proposals)
        if cores:
            count = target_pages(settings, shot_count, minutes)
            fitted_settings = dict(settings, core_page_target=cores / count)
            return _fit_core_story(proposals, fitted_settings, shot_count, minutes)
    greens = [proposal for proposal in proposals if proposal["color"] == PAGE]
    if len(greens) < 1:
        return proposals, []
    target = target_pages(settings, shot_count, minutes)
    target = min(max(1, int(shot_count or 1)), _budget_page_count(target, proposals, settings, minutes))
    gap = gap_frames(settings, "min_green_seconds")
    chosen = {greens[0]["frame"]}
    pool = [proposal["frame"] for proposal in greens[1:]]
    by_frame = {item["frame"]: item for item in proposals}
    while len(chosen) < target and pool and len(chosen) < len(greens):
        nxt = max(pool, key=lambda frame: (_personal(by_frame[frame], "page"),
                                           min(abs(frame - kept) for kept in chosen)))
        pool.remove(nxt)
        chosen.add(nxt)
    warnings = []
    if len(chosen) < target:
        while len(chosen) < target:
            ranked = sorted(
                (item for item in proposals if item["color"] == CORE and item["frame"] not in chosen
                 and all(abs(item["frame"] - kept) >= gap for kept in chosen)),
                key=lambda item: (_personal(item, "page"), min(abs(item["frame"] - kept) for kept in chosen),
                                  item.get("strength") or 0),
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
        if _budget_protected(proposal, settings):
            pass
        elif proposal["color"] == PAGE and proposal["frame"] not in chosen:
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
    for page in _pages(proposals, include_leading_extras=bool(core_target(settings) or settings.get("_budget_active"))):
        kept = list(page)

        def cores():
            return [item for item in kept if item["color"] in (PAGE, CORE)]

        def protected(item):
            return (_budget_protected(item, settings) or item.get("rule") == "user"
                    or bool(item.get("user_role")))

        def sacrifice(pool):
            return min(pool, key=lambda item: (setting(settings, "require_open_mouth")
                                               and item["color"] == CORE and item.get("speech_quality_ok") is True,
                                               (_dialogue_retention(item, kept)
                                                if setting(settings, "require_open_mouth") else (0, 0)),
                                               _personal(item, "extra" if item["color"] == EXTRA else "core"),
                                               _DROP.get(item["rule"], 4), item["sharpness"], item["frame"]))

        while len(cores()) > core_max:
            pool = [item for item in kept if item["color"] == CORE and not protected(item)]
            if not pool or len(cores()) - 1 < core_min:
                break
            kept.remove(sacrifice(pool))
        if soft_max is not None:
            while len(cores()) > soft_max:
                pool = [item for item in kept if item["color"] == CORE and not protected(item)]
                if not pool or len(cores()) - 1 < core_min or len(kept) - 1 < total_min:
                    break
                kept.remove(sacrifice(pool))
            if len(cores()) > soft_max:
                warnings.append(
                    f"Page at frame {kept[0]['frame']}: the image minimum keeps the Core average above its target."
                )
        while len(kept) > total_max:
            extras = [item for item in kept if item["color"] == EXTRA and not protected(item)]
            pool = extras or [item for item in kept if item["color"] == CORE and not protected(item)]
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
    warnings.extend(_core_average_warnings(kept_pages, settings))
    return kept_pages, warnings


def _core_average_warnings(proposals, settings):
    average = core_target(settings)
    page_count = sum(item["color"] == PAGE for item in proposals)
    core_count = sum(item["color"] in (PAGE, CORE) for item in proposals)
    actual = core_count / page_count if page_count else 0.0
    if average and page_count and abs(actual - average) > 1.000001:
        return [f"Core target {average:g} per page: {core_count} Core images over {page_count} pages "
                f"give {actual:.2f}. Available images, page limits or image minimums prevent a closer average."]
    return []


def _budget_candidates(shot, frames, utterances, settings, best):
    """More choices from measured frames, with the same visual hard limits."""
    candidates = {}

    def add(frame, color, kind):
        item = _proposal(frame, color, kind, _note(kind), shot.get("cut_grey") or 0,
                         speech_quality_ok=(color == CORE and setting(settings, "require_open_mouth")
                                            and _overlaps(frame, utterances)
                                            and mouth_state(frame, settings) == "open"
                                            and quality_ok(frame, settings, best)),
                         dialogue=_dialogue_metadata(frame, utterances))
        old = candidates.get(item["frame"])
        if old is None or (old["color"] == EXTRA and color == CORE):
            candidates[item["frame"]] = item

    good = [frame for frame in frames if quality_ok(frame, settings, best)]
    for utterance in utterances:
        inside = [frame for frame in good if utterance["start"] <= frame["frame"] < utterance["end"]]
        if setting(settings, "require_open_mouth"):
            # A quota never creates an unverified mouth fallback.
            pool = _sharp_enough(_with_interior([frame for frame in inside
                                               if mouth_state(frame, settings) == "open"]), settings)
            kind = "speech"
        else:
            pool = _sharp_enough([frame for frame in inside if frame.get("hold")] or inside, settings)
            kind = "speech_plain"
        for frame in pool:
            add(frame, CORE, kind)
    region = [frame for frame in _end_frames(frames, shot, settings) if quality_ok(frame, settings, best)]
    for frame in [frame for frame in region if frame.get("hold")] or region:
        add(frame, CORE, "body")
    if int(setting(settings, "action_extras")) > 0 and action_shot(shot, frames, settings):
        for frame in good:
            add(frame, EXTRA, "action")
    return list(candidates.values())


def _budget_rank(item, sources):
    role = "extra" if item["color"] == EXTRA else "core"
    source = sources.get(int(item["frame"]))
    frame = source[2] if source is not None else item
    priority = {"page": 5, "speech": 5, "speech_plain": 4, "body": 3,
                "speech_unverified": 2, "speech_extra": 1, "action": 0}.get(item.get("rule"), 3)
    if item["color"] == CORE and item.get("speech_quality_ok") is True:
        priority = max(priority, 5)
    return (priority, _personal(item, role), bool(frame.get("hold")),
            _cavity(frame) if item.get("rule") == "speech" else 0,
            _number(frame, "expression"), _number(item, "sharpness"), int(item["frame"]))


def _budget_can_add(item, proposals, manual, settings, sources, excluded):
    number = int(item["frame"])
    if number in excluded or number in manual or any(int(other["frame"]) == number for other in proposals):
        return False
    minimum = gap_frames(settings, "min_extra_seconds" if item["color"] == EXTRA else "min_marker_seconds")
    if _blocked(number, (), manual, minimum):
        return False
    source = sources.get(number)
    action_count = 0
    extra_gap = gap_frames(settings, "min_extra_seconds")
    core_gap = gap_frames(settings, "min_marker_seconds")
    for other in proposals:
        gap = extra_gap if EXTRA in (item["color"], other["color"]) else core_gap
        if abs(number - int(other["frame"])) < gap:
            return False
        other_source = sources.get(int(other["frame"]))
        if source is None or other_source is None or source[0] != other_source[0]:
            continue
        if other.get("rule") == "action":
            action_count += 1
        frame, previous = source[2], other_source[2]
        if (_alike(frame, previous, float(setting(settings, "duplicate_diff")))
                and drawing_change(frame, previous) < float(setting(settings, "action_structure"))
                and not _mouth_saves(frame, previous, settings)):
            return False
    return item.get("rule") != "action" or action_count < int(setting(settings, "action_extras"))


def _budget_initial(proposals, candidates, fixed, budget, settings, sources, manual, counted_manual, excluded):
    """Choose the editable pool before dividing it into pages."""
    from vispa_mp.marker_budget import count_markers, target_window
    chosen = [dict(item) for item in fixed]
    available = {}
    for item in list(candidates) + list(proposals):
        number = int(item["frame"])
        source = sources.get(number)
        if number in excluded or number in settings["_budget_protected_frames"]:
            continue
        if budget["span"] is not None and not budget["span"][0] <= number < budget["span"][1]:
            continue
        if source is None or not quality_ok(source[2], settings, source[1]):
            continue
        old = available.get(number)
        if (old is None or item["color"] == PAGE
                or old["color"] != PAGE and _budget_rank(item, sources) > _budget_rank(old, sources)):
            available[number] = item
    # Retain the natural story selection, then fill only when it is genuinely
    # below the soft chapter target. There is no per-minute allocation.
    lower, upper = target_window(budget)
    if count_markers(chosen, counted_manual, budget["span"]) < upper:
        for original in proposals:
            item = available.get(int(original["frame"]))
            if item is not None and _budget_can_add(item, chosen, manual, settings, sources, excluded):
                chosen.append(dict(item))
    desired = max(0, lower - len(counted_manual))
    if desired:
        page_low, _ = _page_limits(settings, budget["minutes"])
        core_low, _ = _bounds(settings, "core_page_min", "core_page_max")
        total_low, _ = _bounds(settings, "total_page_min", "total_page_max")
        # Existing page/image floors can make a smaller global quota impossible.
        desired = max(desired, page_low * max(1, core_low, total_low))
    pool = sorted(available.values(), key=lambda item: _budget_rank(item, sources), reverse=True)
    for item in pool:
        if count_markers(chosen, counted_manual, budget["span"]) - len(counted_manual) >= desired:
            break
        if _budget_can_add(item, chosen, manual, settings, sources, excluded):
            chosen.append(dict(item))
    return sorted(chosen, key=lambda item: item["frame"]), pool


def _budget_finish(proposals, candidates, budget, settings, sources, manual, counted_manual, excluded):
    """Fit the quota inside the page ceilings/floors, preserving edited markers."""
    from vispa_mp.marker_budget import count_markers, target_window
    kept = list(proposals)
    target = int(budget["target"])
    lower, upper = target_window(budget)
    core_low, core_high = _bounds(settings, "core_page_min", "core_page_max")
    total_low, total_high = _bounds(settings, "total_page_min", "total_page_max")

    def count():
        return count_markers(kept, counted_manual, budget["span"])

    removable = []
    pages = _pages(kept, include_leading_extras=bool(core_target(settings) or settings.get("_budget_active")))
    page_of = {int(item["frame"]): page for page in pages for item in page}
    for page in pages:
        core_count = sum(item["color"] in (PAGE, CORE) for item in page)
        for item in page:
            if _budget_protected(item, settings) or item["color"] == PAGE:
                continue
            if len(page) <= max(1, total_low):
                continue
            if item["color"] == CORE and core_count <= max(1, core_low):
                continue
            removable.append(item)
    while count() > upper and removable:
        def removal_key(candidate):
            current_page = page_of[int(candidate["frame"])]
            rank = _budget_rank(candidate, sources)
            retention = (_dialogue_retention(candidate, current_page)
                         if setting(settings, "require_open_mouth") else (0, 0))
            return rank[0], retention, *rank[1:]

        item = min(removable, key=removal_key)
        removable.remove(item)
        page = page_of[int(item["frame"])]
        cores = sum(other["color"] in (PAGE, CORE) for other in page)
        if len(page) <= max(1, total_low) or (item["color"] == CORE and cores <= max(1, core_low)):
            continue
        page.remove(item)
        kept.remove(item)
    # The fitted boundaries remain fixed. A later addition cannot create a page
    # or evade a Core/total ceiling that was just enforced by _trim_pages.
    for item in candidates:
        if count() >= lower:
            break
        if not _budget_can_add(item, kept, manual, settings, sources, excluded):
            continue
        pages = _pages(sorted(kept, key=lambda candidate: candidate["frame"]),
                       include_leading_extras=bool(core_target(settings) or settings.get("_budget_active")))
        if not pages:
            break
        preceding = [index for index, page in enumerate(pages) if int(page[0]["frame"]) <= int(item["frame"])]
        index = preceding[-1] if preceding else 0
        page = pages[index]
        if (not preceding and index == 0 and page[0]["color"] == PAGE
                and not (core_target(settings) or settings.get("_budget_active"))):
            # Legacy grouping treats frames before the first Page as another page.
            continue
        if len(page) >= total_high:
            continue
        if item["color"] in (PAGE, CORE) and sum(other["color"] in (PAGE, CORE) for other in page) >= core_high:
            continue
        added = dict(item)
        if added["color"] == PAGE:
            added.update(color=CORE, name=NAMES[CORE], rule="body", note="Core")
        kept.append(added)
    actual = count()
    warnings = []
    if actual < int(budget["min"]):
        warnings.append(f"Global marker minimum {budget['min']} could not be reached: {actual} markers. "
                        "Measured image quality, spacing, duplicate drawings or page/image limits stop there; no thresholds were relaxed.")
    elif actual > int(budget["max"]):
        warnings.append(f"Global marker maximum {budget['max']} could not be respected: {actual} markers. "
                        "Protected choices, manual markers or page/image minimums prevent removing more.")
    elif not lower <= actual <= upper:
        warnings.append(f"Global marker target about {target}: {actual} markers retained within {budget['min']}–{budget['max']}. "
                        "Available admissible images, protected choices, spacing or page/image limits prevent a closer target.")
    return sorted(kept, key=lambda item: item["frame"]), warnings, actual


def propose(analysis, settings, profile=None):
    """Proposals and warnings. Does not read video, audio, or a model."""
    if profile is not None:
        from vispa_mp.learning_model import apply_profile
        analysis = apply_profile(analysis, profile)
    fps = float(analysis.get("fps") or 24)
    settings = dict(settings or {})
    settings["_fps"] = fps  # gaps in seconds become frames of this timeline
    from vispa_mp.marker_budget import budget_settings, marker_frames
    budget = budget_settings(settings, analysis)
    budget_active = budget["enabled"]
    manual = [int(frame) for frame in analysis.get("manual_frames") or []]
    candidates, sources, fixed, counted_manual, excluded = [], {}, [], set(), set()
    if budget_active:
        excluded = {int(frame) for frame in analysis.get("_budget_excluded_frames") or []}
        fixed_by_frame = {int(item["frame"]): dict(item) for item in analysis.get("_budget_user_proposals") or []
                          if item.get("color") in (PAGE, CORE, EXTRA) and int(item["frame"]) not in excluded}
        fixed = list(fixed_by_frame.values())
        settings["_budget_active"] = True
        settings["_budget_protected_frames"] = set(fixed_by_frame)
        counted_manual = marker_frames((), analysis.get("_budget_manual_frames", manual), budget["span"])
    utterances = sorted(analysis.get("utterances") or [], key=lambda item: item["start"])
    proposals = []
    warnings = []
    last_green = None
    minimum = gap_frames(settings, "min_marker_seconds")
    green_gap = gap_frames(settings, "min_green_seconds")
    for shot in analysis.get("shots") or []:
        protected_start = int(shot.get("parent_start", shot["start"]))
        protected_end = int(shot.get("parent_end", shot["end"]))
        if setting(settings, "skip_marked_shots") and any(protected_start <= frame < protected_end for frame in manual):
            continue
        frames = [dict(frame) for frame in shot.get("frames") or []]
        if not frames:
            continue
        if profile is None:
            # Standard mode must also ignore scores from a previously enriched
            # analysis or imported project, rather than retaining old preferences.
            for frame in frames:
                for role in ("core", "extra", "page"):
                    frame.pop(f"personal_{role}", None)
                frame.pop("personal_extra_role", None)
        mark_holds(frames, setting(settings, "hold_ratio"))
        best = _shot_best(frames)
        if budget_active:
            for frame in frames:
                sources[int(frame["frame"])] = ((int(shot["start"]), int(shot["end"])), best, frame)
            candidates.extend(_budget_candidates(shot, frames, utterances, settings, best))
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
                frame, color, "page" if color == PAGE else kind, note, shot.get("cut_grey") or 0,
                speech_quality_ok=(color in (PAGE, CORE) and setting(settings, "require_open_mouth")
                                   and _overlaps(frame, utterances)
                                   and mouth_state(frame, settings) == "open"
                                   and quality_ok(frame, settings, best)),
                dialogue=_dialogue_metadata(frame, utterances)))
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
    if budget_active:
        ordered, candidates = _budget_initial(ordered, candidates, fixed, budget, settings, sources,
                                              manual, counted_manual, excluded)
    ordered, fit_warnings = _fit_story(ordered, settings, len(analysis.get("shots") or []),
                                       budget["minutes"] if budget_active else analyzed_minutes(analysis))
    ordered, trim_warnings = _trim_pages(ordered, settings)
    if budget_active:
        ordered, budget_warnings, actual = _budget_finish(ordered, candidates, budget, settings, sources,
                                                         manual, counted_manual, excluded)
        # The last additions can repair an underfilled page. Report its final
        # state rather than carrying stale intermediate page counts to the UI.
        trim_warnings = []
        core_low, core_high = _bounds(settings, "core_page_min", "core_page_max")
        total_low, total_high = _bounds(settings, "total_page_min", "total_page_max")
        for page in _pages(ordered, include_leading_extras=bool(core_target(settings) or settings.get("_budget_active"))):
            cores = sum(item["color"] in (PAGE, CORE) for item in page)
            if cores < core_low or len(page) < total_low:
                trim_warnings.append(f"Page at frame {page[0]['frame']}: {cores} Core images, {len(page)} in all, below the minimum.")
            elif cores > core_high or len(page) > total_high:
                trim_warnings.append(f"Page at frame {page[0]['frame']}: protected choices or image minimums keep the page above the maximum.")
        warnings.extend(budget.get("warnings") or [])
        warnings.extend(budget_warnings)
    from vispa_mp.role_refinement import refine_roles
    settings["_personal_role_assignment"] = profile is not None
    refined = refine_roles(ordered, analysis, settings)
    if any(before["color"] != after["color"] for before, after in zip(ordered, refined)):
        # Role refinement preserves the images and page boundaries. Only a soft
        # Core-average diagnostic may need its final counts refreshed.
        trim_warnings = [warning for warning in trim_warnings if not warning.startswith("Core target ")]
        average = core_target(settings)
        if average:
            core_low, core_high = _bounds(settings, "core_page_min", "core_page_max")
            soft_max = max(core_low, min(core_high, floor(average + 1)))
            resolved = {f"Page at frame {page[0]['frame']}: the image minimum keeps the Core average above its target."
                        for page in _pages(refined, include_leading_extras=True)
                        if sum(item["color"] in (PAGE, CORE) for item in page) <= soft_max}
            trim_warnings = [warning for warning in trim_warnings if warning not in resolved]
        trim_warnings.extend(_core_average_warnings(refined, settings))
    ordered = refined
    warnings.extend(fit_warnings)
    warnings.extend(trim_warnings)
    result = {"proposals": ordered, "warnings": warnings}
    if budget_active:
        result["marker_budget"] = dict(budget, actual=actual, manual_count=len(counted_manual))
    return result


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

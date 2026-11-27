"""Which frames are worth sending to the tagger.

The choice is fixed at analysis time. Later threshold changes only re-rank
frames that already have a score.
"""

from vispa_mp.preset import setting
from vispa_mp.rules import mark_holds


def _take(selected, pool, limit, kind, cap):
    if len(selected) >= cap:
        return False
    seen = {frame["frame"] for frame in selected}
    if kind == "hold":
        pool = [frame for frame in pool if frame["hold"]]
    elif kind == "cycle":
        pool = [frame for frame in pool if not frame["hold"]]
    pool = [frame for frame in pool if frame["frame"] not in seen]
    pool.sort(key=lambda frame: frame["sharpness"], reverse=True)
    for frame in pool[:limit]:
        selected.append(frame)
        if len(selected) >= cap:
            return False
    return True


def _temporal_choices(frames, start, end, count):
    """A sharp representative of each part, rather than a sharp-frame cluster.

    Mouth scores do not exist until after this sampling. Covering a reply's
    duration gives its different mouth poses a chance to reach recognition.
    """
    if count <= 0 or not frames:
        return []
    count = min(count, len(frames))
    span = max(1, end - start)
    buckets = [[] for _ in range(count)]
    for frame in frames:
        index = min(count - 1, max(0, int((frame["frame"] - start) * count / span)))
        buckets[index].append(frame)
    chosen = []
    for index, pool in enumerate(buckets):
        if pool:
            middle = start + (index + 0.5) * span / count
            chosen.append(max(pool, key=lambda frame: (frame["sharpness"],
                                                       -abs(frame["frame"] - middle), -frame["frame"])))
    seen = {frame["frame"] for frame in chosen}
    while len(chosen) < count:
        remaining = [frame for frame in frames if frame["frame"] not in seen]
        if not remaining:
            break
        item = max(remaining, key=lambda frame: (min(abs(frame["frame"] - other["frame"]) for other in chosen),
                                                  frame["sharpness"], -frame["frame"]))
        chosen.append(item)
        seen.add(item["frame"])
    return chosen


def _turn_choices(frames, start, end, per_line):
    """An ordered queue with held and moving drawings across one reply."""
    holds = _temporal_choices([frame for frame in frames if frame["hold"]], start, end, per_line)
    cycles = _temporal_choices([frame for frame in frames if not frame["hold"]], start, end, per_line)
    if not holds and not cycles:
        return []
    middle = (start + end) / 2
    # The first pass represents the turn near its centre. Extra passes cover
    # more of the reply, alternating held and moving animation when available.
    first = min(holds or cycles, key=lambda frame: (abs(frame["frame"] - middle),
                                                  -frame["sharpness"], frame["frame"]))
    chosen = [first]
    holds = [frame for frame in holds if frame["frame"] != first["frame"]]
    cycles = [frame for frame in cycles if frame["frame"] != first["frame"]]
    pools = [cycles, holds]
    while any(pools):
        for pool in pools:
            if not pool:
                continue
            item = max(pool, key=lambda frame: (min(abs(frame["frame"] - other["frame"]) for other in chosen),
                                                 frame["sharpness"], -frame["frame"]))
            pool.remove(item)
            chosen.append(item)
    return chosen


def _dialogue_candidates(selected, frames, shot, utterances, per_line, cap):
    if per_line <= 0 or len(selected) >= cap:
        return
    turns = []
    for utterance in sorted(utterances, key=lambda item: (item["start"], item["end"])):
        start, end = max(shot["start"], utterance["start"]), min(shot["end"], utterance["end"])
        if end <= start:
            continue
        inside = [frame for frame in frames if start <= frame["frame"] < end]
        if inside:
            turns.append((start, end, _turn_choices(inside, start, end, per_line)))
    seen = {frame["frame"] for frame in selected}
    # Reserve coverage before a long early reply can consume the full cap.
    while len(selected) < cap:
        uncovered = [turn for turn in turns if not any(turn[0] <= number < turn[1] for number in seen)]
        if not uncovered:
            break
        turn = max(uncovered, key=lambda item: (
            min((abs((item[0] + item[1]) / 2 - number) for number in seen), default=float("inf")),
            -item[0], -item[1]))
        frame = turn[2][0]
        selected.append(frame)
        seen.add(frame["frame"])
    # Fair extra coverage: each reply gets one new choice before another round.
    while len(selected) < cap:
        added = False
        for _start, _end, queue in turns:
            frame = next((item for item in queue if item["frame"] not in seen), None)
            if frame is None:
                continue
            selected.append(frame)
            seen.add(frame["frame"])
            added = True
            if len(selected) >= cap:
                break
        if not added:
            break


def _spread(frames, start, end, count):
    holds = [frame for frame in frames if frame["hold"]] or list(frames)
    if count <= 0 or end <= start or not holds:
        return []
    points = [start + (index + 1) * (end - start) / (count + 1) for index in range(count)]
    chosen, used = [], set()
    for point in points:
        pool = [frame for frame in holds if frame["frame"] not in used]
        if not pool:
            break
        best = min(pool, key=lambda frame: (abs(frame["frame"] - point), -frame["sharpness"]))
        chosen.append(best)
        used.add(best["frame"])
    return chosen


def candidate_frames(shot, utterances, settings):
    """End of shot, fair dialogue-turn coverage, then a spread for action."""
    frames = [dict(frame) for frame in shot.get("frames") or []]
    if not frames:
        return []
    mark_holds(frames, setting(settings, "hold_ratio"))
    frames.sort(key=lambda frame: frame["frame"])
    cap = int(setting(settings, "max_tagged_per_shot"))
    if cap <= 0:
        return []
    per_line = int(setting(settings, "candidates_per_line"))
    selected = []
    span = max(1, shot["end"] - shot["start"])
    cut = shot["start"] + (1 - float(setting(settings, "end_fraction"))) * span
    end_frames = [frame for frame in frames if frame["frame"] >= cut] or frames[-1:]
    _take(selected, end_frames, 1, "hold" if any(frame["hold"] for frame in end_frames) else "cycle", cap)
    _dialogue_candidates(selected, frames, shot, utterances, per_line, cap)
    if len(selected) < cap:
        _take(selected, end_frames, 3, "hold", cap)
    if len(selected) < cap:
        for frame in _spread(frames, shot["start"], shot["end"], int(setting(settings, "spread_tagged"))):
            if frame["frame"] in {item["frame"] for item in selected}:
                continue
            selected.append(frame)
            if len(selected) >= cap:
                break
    selected.sort(key=lambda frame: frame["frame"])
    return selected

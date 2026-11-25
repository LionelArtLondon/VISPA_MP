"""Which frames are worth sending to the tagger.

The choice is fixed at analysis time. Later threshold changes only re-rank
frames that already have a score.
"""

from vispa_mp.preset import setting
from vispa_mp.rules import mark_holds


def _take(selected, pool, limit, kind, cap):
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
    """Tagged frames for one shot: end of shot, each line, and a spread for action."""
    frames = [dict(frame) for frame in shot.get("frames") or []]
    if not frames:
        return []
    mark_holds(frames, setting(settings, "hold_ratio"))
    frames.sort(key=lambda frame: frame["frame"])
    cap = int(setting(settings, "max_tagged_per_shot"))
    per_line = int(setting(settings, "candidates_per_line"))
    selected = []
    span = max(1, shot["end"] - shot["start"])
    cut = shot["start"] + (1 - float(setting(settings, "end_fraction"))) * span
    end_frames = [frame for frame in frames if frame["frame"] >= cut] or frames[-1:]
    _take(selected, end_frames, 1, "hold", cap)
    for utterance in utterances:
        if utterance["end"] <= shot["start"] or utterance["start"] >= shot["end"]:
            continue
        inside = [frame for frame in frames if utterance["start"] <= frame["frame"] < utterance["end"]]
        if not _take(selected, inside, per_line, "hold", cap):
            break
        if not _take(selected, inside, per_line, "cycle", cap):
            break
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

"""Find sustained reframings inside a long, uncut shot.

This runs on every-frame measurements before candidate sampling. It compares
small spatial signatures over time, so a slow camera move can be noticed even
when no pair of consecutive pictures looks like a hard cut.
"""

from bisect import bisect_left
from math import ceil

import numpy as np

from vispa_mp.preset import setting

SAMPLE_SECONDS = 0.10
MIN_PART_SECONDS = 0.75
CONFIRM_SECONDS = 0.40


def _different(first, second):
    delta = second - first
    brightness = float(delta.mean())
    # Local animation (a mouth or blink) must not become a new camera framing.
    spatial = delta - brightness
    first_shape = (first - first.mean()) / (first.std() + 8.0)
    second_shape = (second - second.mean()) / (second.std() + 8.0)
    reframed = (float(np.abs(first_shape - second_shape).mean()) >= 0.42
                and float(np.abs(delta).mean()) >= 10.0
                and float((np.abs(spatial) >= 12.0).mean()) >= 0.30)
    relit = (abs(brightness) >= 24.0
             and float((np.sign(brightness) * delta >= 12.0).mean()) >= 0.65)
    return reframed or relit


def decompose_shot(shot, fps, settings=None, cancel=None):
    """A shot or its contiguous subshots; a duration alone never forces a split.

    The first fragment keeps the real cut's scene evidence. Later fragments
    record reframing without claiming another scene. Original bounds keep the
    user's skip-marked-shot protection intact across all fragments.
    """
    if (not setting(settings, "split_long_shots")
            or (shot["end"] - shot["start"]) / fps <= float(setting(settings, "long_shot_seconds"))):
        return [shot]
    frames = shot.get("frames") or []
    if not frames or any(len(frame.get("signature") or []) != 64 for frame in frames):
        return [shot]
    samples = []
    step = max(1, int(round(fps * SAMPLE_SECONDS)))
    for frame in frames:
        if not samples or frame["frame"] - samples[-1]["frame"] >= step:
            samples.append(frame)
    if len(samples) < 3:
        return [shot]
    values = np.asarray([frame["signature"] for frame in samples], dtype=np.float32)
    # A brief flash should not survive as a new layout. Keep source data intact.
    smooth = np.stack([np.median(values[max(0, i - 1):min(len(values), i + 2)], axis=0)
                       for i in range(len(values))])
    times = [frame["frame"] for frame in samples]
    minimum = max(1, int(ceil(fps * MIN_PART_SECONDS)))
    confirm = max(1, int(ceil(fps * CONFIRM_SECONDS)))
    boundaries = [int(shot["start"])]
    anchor = smooth[0]
    for index, (number, signature) in enumerate(zip(times, smooth)):
        if cancel is not None and cancel():
            raise InterruptedError("Shot search was stopped.")
        if number - boundaries[-1] < minimum or shot["end"] - number < minimum:
            continue
        if not _different(anchor, signature):
            continue
        end = bisect_left(times, number + confirm)
        if end >= len(times):
            continue
        future = smooth[index:end + 1]
        # A different image must persist. Large ongoing fluctuations are action
        # or a transition, rather than a settled new framing to use as a panel.
        if not all(_different(anchor, item) for item in future):
            continue
        shape = (future - future.mean(axis=1, keepdims=True)) / (future.std(axis=1, keepdims=True) + 8.0)
        if (float(np.abs(shape - shape[0]).mean(axis=1).max()) > 0.25
                or float(np.ptp(future.mean(axis=1))) > 10.0):
            continue
        boundaries.append(int(number))
        anchor = np.median(future, axis=0)
    if len(boundaries) == 1:
        return [shot]
    boundaries.append(int(shot["end"]))
    parts = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        part = dict(shot)
        part.update(start=start, end=end, parent_start=int(shot["start"]), parent_end=int(shot["end"]))
        part["frames"] = [frame for frame in frames if start <= frame["frame"] < end]
        if not part["frames"]:
            continue
        part["motion"] = sum(float(frame.get("neighbor") or 0) for frame in part["frames"]) / len(part["frames"])
        if index:
            part.update(opening=False, cut_grey=0.0, cut_colour=0.0, cut_shape=0.0, reframed=True)
        parts.append(part)
    return parts

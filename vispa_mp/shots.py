"""Shot cuts from the measure already tuned on these episodes.

The decision is the one in VISPA Cue's ``shot_cuts.py`` (grey, colour, shape,
a shot shorter than 0.2 s is merged). Cue itself is not imported.
"""

from statistics import median

import numpy as np

METHOD = dict(name="frame_difference", version=3, size=[64, 36], grey=[12.0, 3.5], colours=[0.2, 3.0],
              shapes=[0.35, 4.0], window=12, min_shot_us=200_000)
WINDOW = METHOD["window"]
MIN_SHOT = METHOD["min_shot_us"]
WIDTH, HEIGHT = METHOD["size"]


def grey_of(picture):
    image = np.asarray(picture, dtype=np.float32)
    if image.ndim == 2:
        return image
    return image @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def measures(picture):
    """(grey, colour histogram, contrast-normalised shape) of one small RGB frame."""
    picture = np.asarray(picture, dtype=np.float32)
    grey = grey_of(picture)
    colour = picture if picture.ndim == 3 else picture[..., None].repeat(3, axis=2)
    bins = np.clip(colour.astype(np.int32) >> 4, 0, 15)
    histogram = np.concatenate([np.bincount(bins[..., channel].ravel(), minlength=16) for channel in range(3)]).astype(np.float32)
    histogram /= max(1.0, float(histogram.sum()))
    shapes = (grey - grey.mean()) / (grey.std() + 8.0)
    return grey, histogram, shapes


def _changes(previous, now):
    return (float(np.mean(np.abs(now[0] - previous[0]))),
            0.5 * float(np.abs(now[1] - previous[1]).sum()),
            float(np.mean(np.abs(now[2] - previous[2]))))


def _is_cut(changes, recent):
    (grey_level, grey_ratio), (colour_level, colour_ratio), (shape_level, shape_ratio) = (
        METHOD["grey"], METHOD["colours"], METHOD["shapes"])
    usual = [median(values) if values else 0.0 for values in recent]
    return ((changes[0] >= grey_level and changes[0] >= grey_ratio * max(usual[0], 1.5))
            or (changes[1] >= colour_level and changes[1] >= colour_ratio * max(usual[1], 0.02))
            or (changes[2] >= shape_level and changes[2] >= shape_ratio * max(usual[2], 0.03)))


def cut_records(frames, cancel=None, report=None):
    """One record per accepted cut: index, time_us, grey, colour, shape.

    ``frames`` is ``(time µs, small RGB picture)`` in order. ``index`` is that order.
    """
    records, last_cut, previous = [], None, None
    recent = ([], [], [])
    total = max(1, len(frames))
    for index, (time_us, picture) in enumerate(frames):
        if cancel is not None and cancel():
            raise InterruptedError("Shot search was stopped.")
        if report is not None and index % 250 == 0:
            report(index / total)
        now = measures(picture)
        if previous is not None:
            changes = _changes(previous, now)
            if _is_cut(changes, recent):
                if last_cut is None or time_us - last_cut >= MIN_SHOT:
                    records.append({"index": index, "time_us": int(time_us), "grey": changes[0],
                                    "colour": changes[1], "shape": changes[2]})
                    last_cut = time_us
                recent = ([], [], [])
            else:
                for values, change in zip(recent, changes):
                    values.append(change)
                    del values[:-WINDOW]
        previous = now
    return records


def find_cuts(frames, cancel=None):
    """Times in µs of the first frame of each new shot. Same cuts as Cue."""
    return [record["time_us"] for record in cut_records(frames, cancel)]


def sharpness_of(picture):
    """Variance of a Laplacian, on the small frame used for the cuts."""
    grey = grey_of(picture)
    if grey.shape[0] < 3 or grey.shape[1] < 3:
        return 0.0
    center = grey[1:-1, 1:-1]
    lap = grey[:-2, 1:-1] + grey[2:, 1:-1] + grey[1:-1, :-2] + grey[1:-1, 2:] - 4.0 * center
    return float(lap.var())


def signature_of(picture):
    """8×8 block means, so two almost identical holds can be told apart from a new picture."""
    grey = grey_of(picture)
    height, width = grey.shape
    values = []
    for y in range(8):
        for x in range(8):
            block = grey[int(y * height / 8):int((y + 1) * height / 8), int(x * width / 8):int((x + 1) * width / 8)]
            values.append(round(float(block.mean()) if block.size else 0.0, 2))
    return values


def grey_diff(left, right):
    return float(np.mean(np.abs(grey_of(left) - grey_of(right))))


def picture_change(left, right):
    return _changes(measures(left), measures(right))


def _map_index(clip, index, timeline_fps):
    source_fps = float(clip.get("fps") or timeline_fps)
    return int(round(clip["start"] + index * float(timeline_fps) / source_fps))


def _describe(pictures, timeline_frames, media, source_start):
    greys = [grey_of(picture) for picture in pictures]
    described = []
    count = len(pictures)
    for index, picture in enumerate(pictures):
        if count == 1:
            neighbor = 0.0
        elif index == 0:
            neighbor = float(np.mean(np.abs(greys[0] - greys[1])))
        elif index == count - 1:
            neighbor = float(np.mean(np.abs(greys[index] - greys[index - 1])))
        else:
            neighbor = min(float(np.mean(np.abs(greys[index] - greys[index - 1]))),
                           float(np.mean(np.abs(greys[index] - greys[index + 1]))))
        described.append({
            "frame": int(timeline_frames[index]),
            "source_frame": int(source_start) + index,
            "media": media,
            "sharpness": round(sharpness_of(picture), 4),
            "neighbor": round(neighbor, 4),
            "signature": signature_of(picture),
        })
    return _collapse_frames(described)


def _collapse_frames(frames):
    """Two source frames that land on one timeline frame keep the sharper one."""
    by_frame = {}
    for frame in frames:
        current = by_frame.get(frame["frame"])
        if current is None or frame["sharpness"] > current["sharpness"]:
            by_frame[frame["frame"]] = frame
    return [by_frame[key] for key in sorted(by_frame)]


def build_shots(clips, strips, timeline_fps, cancel=None, report=None):
    """Shots on video 1. A clip edge is a cut; a long clip is also cut inside.

    ``strips[i]`` is the RGB filmstrip of ``clips[i]``, one picture per source frame
    from ``source_start`` inclusive.
    """
    shots = []
    previous = None
    first = True
    count = max(1, len(clips))
    for number, (clip, strip) in enumerate(zip(clips, strips)):
        part = None if report is None else (lambda fraction, number=number: report((number + fraction) / count))
        pictures = np.asarray(strip)
        if pictures.size == 0:
            continue
        source_fps = float(clip.get("fps") or timeline_fps)
        frame_us = max(1, int(round(1_000_000 / source_fps)))
        timed = [(index * frame_us, pictures[index]) for index in range(len(pictures))]
        records = {record["index"]: record for record in cut_records(timed, cancel, part)}
        boundaries = [0] + sorted(records) + [len(pictures)]
        for start_index, end_index in zip(boundaries, boundaries[1:]):
            if end_index <= start_index:
                continue
            piece = pictures[start_index:end_index]
            if start_index == 0 and previous is not None:
                grey, colour, shape = picture_change(previous, piece[0])
                opening = False
            elif start_index == 0 and first:
                grey, colour, shape = 0.0, 0.0, 0.0
                opening = True
            else:
                record = records[start_index]
                grey, colour, shape = record["grey"], record["colour"], record["shape"]
                opening = False
            timeline_frames = [_map_index(clip, index, timeline_fps) for index in range(start_index, end_index)]
            frames = _describe(piece, timeline_frames, clip.get("path") or "", int(clip.get("source_start") or 0) + start_index)
            if not frames:
                continue
            shot_start = _map_index(clip, start_index, timeline_fps)
            shot_end = clip["end"] if end_index >= len(pictures) else _map_index(clip, end_index, timeline_fps)
            if shot_end <= shot_start:
                shot_end = shot_start + 1
            neighbors = [frame["neighbor"] for frame in frames]
            shots.append({
                "start": int(shot_start),
                "end": int(shot_end),
                "opening": opening,
                "cut_grey": round(float(grey), 4),
                "cut_colour": round(float(colour), 4),
                "cut_shape": round(float(shape), 4),
                "motion": round(float(sum(neighbors) / len(neighbors)), 4),
                "frames": frames,
            })
            previous = piece[-1]
            first = False
    return shots

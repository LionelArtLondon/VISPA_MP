"""Exact local Video 1 stills for a position requested in the timeline review.

This backend reads the original source snapshot and existing analysis. It never
contacts Resolve, edits those inputs, or loads image-recognition models.
"""

from copy import deepcopy
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image

from vispa_mp.frames import extract_stills
from vispa_mp.shots import HEIGHT, WIDTH, sharpness_of, signature_of
from vispa_mp.snapshot import source_in_file_frames


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _rate(value, description):
    if isinstance(value, bool):
        raise ValueError(f"The {description} frame rate cannot be verified for exact capture.")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"The {description} frame rate cannot be verified for exact capture.") from error
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"The {description} frame rate cannot be verified for exact capture.")
    return value


def _interval(start, end, description):
    if not _integer(start) or not _integer(end) or end <= start:
        raise ValueError(f"The {description} range cannot be verified for exact capture.")
    return start, end


def _cancelled(cancel):
    if cancel is not None and cancel():
        raise InterruptedError("The image capture was stopped.")


def _normal_speed(value):
    if value is None or value == "":
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, str):
        value = value.strip().removesuffix("%")
    try:
        speed = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(speed) and (abs(speed - 1.0) < 1e-6 or abs(speed - 100.0) < 1e-6)


def _media_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _picture(path):
    if not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
        raise ValueError("The captured still has no image file.")
    with Image.open(path) as image:
        if image.width <= 0 or image.height <= 0 or image.width * image.height > 16_777_216:
            raise ValueError("The captured still has invalid dimensions.")
        return np.asarray(image.convert("RGB").resize((WIDTH, HEIGHT), Image.Resampling.BILINEAR)).copy()


def _capture_context(snapshot, analysis, frame):
    if (not isinstance(snapshot, dict) or not isinstance(analysis, dict)
            or not _integer(frame) or not -(2 ** 31) <= frame < 2 ** 31):
        raise ValueError("Choose an integer timeline frame in an analyzed Video 1 clip.")
    fps = _rate(snapshot.get("fps"), "timeline")
    base = analysis.get("timebase") or {}
    if not isinstance(base, dict):
        raise ValueError("The analyzed timeline timebase cannot be verified for exact capture.")
    analysis_fps = _rate(analysis.get("fps", base.get("fps")), "analysis")
    if abs(fps - analysis_fps) > 0.001:
        raise ValueError("The analyzed and source timeline frame rates differ. Read the timeline and Analyze again.")
    lower, upper = _interval(snapshot.get("start_frame"), snapshot.get("end_frame"), "timeline")
    for name in ("timeline_range", "range"):
        span = analysis.get(name)
        if span is not None:
            if not isinstance(span, (list, tuple)) or len(span) != 2:
                raise ValueError("The analyzed range cannot be verified for exact capture.")
            start, end = _interval(*span, "analyzed")
            lower, upper = max(lower, start), min(upper, end)
    if not lower <= frame < upper:
        raise ValueError("The requested frame is outside the analyzed range. Analyze that part of the timeline first.")
    clips = []
    for clip in snapshot.get("video_clips") or []:
        if not isinstance(clip, dict):
            raise ValueError("A Video 1 source clip cannot be located for exact capture.")
        start, end = _interval(clip.get("start"), clip.get("end"), "Video 1 clip")
        if start <= frame < end:
            clips.append(clip)
    if len(clips) != 1:
        detail = "overlapping Video 1 clips or a transition" if clips else "a gap or missing Video 1 clip"
        raise ValueError(f"The requested frame falls on {detail}; an exact source image cannot be captured.")
    clip = clips[0]
    if not _normal_speed(clip.get("speed")):
        raise ValueError("Retimed Video 1 clips cannot provide an exact capture. Use a normal-speed source clip.")
    source_fps = _rate(clip.get("fps") if clip.get("fps") is not None else fps, "source video")
    source_start, source_end = _interval(clip.get("source_start"), clip.get("source_end"), "source In/Out")
    if source_start < 0:
        raise ValueError("The source In/Out range cannot be verified for exact capture.")
    clip = source_in_file_frames(clip, fps)
    source_start, source_end = _interval(clip.get("source_start"), clip.get("source_end"), "source In/Out")
    expected = (clip["end"] - clip["start"]) * source_fps / fps
    if abs((source_end - source_start) - expected) > 2:
        raise ValueError("The Video 1 clip has a retimed or inconsistent source span; exact capture is unavailable.")
    media = clip.get("path")
    if not isinstance(media, (str, os.PathLike)) or not os.fspath(media) or not Path(media).is_file():
        raise ValueError(f"Video 1 source media is offline or missing: {media or '(no source file)'}. Relink it before capturing.")
    media = str(Path(media).resolve())
    shots = [shot for shot in analysis.get("shots") or []
             if isinstance(shot, dict) and _integer(shot.get("start")) and _integer(shot.get("end"))
             and shot["start"] <= frame < shot["end"]]
    if len(shots) != 1:
        raise ValueError("The requested frame has no unambiguous analyzed shot. Analyze that part of Video 1 first.")
    shot = shots[0]
    lower = max(lower, clip["start"], shot["start"])
    upper = min(upper, clip["end"], shot["end"])
    # Do not offer a neighbour across a nearby overlapping clip or transition.
    for other in snapshot.get("video_clips") or []:
        if other["end"] <= frame:
            lower = max(lower, other["end"])
        elif other["start"] > frame:
            upper = min(upper, other["start"])
    return clip, media, fps, source_fps, source_start, source_end, lower, upper, shot


def capture_timeline_candidates(snapshot, analysis, frame, cache, binary=None, cancel=None):
    """Return the exact requested frame and at most four nearby source stills.

    Neighbours are approximately 0.5/1 second away, confined to this source clip,
    analyzed shot and analyzed range. Timeline positions use the file picture
    held at that instant (floor), including an interlaced picture's second field.
    Only normal-speed source mappings are accepted; ambiguous mappings fail.
    """
    _cancelled(cancel)
    clip, media, fps, source_fps, source_start, source_end, lower, upper, shot = _capture_context(
        snapshot, analysis, frame)

    def source_of(number):
        return source_start + math.floor((number - clip["start"]) * source_fps / fps + 1e-9)

    exact_source = source_of(frame)
    if not source_start <= exact_source < source_end:
        raise ValueError("The exact requested image is outside the clip's verified source In/Out range.")
    offsets = {0, -max(1, round(fps / 2)), max(1, round(fps / 2)), -max(1, round(fps)), max(1, round(fps))}
    positions = {max(lower, min(upper - 1, frame + offset)) for offset in offsets}
    # Retain the exact timeline position when two fields show the same picture.
    selected = {exact_source: frame}
    for number in sorted(positions):
        source = source_of(number)
        if source_start <= source < source_end:
            selected.setdefault(source, number)
    cached = {}
    for candidate in shot.get("frames") or []:
        if (not isinstance(candidate, dict) or not _integer(candidate.get("source_frame"))
                or candidate["source_frame"] not in selected or not isinstance(candidate.get("media"), str)
                or _media_key(candidate["media"]) != _media_key(media) or not candidate.get("image")):
            continue
        _cancelled(cancel)
        try:
            _picture(candidate["image"])
        except (OSError, ValueError, TypeError, Image.DecompressionBombError):
            continue
        cached.setdefault(candidate["source_frame"], candidate)
    candidates, pending = [], []
    for source, number in sorted(selected.items(), key=lambda pair: pair[1]):
        candidate = deepcopy(cached.get(source) or {})
        candidate.update(frame=number, source_frame=source, media=media)
        candidates.append(candidate)
        if source not in cached:
            pending.append(candidate)
    _cancelled(cancel)
    if pending:
        try:
            extract_stills(pending, Path(cache) / "timeline-capture", binary=binary, cancel=cancel)
        except InterruptedError:
            raise
        except (OSError, RuntimeError, ValueError) as error:
            raise RuntimeError(f"The exact Video 1 image at frame {frame} could not be captured: {error}") from error
    for candidate in candidates:
        _cancelled(cancel)
        try:
            picture = _picture(candidate.get("image"))
        except (OSError, ValueError, TypeError, Image.DecompressionBombError) as error:
            raise RuntimeError(f"The exact Video 1 image at frame {candidate['frame']} is missing or unreadable.") from error
        candidate.setdefault("sharpness", round(sharpness_of(picture), 4))
        candidate.setdefault("signature", signature_of(picture))
        for key in ("neighbor", "open_mouth", "closed_mouth", "motion_blur", "from_behind", "group", "solo",
                    "face", "expression", "cavity", "mouth", "teeth", "strength"):
            candidate.setdefault(key, 0.0)
    return candidates

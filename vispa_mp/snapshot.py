"""What Resolve sent about the timeline, made consistent before anything uses it.

An interlaced timeline (25i) counts fields through the scripting API: 50 per
second, while its timecode and its pictures run at 25. Resolve may also give
a clip's position in its file in those timeline units rather than in the
file's own frames.
"""

import math

# The VISPA_MP script that reads interlacing and the playback rate.
SCRIPT_VERSION = 2
OLD_SCRIPT = ("The VISPA_MP script running in Resolve is an older version. Run Workspace > Scripts > "
              "VISPA_MP again, so VISPA MP reads interlaced timelines correctly.")


def _same_rate(left, right):
    return abs(float(left) - float(right)) < 0.01


def timecode_fps(snapshot):
    """The rate of the timecode Resolve shows: the playback rate on an interlaced timeline."""
    fps = float(snapshot.get("fps") or 24)
    shown = snapshot.get("playback_fps")
    if snapshot.get("interlaced") and shown and float(shown) > 0:
        return float(shown)
    return fps


def source_in_file_frames(clip, fps):
    """The clip's position in its file, in the file's own frames.

    When the file's rate differs from the timeline's and the reported source span
    equals the timeline span, Resolve counted in timeline units: convert them.
    """
    clip = dict(clip)
    file_fps = float(clip.get("fps") or fps)
    start, end = clip.get("source_start"), clip.get("source_end")
    span = int(clip.get("end") or 0) - int(clip.get("start") or 0)
    if file_fps <= 0 or _same_rate(file_fps, fps) or start is None or end is None or span <= 0:
        return clip
    given = int(end) - int(start)
    expected = span * file_fps / float(fps)
    if abs(given - span) <= 1 and abs(given - expected) > 1:
        ratio = file_fps / float(fps)
        # The start is the picture holding that field, the end takes the picture it falls in.
        clip["source_start"] = int(math.floor(int(start) * ratio + 1e-9))
        clip["source_end"] = int(math.ceil(int(end) * ratio - 1e-9))
    return clip


def describe_rate(snapshot):
    """'25i (50 fields) · video 25 fps' for the footer."""
    fps = float(snapshot.get("fps") or 24)
    shown = float(snapshot.get("timecode_fps") or timecode_fps(snapshot))
    text = f"{shown:g}i ({fps:g} fields)" if snapshot.get("interlaced") else f"{fps:g} fps"
    rates = sorted({float(clip["fps"]) for clip in snapshot.get("video_clips") or [] if clip.get("fps")})
    if rates:
        text += " · video " + ", ".join(f"{rate:g}" for rate in rates) + " fps"
    return text


def normalize(snapshot):
    """A copy with ``timecode_fps``, source positions in file frames, and rate warnings."""
    result = dict(snapshot)
    fps = float(result.get("fps") or 24)
    shown = timecode_fps(result)
    result["timecode_fps"] = shown
    warnings = list(result.get("warnings") or [])
    current = int(result.get("script_version") or 1) >= SCRIPT_VERSION
    if not current:
        warnings.append(OLD_SCRIPT)
    for key in ("video_clips", "audio_clips"):
        result[key] = [source_in_file_frames(clip, fps) for clip in result.get(key) or []]
    # An older script does not say whether the timeline is interlaced: 25 against 50 proves nothing.
    for rate in sorted({float(clip["fps"]) for clip in result["video_clips"] if clip.get("fps")} if current else ()):
        if not _same_rate(rate, shown):
            warnings.append(
                f"Video 1 runs at {rate:g} fps and the timeline at {shown:g}: Resolve repeats or skips "
                "pictures, so a marker can land on a picture that is not in the file.")
    result["warnings"] = warnings
    return result

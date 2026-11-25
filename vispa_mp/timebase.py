"""Timeline frames and the timecode Resolve shows."""


def parse_fps(raw):
    """A Resolve frame-rate setting as a float, or None when it is empty."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw:
        return float(raw)
    text = str(raw or "").strip()
    if not text:
        return None
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        return float(numerator) / float(denominator)
    return float(text)


def nominal_fps(fps):
    """Timecode counts 24 frames at 23.976, 30 at 29.97."""
    return max(1, int(round(float(fps))))


def parse_timecode(text, fps):
    """Frames from 00:00:00:00 for a non-drop or drop display."""
    raw = str(text or "00:00:00:00").strip()
    drop = ";" in raw
    parts = raw.replace(";", ":").split(":")
    if len(parts) != 4:
        raise ValueError(f"Unreadable timecode: {text}")
    hours, minutes, seconds, frames = (int(part) for part in parts)
    rate = nominal_fps(fps)
    if drop and rate in (30, 60):
        return _drop_to_frames(hours, minutes, seconds, frames, rate), True
    total = ((hours * 3600 + minutes * 60 + seconds) * rate) + frames
    return total, drop


def _drop_to_frames(hours, minutes, seconds, frames, rate):
    """SMPTE drop-frame to a real frame count. rate is 30 or 60."""
    drop = 2 if rate == 30 else 4
    total_minutes = hours * 60 + minutes
    frames_per_hour = rate * 3600
    frames_per_minute = rate * 60
    dropped = drop * (total_minutes - total_minutes // 10)
    return (hours * frames_per_hour + minutes * frames_per_minute + seconds * rate + frames - dropped)


def format_timecode(frame, timebase):
    """The display timecode of one timeline frame.

    ``timecode_fps`` is the rate Resolve's timecode counts. On an interlaced
    timeline it is half of ``fps``: two timeline units (fields) per picture.
    """
    fps = float(timebase["fps"])
    shown = float(timebase.get("timecode_fps") or fps)
    per_picture = fps / shown if shown > 0 else 1.0
    rate = nominal_fps(shown)
    origin, origin_drop = parse_timecode(timebase.get("start_timecode") or "00:00:00:00", shown)
    drop = bool(timebase.get("drop", origin_drop))
    offset = int(frame) - int(timebase.get("start_frame") or 0)
    absolute = origin + int(offset // per_picture)
    if absolute < 0:
        absolute = 0
    separator = ";" if drop else ":"
    if drop and rate in (30, 60):
        hours, minutes, seconds, frames = _frames_to_drop(absolute, rate)
    else:
        frames = absolute % rate
        seconds_total = absolute // rate
        seconds = seconds_total % 60
        minutes_total = seconds_total // 60
        minutes = minutes_total % 60
        hours = minutes_total // 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{frames:02d}"


def _frames_to_drop(absolute, rate):
    drop = 2 if rate == 30 else 4
    frames_per_minute = rate * 60 - drop
    frames_per_ten = rate * 60 * 10 - drop * 9
    ten, within = divmod(absolute, frames_per_ten)
    if within < rate * 60:
        minute_in_ten, frame_in_minute = 0, within
    else:
        minute_in_ten, frame_in_minute = divmod(within - drop, frames_per_minute)
        frame_in_minute += drop
    minutes_total = ten * 10 + minute_in_ten
    hours, minutes = divmod(minutes_total, 60)
    seconds, frames = divmod(frame_in_minute, rate)
    return hours, minutes, seconds, frames


def absolute_mark(value, start_frame):
    """Resolve's in/out is sometimes counted from the timeline start."""
    if value is None or value == "":
        return None
    number = int(value)
    start = int(start_frame or 0)
    if start and number < start:
        return start + number
    return number

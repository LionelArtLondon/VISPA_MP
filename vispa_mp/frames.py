"""Filmstrip and stills read with ffmpeg, then kept on disk."""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from vispa_mp.shots import HEIGHT, WIDTH

ROOT = Path(__file__).resolve().parents[1]


def ffmpeg_path():
    """The ffmpeg binary: an override, the copy in tools/, PATH, then a local install."""
    candidates = [
        os.environ.get("VISPA_MP_FFMPEG"),
        os.environ.get("FFMPEG"),
        str(ROOT / "tools" / "ffmpeg" / "ffmpeg.exe"),
        shutil.which("ffmpeg"),
        r"C:\Program Files\Topaz Labs LLC\Topaz Video AI\ffmpeg.exe",
        r"C:\Program Files\EaseUS\EaseUS Data Recovery Wizard\VideoViewer\ffmpeg.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError("ffmpeg was not found. Download the tools, or put ffmpeg.exe in tools/ffmpeg.")


def _key(path, start, count):
    file = Path(path)
    stat = file.stat()
    raw = f"{file.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{start}|{count}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _rate_args(binary):
    """ffmpeg 8 dropped -vsync. Older copies still only know that flag."""
    cached = getattr(_rate_args, "value", None)
    if cached and cached[0] == binary:
        return cached[1]
    probe = subprocess.run([binary, "-hide_banner", "-h", "full"], capture_output=True, text=True)
    text = (probe.stdout or "") + (probe.stderr or "")
    args = ["-fps_mode", "vfr"] if "-fps_mode" in text else ["-vsync", "vfr"]
    _rate_args.value = (binary, args)
    return args


def _run(command):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    if process.returncode != 0:
        message = error.decode("utf-8", "replace")[-800:]
        raise RuntimeError(message or f"ffmpeg failed ({process.returncode}).")
    return output


def load_filmstrip(clip, cache, binary=None):
    """64×36 RGB pictures for every source frame of the clip, cached."""
    binary = binary or ffmpeg_path()
    start = int(clip.get("source_start") or 0)
    count = max(0, int(clip.get("source_end") or 0) - start)
    if count <= 0:
        count = max(0, int(clip["end"]) - int(clip["start"]))
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    stored = cache / f"strip_{_key(clip['path'], start, count)}.npy"
    if stored.is_file():
        return np.load(stored)
    end = start + count - 1
    command = [binary, "-hide_banner", "-loglevel", "error", "-i", clip["path"],
               "-vf", f"select='between(n,{start},{end})',scale={WIDTH}:{HEIGHT}:flags=bilinear",
               *_rate_args(binary), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    raw = _run(command)
    frame_bytes = WIDTH * HEIGHT * 3
    got = len(raw) // frame_bytes
    if got <= 0:
        raise RuntimeError(f"No picture was read from {clip['path']}.")
    frames = np.frombuffer(raw[:got * frame_bytes], dtype=np.uint8).reshape(got, HEIGHT, WIDTH, 3).copy()
    np.save(stored, frames)
    return frames


def load_waveform(clip, timeline_fps, cache, binary=None):
    """Mono float32 at 16 kHz, starting at the clip's first timeline frame."""
    binary = binary or ffmpeg_path()
    source_fps = float(clip.get("fps") or timeline_fps)
    start_sec = int(clip.get("source_start") or 0) / source_fps
    duration = max(0.0, (int(clip["end"]) - int(clip["start"])) / float(timeline_fps))
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    stored = cache / f"wave_{_key(clip['path'], int(start_sec * 1000), int(duration * 1000))}.npy"
    if stored.is_file():
        return np.load(stored)
    command = [binary, "-hide_banner", "-loglevel", "error", "-i", clip["path"],
               "-ss", f"{start_sec:.6f}", "-t", f"{duration:.6f}",
               "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"]
    raw = _run(command)
    audio = np.frombuffer(raw, dtype=np.float32).copy() if raw else np.zeros(0, dtype=np.float32)
    np.save(stored, audio)
    return audio


def extract_stills(frames, cache, binary=None):
    """One JPEG per candidate, grouped so each media file is decoded once."""
    binary = binary or ffmpeg_path()
    cache = Path(cache) / "stills"
    cache.mkdir(parents=True, exist_ok=True)
    groups = {}
    for frame in frames:
        groups.setdefault(frame["media"], []).append(frame)
    for media, items in groups.items():
        pending = []
        for frame in items:
            dest = cache / _key(media, int(frame["source_frame"]), 1)
            dest = dest.with_suffix(".jpg")
            frame["image"] = str(dest)
            if not dest.is_file():
                pending.append(frame)
        if not pending:
            continue
        pending.sort(key=lambda frame: int(frame["source_frame"]))
        select = "+".join(f"eq(n,{int(frame['source_frame'])})" for frame in pending)
        folder = cache / "batch"
        folder.mkdir(parents=True, exist_ok=True)
        pattern = str(folder / "frame_%05d.jpg")
        for old in folder.glob("frame_*.jpg"):
            old.unlink()
        command = [binary, "-hide_banner", "-loglevel", "error", "-i", media,
                   "-vf", f"select='{select}',scale=448:-2", *_rate_args(binary), "-q:v", "3", pattern]
        _run(command)
        written = sorted(folder.glob("frame_*.jpg"))
        if len(written) != len(pending):
            raise RuntimeError(f"{len(written)} images extracted for {len(pending)} requested in {media}.")
        for src, frame in zip(written, pending):
            Path(frame["image"]).parent.mkdir(parents=True, exist_ok=True)
            src.replace(frame["image"])

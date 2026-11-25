"""Filmstrip and stills read with ffmpeg, then kept on disk."""

import hashlib
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from vispa_mp.shots import HEIGHT, WIDTH

ROOT = Path(__file__).resolve().parents[1]
STILL_WIDTH = 448
STOPPED = "The analysis was stopped."


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
    probe = subprocess.run([binary, "-hide_banner", "-h", "full"], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = (probe.stdout or "") + (probe.stderr or "")
    args = ["-fps_mode", "vfr"] if "-fps_mode" in text else ["-vsync", "vfr"]
    _rate_args.value = (binary, args)
    return args


class _Ffmpeg:
    """One ffmpeg process read from stdout. ``cancel`` kills it, even mid-decode."""

    def __init__(self, command, cancel=None):
        self.cancel = cancel
        self.cancelled = False
        self.finished_early = False
        self.process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.stdout = self.process.stdout
        self._errors = []
        self._drain = threading.Thread(target=self._read_errors, daemon=True)
        self._drain.start()
        if cancel is not None:
            threading.Thread(target=self._watch, daemon=True).start()

    def _read_errors(self):
        self._errors.append(self.process.stderr.read())

    def _watch(self):
        while self.process.poll() is None:
            if self.cancel():
                self.cancelled = True
                self.process.kill()
                return
            time.sleep(0.1)

    def stop(self):
        """Enough was read: end ffmpeg without calling it a failure."""
        self.finished_early = True
        if self.process.poll() is None:
            self.process.kill()

    def __enter__(self):
        return self

    def __exit__(self, kind, _value, _trace):
        if kind is not None and self.process.poll() is None:
            self.process.kill()
        code = self.process.wait()
        self._drain.join(timeout=5)
        if self.cancelled or (self.cancel is not None and self.cancel()):
            raise InterruptedError(STOPPED)
        if kind is None and code != 0 and not self.finished_early:
            message = b"".join(item or b"" for item in self._errors).decode("utf-8", "replace")[-800:]
            raise RuntimeError(message or f"ffmpeg failed ({code}).")
        return False


def _run(command, cancel=None, expected=0, report=None):
    """All of ffmpeg's output. With ``expected`` bytes, ``report`` gets how far it is."""
    chunks, received = [], 0
    with _Ffmpeg(command, cancel) as run:
        while True:
            chunk = run.stdout.read(1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
            if report is not None and expected:
                report(received / expected)
    return b"".join(chunks)


def _read_exactly(stream, size):
    data = stream.read(size)
    if data is None or len(data) < size:
        return None
    return data


def ppm_frames(stream):
    """Pictures from ffmpeg's ``-f image2pipe -c:v ppm`` output, one array each."""
    while True:
        magic = stream.readline()
        if not magic:
            return
        if magic.strip() != b"P6":
            raise RuntimeError("ffmpeg sent an unexpected picture format.")
        size = stream.readline().split()
        stream.readline()
        width, height = int(size[0]), int(size[1])
        data = _read_exactly(stream, width * height * 3)
        if data is None:
            return
        yield np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)


def load_filmstrip(clip, cache, binary=None, cancel=None, report=None):
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
    frame_bytes = WIDTH * HEIGHT * 3
    raw = _run(command, cancel, count * frame_bytes, report)
    got = len(raw) // frame_bytes
    if got <= 0:
        raise RuntimeError(f"No picture was read from {clip['path']}.")
    frames = np.frombuffer(raw[:got * frame_bytes], dtype=np.uint8).reshape(got, HEIGHT, WIDTH, 3).copy()
    np.save(stored, frames)
    return frames


def load_waveform(clip, timeline_fps, cache, binary=None, cancel=None, report=None):
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
    raw = _run(command, cancel, int(duration * 16000) * 4, report)
    audio = np.frombuffer(raw, dtype=np.float32).copy() if raw else np.zeros(0, dtype=np.float32)
    np.save(stored, audio)
    return audio


def _save_still(picture, destination):
    from PIL import Image
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.stem + ".part.jpg")
    Image.fromarray(picture).save(partial, quality=92)
    os.replace(partial, destination)


def extract_stills(frames, cache, binary=None, cancel=None, report=None):
    """One JPEG per candidate, 448 px wide.

    Each media file is decoded once, from the first wanted frame to the last.
    ffmpeg sends every picture of that span and Python keeps the wanted ones,
    so there is no limit on how many stills one pass can write.
    """
    binary = binary or ffmpeg_path()
    report = report or (lambda _fraction, _detail: None)
    cache = Path(cache) / "stills"
    cache.mkdir(parents=True, exist_ok=True)
    groups = {}
    for frame in frames:
        groups.setdefault(frame["media"], []).append(frame)
    wanted = {}
    for media, items in groups.items():
        pending = {}
        for frame in items:
            number = int(frame["source_frame"])
            dest = cache / (_key(media, number, 1) + ".jpg")
            frame["image"] = str(dest)
            if not dest.is_file():
                pending.setdefault(number, dest)
        wanted[media] = pending
    total = sum(len(pending) for pending in wanted.values())
    written = 0
    for media, pending in wanted.items():
        if not pending:
            continue
        first, last = min(pending), max(pending)
        command = [binary, "-hide_banner", "-loglevel", "error", "-i", media,
                   "-vf", f"select='between(n,{first},{last})',scale={STILL_WIDTH}:-2",
                   *_rate_args(binary), "-f", "image2pipe", "-c:v", "ppm", "pipe:1"]
        before = written
        with _Ffmpeg(command, cancel) as run:
            for offset, picture in enumerate(ppm_frames(run.stdout)):
                number = first + offset
                dest = pending.get(number)
                if dest is not None:
                    _save_still(picture, dest)
                    written += 1
                    report(written / total, f"{written}/{total} images")
                if number >= last:
                    run.stop()
                    break
        if written - before != len(pending):
            raise RuntimeError(f"{written - before} images extracted for {len(pending)} requested in {media}.")

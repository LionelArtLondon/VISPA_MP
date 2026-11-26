"""Read video 1 and audio 1, then hand measured frames to the rules."""

import hashlib
import json
import time
from pathlib import Path

from vispa_mp.candidates import candidate_frames
from vispa_mp.frames import STOPPED, extract_stills, load_filmstrip, load_waveform
from vispa_mp.preset import setting
from vispa_mp.progress import Steps
from vispa_mp.shots import build_shots
from vispa_mp.speech import Silero, map_turns, turns_from_probs
from vispa_mp.store import ScoreStore, load_analysis, save_analysis
from vispa_mp.tags import Tagger, model_id
from vispa_mp.timeline_identity import normalize_identity

# Raise this when the content of an analysis changes: saved ones are then redone.
ANALYSIS_VERSION = 2
# Settings that change which frames are examined. The others only change the rules.
# The speech settings are left out: the review already redraws the lines from the
# saved probabilities, so changing them never asked for a new analysis.
CANDIDATE_SETTINGS = (
    "hold_ratio", "end_fraction", "candidates_per_line", "max_tagged_per_shot", "spread_tagged", "use_in_out",
)


def _normal_speed(value):
    if value is None or value == "":
        return True
    try:
        number = float(value)
    except (TypeError, ValueError):
        return True
    return abs(number - 1) < 0.02 or abs(number - 100) < 1


def _range_of(snapshot, settings):
    if not setting(settings, "use_in_out"):
        return None, []
    start, end = snapshot.get("mark_in"), snapshot.get("mark_out")
    notes = []
    if start is None and end is None:
        notes.append("No In/Out range: the whole timeline is analyzed.")
        return None, notes
    start = snapshot["start_frame"] if start is None else start
    end = snapshot["end_frame"] if end is None else end
    return (int(start), int(end)), notes


def _overlaps(shot, span):
    if span is None:
        return True
    return shot["end"] > span[0] and shot["start"] < span[1]


def time_left(done, total, elapsed):
    """'about 12 min left' from the pace so far."""
    if done <= 0 or total <= done:
        return ""
    seconds = elapsed / done * (total - done)
    if seconds < 60:
        return "less than a minute left"
    minutes = int(round(seconds / 60))
    if minutes < 90:
        return f"about {minutes} min left"
    return f"about {minutes // 60} h {minutes % 60:02d} min left"


class Live:
    """ffmpeg, Silero and the tagger. Tests pass their own object instead."""

    def __init__(self, cache, steps=None, cancel=None):
        from vispa_mp.models_setup import MODELS, SILERO, WD_LABELS, WD_ONNX, ready
        if not ready():
            raise RuntimeError("The models are missing. Download them before analyzing.")
        self.cache = Path(cache or (MODELS.parent / "cache"))
        self.steps = steps or Steps()
        self.cancel = cancel
        self.silero = Silero(SILERO)
        self.wd_files = (WD_ONNX, WD_LABELS)
        self.tagger = None
        self.scores = ScoreStore(self.cache, model_id(WD_ONNX))

    def filmstrip(self, clip):
        return load_filmstrip(clip, self.cache, cancel=self.cancel,
                              report=self.steps.part(clip.get("name") or "Video 1"))

    def waveform(self, clip, fps):
        # The sound is half of this step, speech the other half.
        part = self.steps.part("Reading " + (clip.get("name") or "audio 1"))
        return load_waveform(clip, fps, self.cache, cancel=self.cancel, report=lambda value: part(value / 2))

    def probabilities(self, audio):
        part = self.steps.part("Finding the lines")
        return self.silero.probabilities(audio, cancel=self.cancel, report=lambda value: part(0.5 + value / 2))

    def score_many(self, frames):
        self.steps.start(4, f"0/{len(frames)} images")
        extract_stills(frames, self.cache, cancel=self.cancel,
                       report=lambda fraction, detail: self.steps.send(fraction, detail))
        self.steps.start(5, "")
        todo = []
        for frame in frames:
            known = self.scores.get(frame["image"])
            if known is None:
                todo.append(frame)
            else:
                frame.update(known)
        if not todo:
            self.steps.send(1.0, f"{len(frames)} images, all already known", force=True)
            return
        known = len(frames) - len(todo)
        aside = f" · {known} already known" if known else ""
        self.steps.send(0.0, "Loading the model" + aside, force=True)
        if self.tagger is None:
            self.tagger = Tagger(*self.wd_files)
        device = getattr(self.tagger, "device", "processor")
        started = time.monotonic()
        for index, frame in enumerate(todo, 1):
            if self.cancel is not None and self.cancel():
                raise InterruptedError(STOPPED)
            scores = self.tagger.score_path(frame["image"])
            self.scores.put(frame["image"], scores)
            frame.update(scores)
            left = time_left(index, len(todo), time.monotonic() - started)
            self.steps.send(index / len(todo), f"{index}/{len(todo)} images on the {device}{aside}", left)


def refresh_utterances(analysis, settings):
    """New line boundaries from probabilities already computed."""
    fps = float(analysis["fps"])
    utterances = []
    for track in analysis.get("speech_tracks") or []:
        utterances.extend(map_turns(turns_from_probs(track["probs"], settings), int(track["start"]), fps))
    return utterances


def _media_of(clip):
    path = clip.get("path") or ""
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return [path, stat.st_mtime_ns, stat.st_size] + [
        clip.get(name) for name in ("start", "end", "source_start", "source_end", "fps", "speed")]


def analysis_key(snapshot, settings):
    """Names an analysis by everything that went into it. None when a media file is missing."""
    from vispa_mp.models_setup import WD_ONNX
    identity = normalize_identity(snapshot.get("timeline_identity"))
    if identity is None:
        return None
    media = []
    for clip in list(snapshot.get("video_clips") or []) + list(snapshot.get("audio_clips") or []):
        described = _media_of(clip)
        if described is None:
            return None
        media.append(described)
    if not media:
        return None
    span, _notes = _range_of(snapshot, settings)
    raw = json.dumps({
        "version": ANALYSIS_VERSION,
        "timeline_identity": identity,
        "tagger": model_id(WD_ONNX),
        "fps": snapshot.get("fps"),
        "start_frame": snapshot.get("start_frame"),
        "media": media,
        "range": list(span) if span else None,
        "settings": {name: setting(settings, name) for name in CANDIDATE_SETTINGS},
    }, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _for_snapshot(analysis, snapshot):
    """A saved analysis, with what may have changed in Resolve since: hand markers and name."""
    identity = normalize_identity(analysis.get("timeline_identity"))
    if identity is None or identity != normalize_identity(snapshot.get("timeline_identity")):
        return None
    restored = dict(analysis)
    restored["timeline_identity"] = identity
    restored["manual_frames"] = [int(marker["frame"]) for marker in snapshot.get("markers") or []
                                 if not marker.get("automatic")]
    restored["timeline_name"] = snapshot.get("timeline_name") or restored.get("timeline_name") or ""
    restored["project_name"] = snapshot.get("project_name") or restored.get("project_name") or ""
    restored["restored"] = True
    return restored


def saved_analysis(snapshot, settings, cache):
    """The analysis already made for this timeline and these settings, or None."""
    key = analysis_key(snapshot, settings)
    if key is None:
        return None
    found = load_analysis(cache, key)
    return _for_snapshot(found, snapshot) if found else None


def analyze(snapshot, settings, sources=None, progress=None, cancel=None, store=None):
    """Shots, lines and tagged frames. Rules stay outside, so a threshold does not redo this.

    With ``store`` (the cache folder), a finished analysis is saved there and
    the same inputs later load it instead of running anything.
    """
    steps = Steps(progress)
    key = analysis_key(snapshot, settings) if store is not None else None
    if key is not None:
        found = load_analysis(store, key)
        restored = _for_snapshot(found, snapshot) if found else None
        if restored:
            return restored
    sources = sources or Live(snapshot.get("cache"), steps, cancel)
    fps = float(snapshot["fps"])
    warnings = list(snapshot.get("warnings") or [])
    clips = list(snapshot.get("video_clips") or [])
    if not clips:
        raise RuntimeError("Video 1 has no clip to read.")
    for clip in clips + list(snapshot.get("audio_clips") or []):
        if not _normal_speed(clip.get("speed")):
            warnings.append(f"{clip.get('name') or 'A clip'} is not at normal speed. The alignment may drift.")
    steps.start(1, clips[0].get("name") or "Video 1")
    strips = [sources.filmstrip(clip) for clip in clips]
    steps.start(2, f"{len(clips)} clip(s) on video 1")
    shots = build_shots(clips, strips, fps, cancel, steps.part(f"{len(clips)} clip(s) on video 1"))
    span, notes = _range_of(snapshot, settings)
    warnings.extend(notes)
    kept = [shot for shot in shots if _overlaps(shot, span)]
    speech_tracks = []
    utterances = []
    steps.start(3, f"{len(kept)} shots found" if kept else "")
    for clip in snapshot.get("audio_clips") or []:
        audio = sources.waveform(clip, fps)
        expected = (int(clip["end"]) - int(clip["start"])) / fps
        if expected and len(audio) / 16000 < 0.9 * expected:
            warnings.append("The sound of " + (clip.get("name") or "audio 1") + " is shorter than the clip.")
        probs = list(sources.probabilities(audio))
        speech_tracks.append({"start": int(clip["start"]), "end": int(clip["end"]), "probs": probs})
        utterances.extend(map_turns(turns_from_probs(probs, settings), int(clip["start"]), fps))
    chosen = []
    for shot in kept:
        shot["frames"] = candidate_frames(shot, utterances, settings)
        chosen.extend(shot["frames"])
    if chosen and hasattr(sources, "score_many"):
        sources.score_many(chosen)
    elif chosen:
        steps.start(5, f"{len(chosen)} images")
        for frame in chosen:
            if cancel is not None and cancel():
                raise InterruptedError(STOPPED)
            frame.update(sources.score(frame))
    manual = [int(marker["frame"]) for marker in snapshot.get("markers") or [] if not marker.get("automatic")]
    result = {
        "fps": fps,
        "timebase": {
            "fps": fps,
            "timecode_fps": float(snapshot.get("timecode_fps") or fps),
            "start_frame": int(snapshot.get("start_frame") or 0),
            "start_timecode": snapshot.get("start_timecode") or "00:00:00:00",
            "drop": bool(snapshot.get("drop")),
        },
        "range": list(span) if span else None,
        "shots": kept,
        "utterances": utterances,
        "speech_tracks": speech_tracks,
        "manual_frames": manual,
        "warnings": warnings,
        "timeline_name": snapshot.get("timeline_name") or "",
        "project_name": snapshot.get("project_name") or "",
        "timeline_identity": normalize_identity(snapshot.get("timeline_identity")),
    }
    if key is not None:
        result["key"] = key
        save_analysis(store, key, result)
    return result

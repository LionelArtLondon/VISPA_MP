"""Read video 1 and audio 1, then hand measured frames to the rules."""

from vispa_mp.candidates import candidate_frames
from vispa_mp.frames import extract_stills, load_filmstrip, load_waveform
from vispa_mp.preset import setting
from vispa_mp.shots import build_shots
from vispa_mp.speech import Silero, map_turns, turns_from_probs
from vispa_mp.tags import Tagger


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


class Live:
    """ffmpeg, Silero and the tagger. Tests pass their own object instead."""

    def __init__(self, cache, progress=None):
        from vispa_mp.models_setup import MODELS, SILERO, WD_LABELS, WD_ONNX, ready
        if not ready():
            raise RuntimeError("The models are missing. Download them before analyzing.")
        self.cache = cache or (MODELS.parent / "cache")
        self.progress = progress or (lambda _text: None)
        self.silero = Silero(SILERO)
        self.tagger = Tagger(WD_ONNX, WD_LABELS)

    def filmstrip(self, clip):
        self.progress(f"Pictures from {clip.get('name') or 'video 1'}")
        return load_filmstrip(clip, self.cache)

    def waveform(self, clip, fps):
        self.progress("Sound from " + (clip.get("name") or "audio 1"))
        return load_waveform(clip, fps, self.cache)

    def probabilities(self, audio):
        self.progress("Speech")
        return self.silero.probabilities(audio)

    def score_many(self, frames):
        self.progress(f"{len(frames)} images to recognize")
        extract_stills(frames, self.cache)
        for index, frame in enumerate(frames, 1):
            if index == 1 or index % 5 == 0:
                self.progress(f"Recognizing {index}/{len(frames)}")
            frame.update(self.tagger.score_path(frame["image"]))


def refresh_utterances(analysis, settings):
    """New line boundaries from probabilities already computed."""
    fps = float(analysis["fps"])
    utterances = []
    for track in analysis.get("speech_tracks") or []:
        utterances.extend(map_turns(turns_from_probs(track["probs"], settings), int(track["start"]), fps))
    return utterances


def analyze(snapshot, settings, sources=None, progress=None):
    """Shots, lines and tagged frames. Rules stay outside, so a threshold does not redo this."""
    progress = progress or (lambda _text: None)
    sources = sources or Live(snapshot.get("cache"), progress)
    fps = float(snapshot["fps"])
    warnings = list(snapshot.get("warnings") or [])
    clips = list(snapshot.get("video_clips") or [])
    if not clips:
        raise RuntimeError("Video 1 has no clip to read.")
    for clip in clips + list(snapshot.get("audio_clips") or []):
        if not _normal_speed(clip.get("speed")):
            warnings.append(f"{clip.get('name') or 'A clip'} is not at normal speed. The alignment may drift.")
    strips = [sources.filmstrip(clip) for clip in clips]
    shots = build_shots(clips, strips, fps)
    span, notes = _range_of(snapshot, settings)
    warnings.extend(notes)
    kept = [shot for shot in shots if _overlaps(shot, span)]
    speech_tracks = []
    utterances = []
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
        for frame in chosen:
            frame.update(sources.score(frame))
    manual = [int(marker["frame"]) for marker in snapshot.get("markers") or [] if not marker.get("automatic")]
    return {
        "fps": fps,
        "timebase": {
            "fps": fps,
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
    }

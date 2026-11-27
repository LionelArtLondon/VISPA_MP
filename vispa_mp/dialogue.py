"""Local changes of voice from pyannote's ONNX speaker segmentation model.

The three speaker channels are local to a ten-second window. We retain only
stable change times, never pretend they identify a character across a chapter.
The export and its MIT license are distributed by the sherpa-onnx project.
"""

import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

ENGINE = "pyannote-segmentation-3.0"
VERSION = 1
SAMPLE_RATE = 16000
MIN_VOICE_SECONDS = 0.25
MAX_GAP_SECONDS = 1.20


def _cancelled(cancel):
    if cancel is not None and cancel():
        raise InterruptedError("The analysis was stopped.")


def _stable_changes(log_probs, frame_seconds, first_seconds):
    """Stable singleton changes; silence/overlapping voices are not identities.

    The model's powerset classes are silence, three individual speakers, then
    their three pairwise overlaps. A change is accepted only between two
    sustained, confident singleton runs. Scores are model support, not a
    calibrated measure of diarization accuracy.
    """
    output = np.asarray(log_probs, dtype=np.float32)
    if output.ndim != 2 or output.shape[1] != 7 or not len(output) or not np.isfinite(output).all():
        raise RuntimeError("The voice-change model returned an invalid segmentation.")
    exp = np.exp(output - output.max(axis=1, keepdims=True))
    probabilities = exp / exp.sum(axis=1, keepdims=True)
    classes = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    labels = np.where((classes >= 1) & (classes <= 3) & (confidence >= 0.55), classes, -1)
    # Ignore very short isolated runs (for instance a musical accent), without
    # interpreting an ambiguous overlap as a new voice.
    runs = []
    start = 0
    while start < len(labels):
        end = start + 1
        while end < len(labels) and labels[end] == labels[start]:
            end += 1
        if labels[start] != -1 and (end - start) * frame_seconds >= MIN_VOICE_SECONDS:
            run = [start, end, int(labels[start]), float(confidence[start:end].mean())]
            if (runs and runs[-1][2] == run[2]
                    and (run[0] - runs[-1][1]) * frame_seconds <= MAX_GAP_SECONDS):
                previous = runs[-1]
                previous[1] = run[1]
                previous[3] = min(previous[3], run[3])
            else:
                runs.append(run)
        start = end
    changes = []
    for left, right in zip(runs, runs[1:]):
        gap = (right[0] - left[1]) * frame_seconds
        if left[2] == right[2] or gap > MAX_GAP_SECONDS:
            continue
        boundary = right[0] if gap > 0.35 else (left[1] + right[0]) / 2
        changes.append({"time": first_seconds + boundary * frame_seconds,
                        "confidence": min(left[3], right[3])})
    return changes


class SpeakerChanges:
    """Bounded, cancellable ONNX windows; no network or extra Python framework."""

    def __init__(self, model_path, cache=None, session=None):
        self.path = Path(model_path)
        self.cache = Path(cache) / "dialogue" if cache is not None else None
        if session is None:
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(str(self.path), sess_options=options,
                                          providers=["CPUExecutionProvider"])
        self.session = session
        metadata = session.get_modelmeta().custom_metadata_map
        try:
            self.sample_rate = int(metadata["sample_rate"])
            self.window = int(metadata["window_size"])
            self.receptive = int(metadata["receptive_field_size"])
            self.shift = int(metadata["receptive_field_shift"])
            if (metadata.get("model_type") != ENGINE or self.sample_rate != SAMPLE_RATE
                    or self.window != 160000 or not 0 < self.shift < self.receptive < self.window
                    or int(metadata["num_classes"]) != 7):
                raise ValueError("unsupported speaker model")
        except (KeyError, ValueError, TypeError) as error:
            raise RuntimeError("The voice-change model is not compatible with VISPA MP.") from error
        self.input_name = session.get_inputs()[0].name
        try:
            stat = self.path.stat()
            self.model_stamp = f"{stat.st_size}:{stat.st_mtime_ns}"
        except OSError:
            self.model_stamp = "injected-test-session"

    def _cache_path(self, audio):
        if self.cache is None:
            return None
        key = hashlib.sha256(f"{ENGINE}:{VERSION}:{self.model_stamp}:".encode())
        key.update(memoryview(audio).cast("B"))
        return self.cache / f"{key.hexdigest()[:32]}.json"

    @staticmethod
    def _valid_events(events, duration):
        if not isinstance(events, list):
            return False
        previous = -1.0
        for event in events:
            if not isinstance(event, dict) or set(event) != {"time", "confidence"}:
                return False
            time, confidence = event["time"], event["confidence"]
            try:
                valid = (not isinstance(time, bool) and isinstance(time, (int, float)) and math.isfinite(time)
                         and previous < time < duration and time > 0
                         and not isinstance(confidence, bool) and isinstance(confidence, (int, float))
                         and math.isfinite(confidence) and 0 <= confidence <= 1)
            except OverflowError:
                valid = False
            if not valid:
                return False
            previous = time
        return True

    def changes(self, audio, cancel=None, report=None):
        _cancelled(cancel)
        audio = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1)
        if not np.isfinite(audio).all():
            raise ValueError("The voice-change audio contains invalid samples.")
        duration = len(audio) / SAMPLE_RATE
        cache_path = self._cache_path(audio)
        if cache_path is not None:
            try:
                events = json.loads(cache_path.read_text(encoding="utf-8"))
                if self._valid_events(events, duration):
                    if report is not None:
                        report(1.0)
                    return events
            except (OSError, ValueError):
                pass
        if len(audio) < self.receptive:
            return []
        # Each central five-second region is examined in a full ten-second
        # context. Window seams therefore never manufacture a voice change.
        hop = self.window // 2
        margin = self.window // 4
        positions = range(-margin, len(audio) - margin, hop)
        events = []
        for index, start in enumerate(positions):
            _cancelled(cancel)
            chunk = np.zeros(self.window, dtype=np.float32)
            left, right = max(0, start), min(len(audio), start + self.window)
            chunk[left - start:right - start] = audio[left:right]
            output = self.session.run(None, {self.input_name: chunk[None, None, :]})[0]
            _cancelled(cancel)
            if np.asarray(output).ndim != 3 or output.shape[0] != 1:
                raise RuntimeError("The voice-change model returned an invalid batch.")
            first = (start + self.receptive / 2) / SAMPLE_RATE
            changes = _stable_changes(output[0], self.shift / SAMPLE_RATE, first)
            valid_start = (start + margin) / SAMPLE_RATE
            valid_end = (start + margin + hop) / SAMPLE_RATE
            events.extend(event for event in changes
                          if 0 < event["time"] < duration and valid_start <= event["time"] < valid_end)
            if report is not None:
                report((index + 1) / len(positions))
        events.sort(key=lambda event: event["time"])
        retained = []
        for event in events:
            if retained and event["time"] - retained[-1]["time"] < MIN_VOICE_SECONDS:
                if event["confidence"] > retained[-1]["confidence"]:
                    retained[-1] = event
            else:
                retained.append(event)
        _cancelled(cancel)
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            partial = cache_path.with_suffix(".part")
            partial.write_text(json.dumps(retained, allow_nan=False), encoding="utf-8")
            os.replace(partial, cache_path)
        return retained


def dialogue_summary(analysis):
    """A readable status, including old projects and an explicit VAD fallback."""
    if not analysis:
        return "Voice changes are detected automatically during Analyze."
    tracks = analysis.get("speech_tracks") or []
    if not tracks:
        return "No analyzed audio track; dialogue voice changes are unavailable."
    statuses = [track.get("dialogue_status") for track in tracks]
    ready = [status for status in statuses if status and status.get("state") == "ready"]
    count = sum(int(status.get("changes") or 0) for status in ready)
    if len(ready) == len(tracks):
        return f"Voice changes: {count} detected. Voices are timing cues, not character identities."
    if ready:
        return f"Voice changes: {count} detected; some audio uses speech timing only. Analyze again after checking the model."
    if all(status is None for status in statuses):
        return "This preparation uses speech timing only. Run Analyze again to detect voice changes."
    return "Voice-change analysis unavailable; speech timing remains active. Check Download models, then Analyze again."

"""Speech turns on audio 1.

Silero VAD v6.3 supplies one probability per 32 ms. The silence that splits two
lines is a setting, so it can change without running the network again.
"""

from vispa_mp.preset import setting

SAMPLE_RATE = 16000
WINDOW = 512


def segment_probs(probs, settings, sample_rate=SAMPLE_RATE):
    """Sample ranges of speech. A silence of ``speech_min_silence_ms`` ends a line."""
    window = WINDOW if sample_rate == 16000 else sample_rate // 31
    threshold = float(setting(settings, "speech_threshold"))
    negative = max(threshold - 0.15, 0.01)
    min_speech = sample_rate * float(setting(settings, "speech_min_duration_ms")) / 1000
    min_silence = sample_rate * float(setting(settings, "speech_min_silence_ms")) / 1000
    pad = sample_rate * float(setting(settings, "speech_pad_ms")) / 1000
    total = len(probs) * window
    speeches = []
    start = None
    silence_at = None
    for index, prob in enumerate(probs):
        sample = index * window
        if prob >= threshold:
            if start is None:
                start = sample
            silence_at = None
            continue
        if start is None or prob >= negative:
            continue
        if silence_at is None:
            silence_at = sample
        if sample - silence_at >= min_silence:
            end = silence_at
            if end - start >= min_speech:
                speeches.append([start, end])
            start = None
            silence_at = None
    if start is not None and total - start >= min_speech:
        speeches.append([start, total])
    padded = []
    for begin, end in speeches:
        begin = max(0, int(begin - pad))
        end = min(total, int(end + pad))
        if padded and begin < padded[-1][1]:
            middle = (padded[-1][1] + begin) // 2
            padded[-1][1] = middle
            begin = middle
        if end > begin:
            padded.append([begin, end])
    return padded


def turns_from_probs(probs, settings, sample_rate=SAMPLE_RATE):
    """``start`` and ``end`` in seconds, relative to the start of this audio."""
    return [{"start": begin / sample_rate, "end": end / sample_rate}
            for begin, end in segment_probs(probs, settings, sample_rate)]


def dialogue_turns(probs, settings, speaker_changes=(), sample_rate=SAMPLE_RATE):
    """Split voiced intervals at measured changes, preserving silence boundaries.

    Anonymous turn IDs describe timing, not character identity. Tiny fragments
    and changes outside speech do not create extra marker opportunities.
    """
    import math
    lines = turns_from_probs(probs, settings, sample_rate)
    events = []
    for event in speaker_changes or ():
        if not isinstance(event, dict):
            continue
        time, confidence = event.get("time"), event.get("confidence")
        if (isinstance(time, (int, float)) and not isinstance(time, bool) and math.isfinite(time)
                and isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
                and math.isfinite(confidence) and 0.55 <= confidence <= 1):
            events.append((float(time), float(confidence)))
    events.sort()
    minimum = max(0.20, min(0.35, float(setting(settings, "speech_min_duration_ms")) / 1000))
    result = []
    for line in lines:
        accepted = []
        previous = line["start"]
        for time, confidence in events:
            if time - previous >= minimum and line["end"] - time >= minimum:
                if line["start"] < time < line["end"]:
                    accepted.append((time, confidence))
                    previous = time
        if not accepted:
            result.append(line)
            continue
        points = [line["start"]] + [time for time, _score in accepted] + [line["end"]]
        for index, (begin, end) in enumerate(zip(points, points[1:])):
            supports = [accepted[min(index, len(accepted) - 1)][1]]
            if index:
                supports.append(accepted[index - 1][1])
            result.append({"start": begin, "end": end, "source": "speaker_change",
                           "turn_id": f"voice-turn-{len(result)}", "confidence": min(supports)})
    return result


def map_turns(turns, start_frame, fps):
    """Timeline frames of turns whose zero is ``start_frame``."""
    mapped = []
    for turn in turns:
        begin = int(round(start_frame + turn["start"] * fps))
        end = int(round(start_frame + turn["end"] * fps))
        if end > begin:
            item = {"start": begin, "end": end}
            for key in ("source", "speaker", "confidence"):
                if key in turn:
                    item[key] = turn[key]
            if "turn_id" in turn:
                item["turn_id"] = f"{start_frame}:{turn['turn_id']}"
            mapped.append(item)
    return mapped


class Silero:
    """ONNX Silero VAD. The state stays inside one audio file, then resets."""

    def __init__(self, path):
        import onnxruntime as ort
        from vispa_mp.tags import providers
        self.session = ort.InferenceSession(str(path), providers=providers(gpu=False))
        self._prob_name, self._state_name = _io_names(self.session)
        self.reset()

    def reset(self):
        import numpy as np
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, 64), dtype=np.float32)

    def probabilities(self, audio, sample_rate=SAMPLE_RATE, cancel=None, report=None):
        import numpy as np
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if sample_rate != SAMPLE_RATE:
            raise ValueError("Silero is called at 16 kHz.")
        self.reset()
        if len(audio) % WINDOW:
            audio = np.pad(audio, (0, WINDOW - len(audio) % WINDOW))
        probs = []
        for start in range(0, len(audio), WINDOW):
            if start % (WINDOW * 2000) == 0:
                if cancel is not None and cancel():
                    raise InterruptedError("The analysis was stopped.")
                if report is not None:
                    report(start / max(1, len(audio)))
            chunk = audio[start:start + WINDOW][None, :]
            model_input = np.concatenate([self.context, chunk], axis=1)
            outputs = self.session.run(None, {
                "input": model_input,
                "state": self.state,
                "sr": np.array(sample_rate, dtype=np.int64),
            })
            names = [item.name for item in self.session.get_outputs()]
            by_name = dict(zip(names, outputs))
            out = by_name.get(self._prob_name, outputs[0])
            self.state = by_name.get(self._state_name, outputs[-1])
            self.context = model_input[:, -64:]
            probs.append(float(np.asarray(out).reshape(-1)[0]))
        return probs


def _io_names(session):
    outputs = [item.name for item in session.get_outputs()]
    prob = next((name for name in outputs if "state" not in name.lower()), outputs[0])
    state = next((name for name in outputs if "state" in name.lower()), outputs[-1])
    return prob, state

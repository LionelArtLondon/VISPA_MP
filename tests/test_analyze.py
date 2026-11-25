import numpy as np

from vispa_mp.analyze import analyze
from vispa_mp.candidates import candidate_frames
from vispa_mp.preset import DEFAULTS


def test_candidates_cover_the_end_of_the_shot_and_each_line():
    frames = [{"frame": number, "sharpness": number, "neighbor": 0.2 if number % 2 == 0 else 20} for number in range(0, 100, 10)]
    shot = {"start": 0, "end": 100, "frames": frames}
    chosen = candidate_frames(shot, [{"start": 0, "end": 40}], dict(DEFAULTS))
    numbers = [frame["frame"] for frame in chosen]
    assert 90 in numbers
    assert any(number < 40 for number in numbers)


class Sources:
    def __init__(self, strip):
        self.strip = strip
        self.scored = []

    def filmstrip(self, _clip):
        return self.strip

    def waveform(self, _clip, _fps):
        return np.zeros(16000, dtype=np.float32)

    def probabilities(self, audio):
        return [0.0] * max(1, len(audio) // 512)

    def score(self, frame):
        self.scored.append(frame["frame"])
        opened = frame["source_frame"] >= 5
        return {
            "open_mouth": 0.9 if opened else 0.05,
            "closed_mouth": 0.05 if opened else 0.8,
            "motion_blur": 0.0, "from_behind": 0.0, "group": 0.1, "solo": 0.8,
            "face": 0.9, "expression": 0.3,
        }


def test_analyze_tags_only_the_range_and_keeps_hand_markers():
    black = np.zeros((36, 64, 3), dtype=np.uint8)
    white = np.full((36, 64, 3), 255, dtype=np.uint8)
    strip = np.stack([black] * 5 + [white] * 5)
    clip = {"name": "episode", "start": 0, "end": 10, "source_start": 0, "source_end": 10,
            "path": "episode.mp4", "fps": 24, "speed": 1}
    snapshot = {
        "fps": 24, "start_frame": 0, "end_frame": 10, "start_timecode": "00:00:00:00", "drop": False,
        "timeline_name": "Episode", "video_clips": [clip], "audio_clips": [],
        "markers": [{"frame": 1, "automatic": False}, {"frame": 8, "automatic": True}],
        "mark_in": None, "mark_out": None, "warnings": [],
    }
    sources = Sources(strip)
    settings = dict(DEFAULTS)
    settings["use_in_out"] = True
    result = analyze(snapshot, settings, sources=sources)
    assert result["manual_frames"] == [1]
    assert sources.scored
    assert any("In/Out" in warning for warning in result["warnings"])
    assert result["shots"][0]["opening"] is True

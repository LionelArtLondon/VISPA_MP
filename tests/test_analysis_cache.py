"""A full episode: many stills, an analysis that can stop, resume and come back."""

import subprocess
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from vispa_mp import analyze as analyze_module
from vispa_mp.analyze import Live, analysis_key, analyze, saved_analysis, time_left
from vispa_mp.frames import extract_stills, ffmpeg_path
from vispa_mp.preset import DEFAULTS
from vispa_mp.progress import Steps
from vispa_mp.store import ScoreStore

try:
    FFMPEG = ffmpeg_path()
except RuntimeError:
    FFMPEG = None

needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")


def _numbered_video(path, count):
    """Frame n is a flat grey of level n, losslessly encoded, so a still tells its number."""
    process = subprocess.Popen(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
         "-s", "64x36", "-r", "24", "-i", "pipe:0", "-c:v", "ffv1", "-pix_fmt", "gray", str(path)],
        stdin=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for number in range(count):
        process.stdin.write(np.full((36, 64), number, dtype=np.uint8).tobytes())
    process.stdin.close()
    assert process.wait() == 0


@needs_ffmpeg
def test_one_pass_writes_more_stills_than_ffmpeg_could_select(tmp_path):
    video = tmp_path / "episode.mkv"
    _numbered_video(video, 250)
    wanted = list(range(10, 250, 2))[:150]  # the old select expression failed past about 100
    frames = [{"media": str(video), "source_frame": number} for number in wanted]
    extract_stills(frames, tmp_path / "cache")
    for frame in frames:
        with Image.open(frame["image"]) as image:
            assert image.width == 448
            level = float(np.asarray(image.convert("L")).mean())
        assert abs(level - frame["source_frame"]) < 2.5, frame
    assert not list((tmp_path / "cache" / "stills").glob("*.part.jpg"))


@needs_ffmpeg
def test_a_stopped_extraction_leaves_no_half_written_still(tmp_path):
    video = tmp_path / "episode.mkv"
    _numbered_video(video, 120)
    frames = [{"media": str(video), "source_frame": number} for number in range(0, 120, 3)]
    with pytest.raises(InterruptedError):
        extract_stills(frames, tmp_path / "cache", cancel=lambda: True)
    assert not list((tmp_path / "cache" / "stills").glob("*.part.jpg"))
    extract_stills(frames, tmp_path / "cache")
    assert all(Path(frame["image"]).is_file() for frame in frames)


def test_scores_survive_a_restart_and_a_cut_line(tmp_path):
    store = ScoreStore(tmp_path, "model")
    store.put("stills/abc.jpg", {"open_mouth": 0.9})
    with store.path.open("a", encoding="utf-8") as file:
        file.write('{"key": "half')  # the app closed in the middle of a write
    again = ScoreStore(tmp_path, "model")
    assert again.get("other/abc.jpg") == {"open_mouth": 0.9}
    assert again.get("stills/missing.jpg") is None
    assert ScoreStore(tmp_path, "another-model").get("stills/abc.jpg") is None


class _Tagger:
    def __init__(self):
        self.seen = []

    def score_path(self, path):
        self.seen.append(Path(path).stem)
        return {"open_mouth": 0.5, "closed_mouth": 0.1}


def _live(tmp_path, cancel=None):
    live = Live.__new__(Live)
    live.cache = tmp_path
    live.steps = Steps()
    live.cancel = cancel
    live.tagger = _Tagger()
    live.wd_files = None
    live.scores = ScoreStore(tmp_path, "model")
    return live


def test_a_stopped_recognition_resumes_with_the_images_left(tmp_path, monkeypatch):
    def fake_stills(frames, _cache, **_kwargs):
        for frame in frames:
            frame["image"] = str(tmp_path / f"still{frame['frame']}.jpg")

    monkeypatch.setattr(analyze_module, "extract_stills", fake_stills)
    frames = [{"frame": number} for number in range(10)]
    first = _live(tmp_path, cancel=lambda: len(first.tagger.seen) >= 4)
    with pytest.raises(InterruptedError):
        first.score_many([dict(frame) for frame in frames])
    assert len(first.tagger.seen) == 4
    second = _live(tmp_path)
    scored = [dict(frame) for frame in frames]
    second.score_many(scored)
    assert second.tagger.seen == [f"still{number}" for number in range(4, 10)]
    assert all(frame["open_mouth"] == 0.5 for frame in scored)
    third = _live(tmp_path)
    third.score_many([dict(frame) for frame in frames])
    assert third.tagger.seen == []


class _Sources:
    def __init__(self):
        self.calls = 0

    def filmstrip(self, _clip):
        self.calls += 1
        black = np.zeros((36, 64, 3), dtype=np.uint8)
        white = np.full((36, 64, 3), 255, dtype=np.uint8)
        return np.stack([black] * 5 + [white] * 5)

    def waveform(self, _clip, _fps):
        return np.zeros(16000, dtype=np.float32)

    def probabilities(self, audio):
        return [0.0] * max(1, len(audio) // 512)

    def score(self, _frame):
        return {"open_mouth": 0.1, "closed_mouth": 0.8, "motion_blur": 0.0, "from_behind": 0.0,
                "group": 0.1, "solo": 0.8, "face": 0.9, "expression": 0.3}


def _snapshot(media, markers=()):
    clip = {"name": "episode", "start": 0, "end": 10, "source_start": 0, "source_end": 10,
            "path": str(media), "fps": 24, "speed": 1}
    return {
        "fps": 24, "start_frame": 0, "end_frame": 10, "start_timecode": "00:00:00:00", "drop": False,
        "timeline_name": "Episode", "video_clips": [clip], "audio_clips": [],
        "markers": list(markers), "mark_in": None, "mark_out": None, "warnings": [],
    }


def test_the_same_inputs_load_the_saved_analysis(tmp_path):
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"video")
    settings = dict(DEFAULTS)
    sources = _Sources()
    first = analyze(_snapshot(media), settings, sources=sources, store=tmp_path)
    assert sources.calls == 1 and not first.get("restored")

    # A rule threshold does not change which images were examined.
    settings["mouth_min"] = 0.6
    hand = [{"frame": 3, "automatic": False}]
    again = analyze(_snapshot(media, hand), settings, sources=sources, store=tmp_path)
    assert sources.calls == 1
    assert again["restored"] is True
    assert again["manual_frames"] == [3]
    assert again["shots"] == first["shots"]
    assert saved_analysis(_snapshot(media), settings, tmp_path)["key"] == first["key"]

    # Examining other images, or a re-rendered media file, means analyzing again.
    settings["candidates_per_line"] = 2
    assert saved_analysis(_snapshot(media), settings, tmp_path) is None
    settings["candidates_per_line"] = DEFAULTS["candidates_per_line"]
    time.sleep(0.01)
    media.write_bytes(b"video, rendered again")
    assert saved_analysis(_snapshot(media), settings, tmp_path) is None


def test_no_key_when_a_media_file_is_missing(tmp_path):
    assert analysis_key(_snapshot(tmp_path / "gone.mp4"), dict(DEFAULTS)) is None


def test_time_left_reads_like_a_person():
    assert time_left(0, 10, 5) == ""
    assert time_left(10, 10, 5) == ""
    assert time_left(5, 10, 20) == "less than a minute left"
    assert time_left(100, 3100, 300) == "about 2 h 30 min left"
    assert time_left(100, 400, 300) == "about 15 min left"


def test_the_analyze_button_becomes_cancel_while_it_runs(qapp, monkeypatch):
    from vispa_mp.ui import MainWindow

    def slow(_snapshot, _settings, progress=None, cancel=None, store=None):
        while not cancel():
            time.sleep(0.01)
        raise InterruptedError("stopped")

    monkeypatch.setattr("vispa_mp.ui.analyze", slow)
    window = MainWindow(client=None)
    window.snapshot = {"fps": 24, "video_clips": []}
    window.analyze_button.click()
    assert window.analyze_button.text() == "Cancel"
    window.analyze_button.click()
    deadline = time.time() + 5
    while window.worker is not None and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    assert window.analyze_button.text() == "Analyze"
    assert "Analysis stopped" in window.status.text()


def test_silero_stays_on_the_processor(monkeypatch):
    import onnxruntime

    from vispa_mp.tags import providers
    monkeypatch.setattr(onnxruntime, "get_available_providers",
                        lambda: ["DmlExecutionProvider", "CPUExecutionProvider"])
    assert providers() == ["DmlExecutionProvider", "CPUExecutionProvider"]
    assert providers(gpu=False) == ["CPUExecutionProvider"]


def test_an_analysis_reports_its_steps_in_order(tmp_path):
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"video")
    seen = []
    analyze(_snapshot(media), dict(DEFAULTS), sources=_Sources(), progress=seen.append)
    steps = [value["step"] for value in seen]
    assert steps == sorted(steps) and steps[0] == 1 and steps[-1] == 5
    assert all(value["steps"] == 5 and 0 <= value["fraction"] <= 1 for value in seen)
    assert seen[0]["label"] == "Reading the video"


def test_steps_are_sent_at_most_ten_times_a_second():
    seen = []
    steps = Steps(seen.append)
    steps.start(2)
    for index in range(1000):
        steps.send(index / 1000)
    steps.send(1.0)
    assert len(seen) <= 4
    assert seen[-1]["fraction"] == 1.0


def test_the_footer_shows_the_step_then_hides(qapp):
    from vispa_mp.ui import MainWindow
    window = MainWindow(client=None)
    window._on_progress({"step": 5, "steps": 5, "label": "Recognizing the images", "fraction": 0.42,
                         "detail": "1240/3100 images on the graphics card", "left": "about 3 min left"})
    assert not window.progress.isHidden()
    assert window.progress.step_label.text() == "5/5  Recognizing the images"
    assert window.progress.percent.text() == "42 %"
    assert window.progress.left.text() == "about 3 min left"
    window._worker_finished()
    assert window.progress.isHidden()

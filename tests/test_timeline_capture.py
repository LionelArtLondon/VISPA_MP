"""Requested timeline stills are exact local source pictures, never near matches."""

from copy import deepcopy
import math
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image
import pytest

from vispa_mp.frames import ffmpeg_path
from vispa_mp.timeline_capture import capture_timeline_candidates


def context(tmp_path, *, start=86400, fps=24, source_fps=None, duration=240, source_start=40):
    source_fps = fps if source_fps is None else source_fps
    media = tmp_path / "Épisode & source.mkv"
    media.write_bytes(b"source file supplied to the fake exact extractor")
    clip = {"path": str(media), "start": start, "end": start + duration, "source_start": source_start,
            "source_end": source_start + round(duration * source_fps / fps), "fps": source_fps, "speed": 1}
    snapshot = {"fps": fps, "start_frame": start, "end_frame": start + duration,
                "start_timecode": "01:00:00:00", "video_clips": [clip], "audio_clips": [], "markers": []}
    analysis = {"fps": fps, "range": None, "timeline_range": [start, start + duration],
                "shots": [{"start": start, "end": start + duration, "frames": []}]}
    return snapshot, analysis


@pytest.fixture
def extractor(tmp_path, monkeypatch):
    calls = []

    def extract(frames, cache, binary=None, cancel=None):
        calls.append({"frames": deepcopy(frames), "cache": Path(cache), "binary": binary, "cancel": cancel})
        for candidate in frames:
            if cancel is not None and cancel():
                raise InterruptedError("capture cancelled")
            image = Path(cache) / f"{candidate['source_frame']}.jpg"
            image.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (64, 36), (candidate["source_frame"] % 255, 80, 120)).save(image)
            candidate["image"] = str(image)

    monkeypatch.setattr("vispa_mp.timeline_capture.extract_stills", extract)
    return calls


def test_exact_target_and_half_second_neighbours_use_source_frames_without_mutating_inputs(tmp_path, extractor):
    snapshot, analysis = context(tmp_path)
    before = deepcopy((snapshot, analysis))
    target = 86520
    candidates = capture_timeline_candidates(snapshot, analysis, target, tmp_path / "cache", binary="chosen-ffmpeg")
    assert [candidate["frame"] for candidate in candidates] == [86496, 86508, 86520, 86532, 86544]
    assert [candidate["source_frame"] for candidate in candidates] == [136, 148, 160, 172, 184]
    assert all(candidate["media"] == snapshot["video_clips"][0]["path"] for candidate in candidates)
    assert all(Path(candidate["image"]).is_file() for candidate in candidates)
    assert all(isinstance(candidate["sharpness"], float) and len(candidate["signature"]) == 64 for candidate in candidates)
    assert all(candidate["open_mouth"] == candidate["closed_mouth"] == candidate["face"] == 0.0
               for candidate in candidates)
    assert len(extractor) == 1
    assert extractor[0]["cache"] == tmp_path / "cache" / "timeline-capture"
    assert extractor[0]["binary"] == "chosen-ffmpeg"
    assert (snapshot, analysis) == before


@pytest.mark.parametrize("target", [86400, 86401, 86638, 86639])
def test_neighbours_are_clamped_to_the_source_clip_and_never_cross_an_edit(tmp_path, extractor, target):
    snapshot, analysis = context(tmp_path)
    result = capture_timeline_candidates(snapshot, analysis, target, tmp_path / "cache")
    assert 1 <= len(result) <= 5
    assert target in {candidate["frame"] for candidate in result}
    assert all(86400 <= candidate["frame"] < 86640 for candidate in result)
    assert all(40 <= candidate["source_frame"] < 280 for candidate in result)
    assert len({candidate["source_frame"] for candidate in result}) == len(result)


def test_analysis_in_out_and_decomposed_shot_bounds_both_limit_neighbours(tmp_path, extractor):
    snapshot, analysis = context(tmp_path, start=100, duration=100)
    analysis["range"] = [120, 160]
    analysis["shots"] = [{"start": 100, "end": 130, "frames": []}, {"start": 130, "end": 200, "frames": []}]
    result = capture_timeline_candidates(snapshot, analysis, 125, tmp_path / "cache")
    assert [candidate["frame"] for candidate in result] == [120, 125, 129]
    assert next(candidate for candidate in result if candidate["frame"] == 125)["source_frame"] == 65


@pytest.mark.parametrize("fps,source_fps,delta,expected", [
    (24, 25, 13, 53), (25, 24, 13, 52),
    (50, 25, 1, 40), (50, 25, 3, 41),
    (24000 / 1001, 30000 / 1001, 13, 56),
    (30000 / 1001, 24000 / 1001, 13, 50),
])
def test_different_rates_keep_the_picture_held_at_the_requested_timeline_position(
        tmp_path, extractor, fps, source_fps, delta, expected):
    snapshot, analysis = context(tmp_path, fps=fps, source_fps=source_fps, duration=1000)
    target = snapshot["start_frame"] + delta
    result = capture_timeline_candidates(snapshot, analysis, target, tmp_path / "cache")
    exact = next(candidate for candidate in result if candidate["frame"] == target)
    assert exact["source_frame"] == expected
    assert exact["frame"] == target


def test_raw_interlaced_source_positions_in_fields_are_normalized_before_mapping(tmp_path, extractor):
    snapshot, analysis = context(tmp_path, start=180000, fps=50, source_fps=25, duration=200)
    snapshot.update(interlaced=True, playback_fps=25)
    snapshot["video_clips"][0].update(source_start=100, source_end=300)
    result = capture_timeline_candidates(snapshot, analysis, 180001, tmp_path / "cache")
    exact = next(candidate for candidate in result if candidate["frame"] == 180001)
    assert exact["source_frame"] == 50
    assert snapshot["video_clips"][0]["source_start"] == 100


@pytest.mark.parametrize("speed", [None, "", 1, 1.0, 100, "100.0", "100%", "1"])
def test_normal_speed_representations_are_supported(tmp_path, extractor, speed):
    snapshot, analysis = context(tmp_path)
    snapshot["video_clips"][0]["speed"] = speed
    assert any(candidate["frame"] == 86520 for candidate in
               capture_timeline_candidates(snapshot, analysis, 86520, tmp_path / "cache"))


@pytest.mark.parametrize("speed", [0, -1, 2, 50, 200, 1.01, "unknown", "200%", True, {}, []])
def test_retimes_and_unverifiable_speeds_fail_before_any_source_extraction(tmp_path, extractor, speed):
    snapshot, analysis = context(tmp_path)
    snapshot["video_clips"][0]["speed"] = speed
    with pytest.raises(ValueError, match="Retimed"):
        capture_timeline_candidates(snapshot, analysis, 86520, tmp_path / "cache")
    assert extractor == []


@pytest.mark.parametrize("frame", [True, False, 86520.0, "86520", None, -(2 ** 31) - 1, 2 ** 31])
def test_requested_position_must_be_an_exact_integer_frame(tmp_path, extractor, frame):
    snapshot, analysis = context(tmp_path)
    with pytest.raises(ValueError, match="integer timeline frame"):
        capture_timeline_candidates(snapshot, analysis, frame, tmp_path / "cache")
    assert extractor == []


@pytest.mark.parametrize("change,message", [
    ("gap", "gap"), ("overlap", "overlapping"), ("offline", "offline or missing"),
    ("outside", "outside the analyzed range"), ("no shot", "analyzed shot"),
    ("overlapping shots", "analyzed shot"), ("span", "inconsistent source span"),
    ("missing source in", "source In/Out"), ("negative source in", "source In/Out"),
    ("timeline rate", "frame rate"), ("source rate", "frame rate"), ("analysis rate", "frame rates differ"),
])
def test_unverifiable_mapping_is_rejected_with_an_actionable_error(tmp_path, extractor, change, message):
    snapshot, analysis = context(tmp_path)
    clip = snapshot["video_clips"][0]
    if change == "gap":
        clip["end"] = 86500
    elif change == "overlap":
        snapshot["video_clips"].append(deepcopy(clip))
    elif change == "offline":
        Path(clip["path"]).unlink()
    elif change == "outside":
        analysis["range"] = [86400, 86520]
    elif change == "no shot":
        analysis["shots"] = []
    elif change == "overlapping shots":
        analysis["shots"].append(deepcopy(analysis["shots"][0]))
    elif change == "span":
        clip["source_end"] -= 10
    elif change == "missing source in":
        clip.pop("source_start")
    elif change == "negative source in":
        clip["source_start"] = -1
    elif change == "timeline rate":
        snapshot["fps"] = float("nan")
    elif change == "source rate":
        clip["fps"] = False
    else:
        analysis["fps"] = 25
    with pytest.raises(ValueError, match=message):
        capture_timeline_candidates(snapshot, analysis, 86520, tmp_path / "cache")
    assert extractor == []


def test_neighbours_stop_before_a_nearby_ambiguous_transition(tmp_path, extractor):
    snapshot, analysis = context(tmp_path, start=100, duration=100)
    snapshot["video_clips"].append({**snapshot["video_clips"][0], "start": 140, "end": 150,
                                    "source_start": 50, "source_end": 60})
    result = capture_timeline_candidates(snapshot, analysis, 135, tmp_path / "cache")
    assert max(candidate["frame"] for candidate in result) == 139
    assert all(candidate["frame"] < 140 for candidate in result)


def test_existing_exact_source_candidates_are_reused_without_ffmpeg_or_model_loading(tmp_path, extractor, monkeypatch):
    snapshot, analysis = context(tmp_path)
    first = capture_timeline_candidates(snapshot, analysis, 86520, tmp_path / "cache")
    first[2]["open_mouth"] = 0.9
    analysis["shots"][0]["frames"] = deepcopy(first)
    before = deepcopy(analysis)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Every exact source image is already available; no extraction or inference is needed")

    monkeypatch.setattr("vispa_mp.timeline_capture.extract_stills", forbidden)
    result = capture_timeline_candidates(snapshot, analysis, 86520, tmp_path / "cache", binary="not installed")
    assert result == first
    assert result[2]["open_mouth"] == 0.9
    assert all(item is not old for item, old in zip(result, analysis["shots"][0]["frames"]))
    assert analysis == before


def test_an_odd_interlaced_field_reuses_the_same_picture_but_keeps_the_requested_frame(tmp_path, extractor, monkeypatch):
    snapshot, analysis = context(tmp_path, start=180000, fps=50, source_fps=25, duration=2)
    image = tmp_path / "field-picture.jpg"
    Image.new("RGB", (64, 36), "blue").save(image)
    analysis["shots"][0]["frames"] = [{"frame": 180000, "source_frame": 40,
                                      "media": snapshot["video_clips"][0]["path"], "image": str(image)}]
    result = capture_timeline_candidates(snapshot, analysis, 180001, tmp_path / "cache")
    assert len(result) == 1 and extractor == []
    assert result[0]["frame"] == 180001 and result[0]["source_frame"] == 40
    assert result[0]["image"] == str(image)


@pytest.mark.parametrize("mismatch", ["source", "media", "missing image", "broken image"])
def test_a_nearby_or_invalid_cached_image_never_substitutes_for_the_requested_source(tmp_path, extractor, mismatch):
    snapshot, analysis = context(tmp_path)
    image = tmp_path / "cached.jpg"
    Image.new("RGB", (64, 36), "blue").save(image)
    cached = {"frame": 86520, "source_frame": 160, "media": snapshot["video_clips"][0]["path"],
              "image": str(image), "open_mouth": 0.99}
    if mismatch == "source":
        cached["source_frame"] = 161
    elif mismatch == "media":
        cached["media"] = str(tmp_path / "other.mkv")
    elif mismatch == "missing image":
        image.unlink()
    else:
        image.write_bytes(b"broken picture")
    analysis["shots"][0]["frames"] = [cached]
    exact = next(candidate for candidate in capture_timeline_candidates(
        snapshot, analysis, 86520, tmp_path / "cache") if candidate["frame"] == 86520)
    assert exact["source_frame"] == 160
    assert exact["image"] != str(image)
    assert exact["open_mouth"] == 0.0


def test_missing_exact_target_after_extraction_is_an_error_even_when_neighbours_exist(tmp_path, monkeypatch):
    snapshot, analysis = context(tmp_path)

    def omit_exact(frames, cache, **_kwargs):
        for candidate in frames:
            if candidate["frame"] != 86520:
                path = tmp_path / f"neighbour-{candidate['frame']}.jpg"
                Image.new("RGB", (64, 36), "green").save(path)
                candidate["image"] = str(path)

    monkeypatch.setattr("vispa_mp.timeline_capture.extract_stills", omit_exact)
    with pytest.raises(RuntimeError, match="86520.*missing or unreadable"):
        capture_timeline_candidates(snapshot, analysis, 86520, tmp_path / "cache")


def test_capture_can_be_cancelled_before_work_or_during_extraction(tmp_path, extractor):
    snapshot, analysis = context(tmp_path)
    before = deepcopy((snapshot, analysis))
    with pytest.raises(InterruptedError, match="stopped"):
        capture_timeline_candidates(snapshot, analysis, 86520, tmp_path / "cache", cancel=lambda: True)
    assert extractor == []
    checks = []

    def cancel():
        checks.append(True)
        return len(checks) >= 4

    with pytest.raises(InterruptedError):
        capture_timeline_candidates(snapshot, analysis, 86520, tmp_path / "cache", cancel=cancel)
    assert len(extractor) == 1 and extractor[0]["cancel"] is cancel
    assert (snapshot, analysis) == before


try:
    FFMPEG = ffmpeg_path()
except RuntimeError:
    FFMPEG = None


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")
def test_real_ffmpeg_extracts_the_requested_trimmed_source_picture_at_an_hour_offset(tmp_path):
    snapshot, analysis = context(tmp_path, duration=80)
    video = Path(snapshot["video_clips"][0]["path"])
    frames = np.stack([np.full((36, 64), number, dtype=np.uint8) for number in range(150)])
    completed = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
         "-s", "64x36", "-r", "24", "-i", "pipe:0", "-c:v", "ffv1", "-pix_fmt", "gray", str(video)],
        input=frames.tobytes(), capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    original = video.read_bytes()
    result = capture_timeline_candidates(snapshot, analysis, 86430, tmp_path / "cache", binary=FFMPEG)
    assert len(result) == 5
    exact = next(candidate for candidate in result if candidate["frame"] == 86430)
    assert exact["source_frame"] == 70
    for candidate in result:
        with Image.open(candidate["image"]) as image:
            assert image.width == 448
            level = float(np.asarray(image.convert("L")).mean())
        assert math.isclose(level, candidate["source_frame"], abs_tol=2.5), candidate
    assert video.read_bytes() == original

"""Long reframings reach real candidate selection, profiles and timeline safeguards."""

from copy import deepcopy

import numpy as np
import pytest

from vispa_mp.analyze import analysis_key, analyze, saved_analysis
from vispa_mp.learning_model import FEATURE_NAMES, train_profile
from vispa_mp.preset import DEFAULTS
from vispa_mp.rules import propose


def _strip(fps=24, seconds=12):
    # A gradual exposure change over a textured drawing has no hard cut. Broad
    # texture avoids abrupt histogram-bin crossings of a uniformly grey image.
    texture = np.random.default_rng(42).integers(30, 101, (36, 64, 1))
    texture = np.repeat(texture, 3, axis=2)
    pictures = []
    for index in range(round(fps * seconds)):
        level = round(100 * min(1, max(0, (index / fps - 3) / 6)))
        pictures.append((texture + level).astype(np.uint8))
    return np.stack(pictures)


class _Sources:
    def __init__(self, strip):
        self.strip = strip
        self.calls = 0
        self.scored = []

    def filmstrip(self, _clip):
        self.calls += 1
        return self.strip

    def score(self, frame):
        self.scored.append(frame["frame"])
        return {"motion_blur": 0, "open_mouth": 0.1, "closed_mouth": 0.8,
                "face": 0.9, "from_behind": 0, "group": 0.1, "solo": 0.8,
                "expression": 0.3}


def _settings(**changes):
    # A broad page allowance isolates decomposition from optional density and
    # action rules: one end-of-shot image should survive for every new framing.
    return dict(DEFAULTS, **{
        "split_long_shots": True, "long_shot_seconds": 4.3,
        "global_markers_enabled": False, "action_extras": 0,
        "core_page_target": 0, "core_page_min": 0, "core_page_max": 100,
        "total_page_min": 0, "total_page_max": 100,
        "target_pages_min": 1, "target_pages_max": 1, "episode_minutes": 0,
        "use_in_out": False, **changes,
    })


def _snapshot(media="episode.mp4", source_fps=24, timeline_fps=24, start=1000):
    clip = {"name": "episode", "path": str(media), "fps": source_fps,
            "start": start, "end": start + round(12 * timeline_fps),
            "source_start": 240, "source_end": 240 + round(12 * source_fps), "speed": 1}
    return {"fps": timeline_fps, "start_frame": start, "end_frame": clip["end"],
            "start_timecode": "01:00:00:00", "drop": False,
            "timeline_name": "Long moving framing", "project_name": "Test chapter",
            "timeline_identity": {"project_id": "long-project", "timeline_id": "long-timeline"},
            "video_clips": [clip], "audio_clips": [], "markers": [],
            "mark_in": None, "mark_out": None, "warnings": []}


def _assert_each_framing_has_a_proposal(analysis, settings, profile=None):
    proposals = propose(analysis, settings, profile=profile)["proposals"]
    assert len(analysis["shots"]) >= 2
    assert len(proposals) == len(analysis["shots"])
    for shot in analysis["shots"]:
        picks = [item for item in proposals if shot["start"] <= item["frame"] < shot["end"]]
        assert len(picks) == 1
        # The existing end preference now applies to each framing, rather than
        # solely the end of the original twelve-second shot.
        end_region = shot["start"] + (1 - settings["end_fraction"]) * (shot["end"] - shot["start"])
        assert picks[0]["frame"] >= end_region
        assert picks[0]["frame"] in {frame["frame"] for frame in shot["frames"]}
    return proposals


def test_analyze_scores_and_proposes_an_end_image_for_each_long_reframing():
    settings = _settings()
    sources = _Sources(_strip())
    snapshot = _snapshot()
    analysis = analyze(snapshot, settings, sources=sources)
    proposals = _assert_each_framing_has_a_proposal(analysis, settings)
    assert len(sources.scored) == sum(len(shot["frames"]) for shot in analysis["shots"])
    assert all(item["frame"] in sources.scored for item in proposals)
    parent_start, parent_end = snapshot["video_clips"][0]["start"], snapshot["video_clips"][0]["end"]
    assert all((shot["parent_start"], shot["parent_end"]) == (parent_start, parent_end)
               for shot in analysis["shots"])
    assert analysis["shots"][0]["opening"] is True
    for shot in analysis["shots"][1:]:
        assert shot["reframed"] is True
        assert not shot["opening"]
        assert all(shot[key] == 0 for key in ("cut_grey", "cut_colour", "cut_shape"))


@pytest.mark.parametrize("changes", [{"split_long_shots": False}, {"long_shot_seconds": 20.0}])
def test_disabled_or_ineligible_decomposition_keeps_one_shot_and_one_marker(changes):
    settings = _settings(**changes)
    analysis = analyze(_snapshot(), settings, sources=_Sources(_strip()))
    assert len(analysis["shots"]) == 1
    assert len(propose(analysis, settings)["proposals"]) == 1


def test_both_decomposition_settings_invalidate_the_analysis_cache(tmp_path):
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"fake media measured through the test source")
    snapshot, settings = _snapshot(media), _settings()
    sources = _Sources(_strip())
    first = analyze(snapshot, settings, sources=sources, store=tmp_path / "cache")
    assert saved_analysis(snapshot, settings, tmp_path / "cache")["key"] == first["key"]
    assert analysis_key(snapshot, _settings(mouth_min=0.7)) == first["key"]
    for changes in ({"split_long_shots": False}, {"long_shot_seconds": 20.0}):
        changed = _settings(**changes)
        assert analysis_key(snapshot, changed) != first["key"]
        assert saved_analysis(snapshot, changed, tmp_path / "cache") is None
        restored = analyze(snapshot, changed, sources=sources, store=tmp_path / "cache")
        assert len(restored["shots"]) == 1
        assert not restored.get("restored")
    assert sources.calls == 3


@pytest.mark.parametrize("source_fps,timeline_fps", [(24, 25), (24, 50)])
def test_reframing_keeps_source_alignment_and_in_out_filtering(source_fps, timeline_fps):
    snapshot = _snapshot(source_fps=source_fps, timeline_fps=timeline_fps)
    clip = snapshot["video_clips"][0]
    snapshot["mark_in"] = clip["start"] + round(2 * timeline_fps)
    snapshot["mark_out"] = clip["end"] - round(2 * timeline_fps)
    analysis = analyze(snapshot, _settings(use_in_out=True), sources=_Sources(_strip(source_fps)))
    assert analysis["range"] == [snapshot["mark_in"], snapshot["mark_out"]]
    assert len(analysis["shots"]) >= 2
    for shot in analysis["shots"]:
        assert shot["end"] > snapshot["mark_in"] and shot["start"] < snapshot["mark_out"]
        assert clip["start"] <= shot["start"] < shot["end"] <= clip["end"]
        assert (shot["parent_start"], shot["parent_end"]) == (clip["start"], clip["end"])
        for frame in shot["frames"]:
            assert clip["source_start"] <= frame["source_frame"] < clip["source_end"]
            expected = clip["start"] + (frame["source_frame"] - clip["source_start"]) * timeline_fps / source_fps
            assert frame["frame"] == round(expected)
            assert shot["start"] <= frame["frame"] < shot["end"]


def test_a_manual_marker_still_protects_the_whole_original_shot():
    snapshot = _snapshot()
    manual = snapshot["video_clips"][0]["start"] + 24
    snapshot["markers"] = [{"frame": manual, "automatic": False}]
    settings = _settings()
    analysis = analyze(snapshot, settings, sources=_Sources(_strip()))
    assert len(analysis["shots"]) >= 2
    assert analysis["manual_frames"] == [manual]
    assert propose(analysis, settings)["proposals"] == []
    unlocked = propose(analysis, _settings(skip_marked_shots=False))["proposals"]
    assert len(unlocked) >= 2
    assert all(item["frame"] != manual for item in unlocked)


def test_a_personal_profile_uses_each_reframing_without_mutating_the_analysis():
    # Train a real small profile rather than injecting cached personal scores.
    samples = []
    for number, sharpness, roles in ((10, 0.2, []), (50, 0.8, ["core"])):
        features = [0.0] * len(FEATURE_NAMES)
        features[FEATURE_NAMES.index("sharpness")] = sharpness
        samples.append({"frame": number, "shot": 0, "features": features, "roles": roles})
    profile = train_profile([{"kind": "vispa-mp-reference", "version": 1,
                              "id": "long-reference", "name": "Reference chapter",
                              "group_id": "long-reference", "samples": samples}], "Reframing test")
    settings = _settings()
    analysis = analyze(_snapshot(), settings, sources=_Sources(_strip()))
    before = deepcopy(analysis)
    _assert_each_framing_has_a_proposal(analysis, settings, profile=profile)
    assert analysis == before

"""Voice changes reach sampling, selection, portable reviews and learning."""

from copy import deepcopy
import hashlib
import math

import numpy as np
from PIL import Image
import pytest

from vispa_mp.analyze import analysis_key, analyze, refresh_utterances, saved_analysis
from vispa_mp.learning_data import import_timeline_reference
from vispa_mp.learning_model import FEATURE_NAMES, load_profile, save_profile, train_profile
from vispa_mp.markers import CORE
from vispa_mp.preset import DEFAULTS
from vispa_mp.project import load_project, save_project
from vispa_mp.rules import propose


FPS = 24
SECONDS = 6
START = 86400


class Sources:
    """Real frame measurements and fake deterministic visual/audio models."""

    def __init__(self, tmp_path):
        x, y = np.arange(64)[None, :], np.arange(36)[:, None]
        picture = np.clip(120 + 55 * np.sin(x / 2) + 35 * np.cos(y / 3), 0, 255).astype(np.uint8)
        self.picture = np.repeat(picture[..., None], 3, axis=2)
        self.strip = np.stack([self.picture] * (FPS * SECONDS))
        self.audio = np.arange(16_000 * SECONDS, dtype=np.float32)
        self.audio_calls = []
        self.probability_calls = []
        self.scored = []
        self.image = tmp_path / "measured.jpg"
        Image.fromarray(self.picture).save(self.image)

    def filmstrip(self, _clip):
        return self.strip

    def waveform(self, clip, fps):
        self.audio_calls.append((dict(clip), fps))
        return self.audio

    def probabilities(self, audio):
        self.probability_calls.append(audio.copy())
        return [0.95] * math.ceil(len(audio) / 512)

    def score_many(self, frames):
        for frame in frames:
            # Every two-second reply contains a good speaking pose, followed
            # by a closed mouth near its end. The final shot image is closed.
            opened = 8 <= int(frame["source_frame"]) % (FPS * 2) <= 32
            frame.update(open_mouth=0.9 if opened else 0.05,
                         closed_mouth=0.05 if opened else 0.9, face=0.9,
                         from_behind=0.0, motion_blur=0.0, expression=0.3,
                         group=0.05, solo=0.9, image=str(self.image))
            self.scored.append(deepcopy(frame))


class DialogueSources(Sources):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.dialogue_calls = []

    def dialogue(self, audio):
        self.dialogue_calls.append(audio.copy())
        changes = [{"time": 2.0, "confidence": 0.9}, {"time": 4.0, "confidence": 0.95}]
        return {"speaker_changes": changes,
                "dialogue_status": {"state": "ready", "engine": "pyannote-segmentation-3.0",
                                    "detail": "Two stable voice changes.", "changes": len(changes)}}


def snapshot(tmp_path):
    media = tmp_path / "chapter.mp4"
    media.write_bytes(b"source identity measured through test adapters")
    clip = {"path": str(media), "name": "Chapter", "start": START, "end": START + FPS * SECONDS,
            "source_start": 0, "source_end": FPS * SECONDS, "fps": FPS, "speed": 1}
    return {"fps": FPS, "start_frame": START, "end_frame": clip["end"],
            "start_timecode": "01:00:00:00", "drop": False,
            "timeline_name": "Dialogue", "project_name": "Avatar chapter",
            "timeline_identity": {"project_id": "project-dialogue", "timeline_id": "timeline-dialogue"},
            "video_clips": [clip], "audio_clips": [dict(clip)], "markers": [],
            "mark_in": None, "mark_out": None, "warnings": []}


def options(**changes):
    return dict(DEFAULTS, **{**dict(global_markers_enabled=False, action_extras=0,
                                   split_long_shots=False, use_in_out=False,
                                   speech_pad_ms=0, core_page_target=0,
                                   target_pages_min=1, target_pages_max=1, episode_minutes=0,
                                   core_page_min=0, core_page_max=16, total_page_min=0, total_page_max=24),
                             **changes})


def avatar_profile():
    # Train an actual legacy-compatible personal ranker that prefers late poses.
    references = []
    for group in ("training-chapter", "validation-chapter"):
        samples = []
        for index, phase in enumerate((0.1, 0.9)):
            features = [0.5] * len(FEATURE_NAMES)
            features[FEATURE_NAMES.index("shot_phase")] = phase
            features[FEATURE_NAMES.index("expression")] = 0.1 + index * 0.8
            samples.append({"frame": 10 + index * 60, "shot": 0, "features": features,
                            "roles": ["core"] if index else []})
        references.append({"kind": "vispa-mp-reference", "version": 1,
                           "id": group, "name": group, "group_id": group,
                           "feature_names": list(FEATURE_NAMES), "samples": samples})
    return train_profile(references, "Avatar dialogue test", holdout_group="validation-chapter")


@pytest.mark.parametrize("personal", [False, True])
def test_continuous_speech_changes_supply_a_good_mouth_in_each_turn_for_standard_and_avatar(tmp_path, personal):
    source = DialogueSources(tmp_path)
    measured = analyze(snapshot(tmp_path), options(), sources=source)
    assert len(measured["utterances"]) == 3
    assert [turn["start"] for turn in measured["utterances"]] == [START, START + 48, START + 96]
    assert all(turn["source"] == "speaker_change" and "speaker" not in turn for turn in measured["utterances"])
    candidates = [frame for shot in measured["shots"] for frame in shot["frames"]]
    assert all(any(turn["start"] <= frame["frame"] < turn["end"] and frame["open_mouth"] == 0.9
                   for frame in candidates) for turn in measured["utterances"])
    before = deepcopy(measured)
    result = propose(measured, options(), profile=avatar_profile() if personal else None)
    for turn in measured["utterances"]:
        chosen = [item for item in result["proposals"] if turn["start"] <= item["frame"] < turn["end"]]
        assert any(item.get("speech_quality_ok") and item.get("dialogue_turn") == turn["start"]
                   for item in chosen)
    assert all(item["mouth"] == 0.9 for item in result["proposals"])
    assert all("dialogue_speaker" not in item for item in result["proposals"])
    assert measured == before
    assert len(source.dialogue_calls) == 1


def test_saved_project_recalculates_the_stored_turns_without_audio_or_model_access(tmp_path, monkeypatch):
    source = DialogueSources(tmp_path)
    data, settings = snapshot(tmp_path), options()
    measured = analyze(data, settings, sources=source)
    proposals = propose(measured, settings)["proposals"]
    path = tmp_path / "dialogue.vispamp"
    save_project(path, data, measured, proposals, settings, {})
    restored = load_project(path, tmp_path / "reloaded")

    def no_inference(*_args, **_kwargs):
        pytest.fail("Recalculate must use saved dialogue measures without inference.")

    monkeypatch.setattr("vispa_mp.dialogue.SpeakerChanges", no_inference)
    refreshed = refresh_utterances(restored["analysis"], restored["settings"])
    assert refreshed == measured["utterances"]
    restored["analysis"]["utterances"] = refreshed
    recalculated = propose(restored["analysis"], restored["settings"])["proposals"]
    assert [(item["frame"], item.get("dialogue_turn")) for item in recalculated] == [
        (item["frame"], item.get("dialogue_turn")) for item in proposals]
    assert restored["analysis"]["speech_tracks"] == measured["speech_tracks"]


def test_existing_avatar_profile_remains_loadable_and_uses_new_turn_boundaries(tmp_path):
    profile = avatar_profile()
    assert "role_assignment" not in profile
    path = tmp_path / "avatar.json"
    save_profile(profile, path)
    restored = load_profile(path)
    measured = analyze(snapshot(tmp_path), options(), sources=DialogueSources(tmp_path))
    proposed = propose(measured, options(), profile=restored)["proposals"]
    assert {item["dialogue_turn"] for item in proposed if item.get("speech_quality_ok")} == {
        turn["start"] for turn in measured["utterances"]}


def test_installing_the_voice_model_invalidates_the_cached_analysis(tmp_path, monkeypatch):
    from vispa_mp import models_setup

    voice_model = tmp_path / "voice-model.onnx"
    weights = b"model bytes" * 200
    monkeypatch.setattr(models_setup, "SPEAKER_SEGMENTATION", voice_model)
    monkeypatch.setattr(models_setup, "SPEAKER_SEGMENTATION_SHA256", hashlib.sha256(weights).hexdigest())
    data, settings = snapshot(tmp_path), options()
    assert not models_setup.dialogue_ready()
    first = analyze(data, settings, sources=DialogueSources(tmp_path), store=tmp_path / "cache")
    assert saved_analysis(data, settings, tmp_path / "cache")["key"] == first["key"]
    assert analysis_key(data, options(mouth_min=0.6)) == first["key"]
    voice_model.write_bytes(weights)
    assert models_setup.dialogue_ready()
    assert analysis_key(data, settings) != first["key"]
    assert saved_analysis(data, settings, tmp_path / "cache") is None


def test_speech_without_a_dialogue_adapter_keeps_the_legacy_single_turn(tmp_path):
    source = Sources(tmp_path)
    measured = analyze(snapshot(tmp_path), options(), sources=source)
    assert len(measured["utterances"]) == 1
    assert "speaker_changes" not in measured["speech_tracks"][0]
    assert "source" not in measured["utterances"][0]
    assert refresh_utterances(measured, options()) == measured["utterances"]
    assert propose(measured, options())["proposals"]


def test_no_audio_does_not_call_the_speaker_model_or_invent_a_dialogue(tmp_path):
    source = DialogueSources(tmp_path)
    data = snapshot(tmp_path)
    data["audio_clips"] = []
    measured = analyze(data, options(), sources=source)
    assert measured["speech_tracks"] == measured["utterances"] == []
    assert source.probability_calls == source.dialogue_calls == source.audio_calls == []
    assert propose(measured, options())["proposals"]


def test_reference_in_out_voice_changes_use_the_cropped_audio_origin(tmp_path):
    source = DialogueSources(tmp_path)
    data = snapshot(tmp_path)
    data.update(mark_in=START + 24, mark_out=START + 120,
                markers=[{"frame": START + 84, "color": CORE, "automatic": False}])
    reference = import_timeline_reference(data, options(), tmp_path / "cache", sources=source, use_in_out=True)
    assert len(source.dialogue_calls) == 1
    cropped = source.dialogue_calls[0]
    assert len(cropped) == 64_000 and cropped[0] == 16_000 and cropped[-1] == 79_999
    assert np.array_equal(cropped, source.probability_calls[0])
    selected = next(sample for sample in reference["samples"] if sample["roles"])
    assert selected["frame"] == START + 84
    assert selected["features"][FEATURE_NAMES.index("speech")] == 1
    assert selected["features"][FEATURE_NAMES.index("speech_phase")] == pytest.approx(0.25)
    assert reference["source"]["range"] == [START + 24, START + 120]


def test_analyze_retries_a_transient_voice_engine_failure_instead_of_loading_it_forever(tmp_path):
    data, settings = snapshot(tmp_path), options()
    source = DialogueSources(tmp_path)
    source.dialogue = lambda _audio: {"speaker_changes": [], "dialogue_status": {
        "state": "failed", "engine": "pyannote-segmentation-3.0", "changes": 0, "detail": "Temporary inference failure."}}
    first = analyze(data, settings, sources=source, store=tmp_path / "cache")
    assert first["speech_tracks"][0]["dialogue_status"]["state"] == "failed"
    assert saved_analysis(data, settings, tmp_path / "cache") is None
    healthy = DialogueSources(tmp_path)
    again = analyze(data, settings, sources=healthy, store=tmp_path / "cache")
    assert len(healthy.dialogue_calls) == 1
    assert len(again["utterances"]) == 3
    assert not again.get("restored")
    assert saved_analysis(data, settings, tmp_path / "cache")["key"] == again["key"]


def test_reference_import_records_and_reports_the_speech_only_fallback(tmp_path):
    source = DialogueSources(tmp_path)
    source.dialogue = lambda _audio: {"speaker_changes": [], "dialogue_status": {
        "state": "unavailable", "engine": "pyannote-segmentation-3.0", "changes": 0,
        "detail": "Voice-change model missing; speech timing remains available."}}
    data = snapshot(tmp_path)
    data["markers"] = [{"frame": START + 24, "color": CORE, "automatic": False}]
    progress = []
    reference = import_timeline_reference(data, options(), tmp_path / "cache", sources=source, progress=progress.append)
    provenance = reference["source"]["dialogue_analysis"]
    assert provenance["tracks"] == 1 and provenance["ready_tracks"] == 0
    assert provenance["changes"] == 0
    assert any("Voice-change model missing" in message for message in progress)
    assert "Voice-change model missing" in provenance["warnings"][0]

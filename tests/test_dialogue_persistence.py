"""Saved voice-change timing survives review reloads and rejects bad metadata."""

from copy import deepcopy

import pytest

from tests.test_project import _review, _rewrite
from vispa_mp.project import load_project, save_project


def _dialogue_review(tmp_path):
    review = _review(tmp_path)
    start = review["analysis"]["timebase"]["start_frame"]
    review["analysis"]["speech_tracks"] = [{
        "start": start, "end": start + 24, "probs": [0.9] * 32,
        "speaker_changes": [{"time": 0.5, "confidence": 0.85}],
        "dialogue_status": {"state": "ready", "engine": "pyannote/segmentation-3.0",
                            "detail": "One stable voice change.", "changes": 1},
    }]
    review["analysis"]["utterances"] = [
        {"start": start, "end": start + 12, "source": "speaker_change", "turn_id": f"{start}:0"},
        {"start": start + 12, "end": start + 24, "source": "speaker_change",
         "turn_id": f"{start}:1", "speaker": "anonymous-voice", "confidence": 0.85},
    ]
    review["proposals"][0].update(dialogue_turn=1, dialogue_speaker="anonymous-voice")
    return review


def _load_changed(tmp_path, edit):
    path = tmp_path / "dialogue.vispamp"
    save_project(path, **_dialogue_review(tmp_path))
    _rewrite(path, edit=edit)
    return load_project(path, tmp_path / "loaded")


def test_voice_change_seconds_and_mapped_turns_survive_portable_project_roundtrip(tmp_path):
    review = _dialogue_review(tmp_path)
    original = deepcopy(review)
    path = tmp_path / "dialogue.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "loaded")
    assert review == original
    for key in ("speech_tracks", "utterances"):
        assert restored["analysis"][key] == review["analysis"][key]
    assert restored["proposals"][0]["dialogue_turn"] == 1
    assert restored["proposals"][0]["dialogue_speaker"] == "anonymous-voice"
    assert restored["analysis"]["speech_tracks"][0]["speaker_changes"][0]["time"] == 0.5


def test_legacy_project_without_dialogue_metadata_still_loads(tmp_path):
    review = _review(tmp_path)
    review["analysis"]["speech_tracks"] = [{"start": 86400, "end": 86424, "probs": [0.9] * 32}]
    review["analysis"]["utterances"] = [{"start": 86400, "end": 86424}]
    path = tmp_path / "legacy.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "loaded")
    assert restored["analysis"]["speech_tracks"] == review["analysis"]["speech_tracks"]
    assert restored["analysis"]["utterances"] == review["analysis"]["utterances"]


@pytest.mark.parametrize("state", ["ready", "unavailable", "failed"])
def test_no_change_and_fallback_statuses_are_portable_without_fake_speaker_labels(tmp_path, state):
    review = _dialogue_review(tmp_path)
    track = review["analysis"]["speech_tracks"][0]
    track["speaker_changes"] = []
    track["dialogue_status"].update(state=state, changes=0, detail="Voice activity remains available.")
    review["analysis"]["utterances"] = [{"start": 86400, "end": 86424, "source": "voice_activity"}]
    path = tmp_path / "fallback.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "loaded")
    assert restored["analysis"]["speech_tracks"][0]["dialogue_status"] == track["dialogue_status"]
    assert "speaker" not in restored["analysis"]["utterances"][0]


@pytest.mark.parametrize("changes", [None, "0.5", [None], [{}], [{"time": 0.5}]])
def test_loading_rejects_unusable_voice_change_lists(tmp_path, changes):
    with pytest.raises(ValueError, match="voice change|dialogue"):
        _load_changed(tmp_path, lambda data: data["analysis"]["speech_tracks"][0].update(speaker_changes=changes))


@pytest.mark.parametrize("time", [None, True, -0.1, 0, 1, 86400.5, float("nan"), float("inf"), 10 ** 400])
def test_loading_rejects_invalid_or_out_of_clip_voice_change_clocks(tmp_path, time):
    with pytest.raises(ValueError, match="voice change|numeric value"):
        _load_changed(tmp_path, lambda data: data["analysis"]["speech_tracks"][0]["speaker_changes"][0].update(time=time))


@pytest.mark.parametrize("confidence", [None, True, -0.01, 1.01, float("nan"), float("inf")])
def test_loading_rejects_invalid_change_support(tmp_path, confidence):
    with pytest.raises(ValueError, match="voice change|numeric value"):
        _load_changed(tmp_path, lambda data: data["analysis"]["speech_tracks"][0]["speaker_changes"][0].update(confidence=confidence))


@pytest.mark.parametrize("values", [
    {"state": "silent"}, {"state": "failed"}, {"changes": False}, {"changes": -1}, {"changes": 2},
    {"engine": ""}, {"engine": "x" * 257}, {"engine": "invalid\nengine"},
    {"detail": None}, {"detail": "x" * 4097},
])
def test_loading_rejects_inconsistent_dialogue_statuses(tmp_path, values):
    with pytest.raises(ValueError, match="dialogue analysis status"):
        _load_changed(tmp_path, lambda data: data["analysis"]["speech_tracks"][0]["dialogue_status"].update(values))


@pytest.mark.parametrize("values", [
    {"source": "transcription"}, {"source": None}, {"turn_id": ""}, {"turn_id": 1},
    {"speaker": False}, {"speaker": "x" * 257}, {"speaker": "invalid\nlabel"},
    {"confidence": True}, {"confidence": -0.1}, {"confidence": 1.1},
    {"end": 86400},
])
def test_loading_rejects_unreadable_mapped_dialogue_metadata(tmp_path, values):
    with pytest.raises(ValueError, match="dialogue interval"):
        _load_changed(tmp_path, lambda data: data["analysis"]["utterances"][0].update(values))


@pytest.mark.parametrize("values", [
    {"dialogue_turn": True}, {"dialogue_turn": "1"}, {"dialogue_turn": 2 ** 31},
    {"dialogue_speaker": None}, {"dialogue_speaker": ""}, {"dialogue_speaker": "bad\nlabel"},
])
def test_loading_rejects_unreadable_proposal_dialogue_metadata(tmp_path, values):
    with pytest.raises(ValueError, match="dialogue turn|dialogue voice label"):
        _load_changed(tmp_path, lambda data: data["proposals"][0].update(values))


def test_voice_changes_cannot_be_saved_on_an_empty_audio_interval(tmp_path):
    review = _dialogue_review(tmp_path)
    track = review["analysis"]["speech_tracks"][0]
    track["end"] = track["start"]
    with pytest.raises(ValueError, match="voice change"):
        save_project(tmp_path / "empty-audio.vispamp", **review)

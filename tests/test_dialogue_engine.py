"""Real inference uses the same bounded windows and clocks as synthetic checks."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from vispa_mp.dialogue import ENGINE, SpeakerChanges, _stable_changes, dialogue_summary
from vispa_mp.preset import DEFAULTS
from vispa_mp.speech import dialogue_turns, map_turns, turns_from_probs


def output(labels):
    values = np.full((len(labels), 7), -12, dtype=np.float32)
    values[np.arange(len(labels)), labels] = 0
    return values


def test_different_stable_voices_split_even_without_a_silence():
    result = _stable_changes(output([1] * 100 + [2] * 100), 0.02, 7.0)
    assert len(result) == 1 and result[0]["time"] == 9.0
    assert 0.9 < result[0]["confidence"] <= 1


@pytest.mark.parametrize("labels", [[1] * 100 + [0] * 20 + [1] * 100,
                                    [1] * 100 + [2] * 3 + [1] * 100,
                                    [4] * 100, [0] * 100])
def test_silence_overlap_and_brief_fluctuations_are_not_another_speaker(labels):
    assert _stable_changes(output(labels), 0.02, 0) == []


def test_uncertain_handoff_uses_the_new_voice_onset_instead_of_the_ambiguous_gap_middle():
    labels = [1] * 100 + [0] * 45 + [2] * 100
    result = _stable_changes(output(labels), 0.02, 0)
    assert result[0]["time"] == pytest.approx(2.9)


def test_a_long_unvoiced_gap_does_not_need_a_voice_change():
    assert _stable_changes(output([1] * 100 + [0] * 100 + [2] * 100), 0.02, 0) == []


class Session:
    def __init__(self):
        self.calls = 0
        self.outputs = [output([1] * 350 + [2] * 239), output([2] * 589)]

    def get_modelmeta(self):
        return SimpleNamespace(custom_metadata_map=dict(model_type=ENGINE, sample_rate="16000",
                               window_size="160000", receptive_field_size="991",
                               receptive_field_shift="270", num_classes="7"))

    def get_inputs(self):
        return [SimpleNamespace(name="x")]

    def run(self, _outputs, inputs):
        assert inputs["x"].shape == (1, 1, 160000)
        assert inputs["x"].dtype == np.float32
        result = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return [result[None]]


def test_overlapping_windows_keep_their_absolute_audio_clock_and_reuse_cached_measurements(tmp_path):
    session = Session()
    model = tmp_path / "model.onnx"
    model.write_bytes(b"test-session")
    engine = SpeakerChanges(model, cache=tmp_path, session=session)
    audio = np.ones(160000, dtype=np.float32)
    original = audio.copy()
    progress = []
    result = engine.changes(audio, report=progress.append)
    assert len(result) == 1
    assert result[0]["time"] == pytest.approx(-2.5 + 991 / 32000 + 350 * 270 / 16000)
    assert session.calls == 2 and progress[-1] == 1
    assert np.array_equal(audio, original)
    assert engine.changes(audio) == result and session.calls == 2


def test_cancelled_inference_keeps_no_partial_measurement(tmp_path):
    session = Session()
    engine = SpeakerChanges(tmp_path / "model.onnx", cache=tmp_path, session=session)
    with pytest.raises(InterruptedError):
        engine.changes(np.ones(160000, dtype=np.float32), cancel=lambda: session.calls >= 1)
    assert not list(tmp_path.glob("dialogue/*.json"))
    assert not list(tmp_path.glob("dialogue/*.part"))


def test_bad_cached_metadata_is_recomputed_instead_of_used(tmp_path):
    session = Session()
    engine = SpeakerChanges(tmp_path / "model.onnx", cache=tmp_path, session=session)
    audio = np.ones(160000, dtype=np.float32)
    path = engine._cache_path(audio)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps([{"time": 10 ** 400, "confidence": 0.9}]))
    assert engine.changes(audio)
    assert session.calls == 2


def test_turns_and_mapping_preserve_voice_change_evidence_when_recalculated():
    probabilities = [0.95] * 200
    events = [{"time": 2.0, "confidence": 0.9}, {"time": 4.0, "confidence": 0.8}]
    turns = dialogue_turns(probabilities, DEFAULTS, events)
    assert len(turns) == 3
    assert [turn["start"] for turn in turns] == [0, 2, 4]
    assert all(turn["source"] == "speaker_change" for turn in turns)
    mapped = map_turns(turns, 90000, 25)
    assert [turn["start"] for turn in mapped] == [90000, 90050, 90100]
    assert mapped[0]["turn_id"].startswith("90000:")
    assert mapped[1]["confidence"] == 0.8
    assert dialogue_turns(probabilities, DEFAULTS) == turns_from_probs(probabilities, DEFAULTS)


def test_voice_changes_outside_speech_or_too_close_to_each_other_do_not_force_short_replies():
    probabilities = [0.0] * 32 + [0.95] * 120 + [0.0] * 32
    legacy = turns_from_probs(probabilities, DEFAULTS)
    assert len(legacy) == 1
    events = [{"time": 0.1, "confidence": 0.9}, {"time": 2, "confidence": 0.9},
              {"time": 2.05, "confidence": 0.9}, {"time": 3, "confidence": 0.1}]
    turns = dialogue_turns(probabilities, DEFAULTS, events)
    assert len(turns) == 2
    assert turns[0]["start"] == legacy[0]["start"] and turns[-1]["end"] == legacy[0]["end"]
    assert turns[0]["end"] == turns[1]["start"] == 2


def test_summary_distinguishes_old_projects_ready_and_unavailable_audio():
    assert "automatically" in dialogue_summary(None)
    assert "No analyzed audio" in dialogue_summary({"speech_tracks": []})
    assert "Analyze again" in dialogue_summary({"speech_tracks": [{}]})
    assert "3 detected" in dialogue_summary({"speech_tracks": [{"dialogue_status": {"state": "ready", "changes": 3}}]})
    assert "unavailable" in dialogue_summary({"speech_tracks": [{"dialogue_status": {"state": "failed"}}]})


def live(tmp_path):
    from vispa_mp.analyze import Live
    from vispa_mp.progress import Steps
    result = Live.__new__(Live)
    result.cache = tmp_path
    result._dialogue = None
    result._dialogue_failure = None
    result.cancel = None
    result.steps = Steps()
    return result


def test_a_missing_optional_model_preserves_speech_analysis_and_explains_the_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("vispa_mp.models_setup.dialogue_ready", lambda: False)
    result = live(tmp_path).dialogue(np.zeros(16000))
    assert result["speaker_changes"] == []
    assert result["dialogue_status"]["state"] == "unavailable"
    assert "Download models" in result["dialogue_status"]["detail"]


def test_a_model_failure_is_reported_without_inventing_voice_changes(tmp_path, monkeypatch):
    monkeypatch.setattr("vispa_mp.models_setup.dialogue_ready", lambda: True)
    def broken(*_args):
        raise RuntimeError("unsupported local inference")
    monkeypatch.setattr("vispa_mp.dialogue.SpeakerChanges", broken)
    result = live(tmp_path).dialogue(np.zeros(16000))
    assert result["speaker_changes"] == []
    assert result["dialogue_status"]["state"] == "failed"
    assert "unsupported local inference" in result["dialogue_status"]["detail"]


def test_cancellation_never_becomes_a_successful_speech_only_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("vispa_mp.models_setup.dialogue_ready", lambda: True)
    def cancelled(*_args, **_kwargs):
        raise InterruptedError("stopped")
    source = live(tmp_path)
    source._dialogue = SimpleNamespace(changes=cancelled)
    with pytest.raises(InterruptedError):
        source.dialogue(np.zeros(16000))

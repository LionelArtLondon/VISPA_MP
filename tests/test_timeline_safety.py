"""An analysis belongs to one Resolve project and timeline, including after a restart."""

from copy import deepcopy

import pytest

from tests.test_analysis_cache import _Sources, _snapshot
from tests.test_ui import action_analysis
from vispa_mp.analyze import analysis_key, analyze, saved_analysis
from vispa_mp.preset import DEFAULTS
from vispa_mp.store import save_analysis
from vispa_mp.ui import MainWindow, Message


IDENTITY = {"project_id": "project-1", "timeline_id": "timeline-1"}


@pytest.mark.parametrize("changed_id", ["project_id", "timeline_id"])
def test_identical_media_on_another_timeline_do_not_rebind_a_cached_analysis(tmp_path, changed_id):
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"video")
    original = _snapshot(media)
    settings = dict(DEFAULTS)
    sources = _Sources()
    first = analyze(original, settings, sources=sources, store=tmp_path)

    other = deepcopy(original)
    other["timeline_identity"][changed_id] = "other"
    assert analysis_key(other, settings) != first["key"]
    assert saved_analysis(other, settings, tmp_path) is None
    second = analyze(other, settings, sources=sources, store=tmp_path)
    assert sources.calls == 2
    assert second["timeline_identity"] == other["timeline_identity"]
    assert first["timeline_identity"] == IDENTITY
    assert saved_analysis(original, settings, tmp_path)["timeline_identity"] == IDENTITY


@pytest.mark.parametrize("stored_identity", [None, {"project_id": "project-1", "timeline_id": "other"}])
def test_a_cache_without_matching_origin_is_not_restored(tmp_path, stored_identity):
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"video")
    snapshot = _snapshot(media)
    settings = dict(DEFAULTS)
    key = analysis_key(snapshot, settings)
    old = {"timeline_name": "Episode", "shots": [], "timeline_identity": stored_identity}
    save_analysis(tmp_path, key, old)
    assert saved_analysis(snapshot, settings, tmp_path) is None

    sources = _Sources()
    result = analyze(snapshot, settings, sources=sources, store=tmp_path)
    assert sources.calls == 1
    assert not result.get("restored")
    assert result["timeline_identity"] == IDENTITY


def test_an_unidentified_snapshot_cannot_restore_or_save_a_bound_analysis(tmp_path):
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"video")
    snapshot = _snapshot(media)
    del snapshot["timeline_identity"]
    settings = dict(DEFAULTS)
    assert analysis_key(snapshot, settings) is None
    assert saved_analysis(snapshot, settings, tmp_path) is None
    result = analyze(snapshot, settings, sources=_Sources(), store=tmp_path)
    assert result["timeline_identity"] is None
    assert not (tmp_path / "analyses").exists()


def _review(qapp):
    window = MainWindow(client=None)
    window.snapshot = {
        "timeline_name": "Episode", "timeline_identity": dict(IDENTITY),
        "start_frame": 0, "fps": 24, "video_clips": [], "audio_clips": [], "markers": [],
    }
    analysis = action_analysis()
    analysis.update(timeline_identity=dict(IDENTITY), timeline_name="Episode")
    window.show_analysis(analysis)
    return window


def _synchronous_worker(window, monkeypatch):
    monkeypatch.setattr(window, "_confirm_project_discard", lambda: True)
    monkeypatch.setattr(window, "_start", lambda work, done: done(work(lambda _value: None)))


@pytest.mark.parametrize("new_identity", [None, {"project_id": "project-1", "timeline_id": "other"},
                                         {"project_id": "other", "timeline_id": "timeline-1"}])
def test_reading_another_timeline_clears_the_previous_review(qapp, tmp_path, monkeypatch, new_identity):
    window = _review(qapp)
    assert window.proposals
    window._preview = {"frame": 12}
    window._suggestions_open = True
    snapshot = dict(window.snapshot, timeline_identity=new_identity, timeline_name="Other episode")
    client = type("Client", (), {"read": lambda self: snapshot})()
    window.client = client
    monkeypatch.setattr(window, "_cache_dir", lambda: tmp_path)
    _synchronous_worker(window, monkeypatch)
    window.read_timeline()
    assert window.analysis is None
    assert window.proposals == []
    assert window.pages == []
    assert window._preview is None
    assert window._suggestions_open is False
    assert window.timeline_label.text() == "Project: unknown\nTimeline: Other episode"


def test_reading_the_same_unchanged_timeline_preserves_review_choices(qapp, tmp_path, monkeypatch):
    window = _review(qapp)
    window.proposals[0]["color"] = "Cyan"
    kept = deepcopy(window.proposals)
    snapshot = deepcopy(window.snapshot)
    window.client = type("Client", (), {"read": lambda self: snapshot})()
    monkeypatch.setattr(window, "_cache_dir", lambda: tmp_path)
    _synchronous_worker(window, monkeypatch)
    window.read_timeline()
    assert window.proposals == kept
    assert window.analysis["timeline_identity"] == IDENTITY


def test_marker_offsets_and_target_come_from_the_analysis(qapp):
    window = _review(qapp)
    window.snapshot["start_frame"] = 1000  # a newer read must never supply the old review's origin
    payload = window.resolve_payload()
    assert payload["expected_timeline"] == IDENTITY
    assert payload["proposals"][0]["frame"] == window.proposals[0]["frame"]
    payload["expected_timeline"]["timeline_id"] = "changed"
    assert window.analysis["timeline_identity"] == IDENTITY


@pytest.mark.parametrize("unbound", [True, False])
def test_write_refuses_unidentified_or_mismatched_analysis_before_confirmation(qapp, monkeypatch, unbound):
    window = _review(qapp)
    if unbound:
        del window.analysis["timeline_identity"]
    else:
        window.snapshot["timeline_identity"]["timeline_id"] = "other"
    window.client = object()
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    monkeypatch.setattr(Message, "ask", lambda *args: pytest.fail("An unsafe placement was offered"))
    monkeypatch.setattr(window, "_start", lambda *args: pytest.fail("An unsafe command was sent"))
    window.write_markers()
    assert notices
    assert window.proposals  # the review remains available to inspect


def test_write_sends_the_analyzed_identity_and_names_the_target(qapp, monkeypatch):
    window = _review(qapp)
    calls, confirmations = [], []

    class Client:
        def apply(self, proposals, start, end, expected_timeline=None):
            calls.append((proposals, start, end, expected_timeline))
            return {"placed": [proposal["frame"] for proposal in proposals], "skipped": [],
                    "failed": [], "outside": [], "verified": True}

    window.client = Client()
    monkeypatch.setattr(Message, "ask", lambda *args: confirmations.append(args) or True)
    monkeypatch.setattr(Message, "tell", lambda *args: None)
    _synchronous_worker(window, monkeypatch)
    window.write_markers()
    assert len(calls) == 1
    assert calls[0][3] == IDENTITY
    assert "Episode" in confirmations[0][2]

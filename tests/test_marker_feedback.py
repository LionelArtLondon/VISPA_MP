"""A proposal count is not a successful placement until Resolve has verified it."""

from copy import deepcopy

import pytest

from vispa_mp.ui import MainWindow, Message


IDENTITY = {"project_id": "project-1", "timeline_id": "timeline-1"}


def _window(qapp, monkeypatch, offsets, result, span=None):
    window = MainWindow()
    window.snapshot = {"start_frame": 90000, "timeline_identity": dict(IDENTITY)}
    window.analysis = {"timeline_name": "Episode", "timeline_identity": dict(IDENTITY), "range": span,
                       "timebase": {"start_frame": 90000, "fps": 25, "start_timecode": "01:00:00:00"}}
    window.proposals = [{"frame": 90000 + offset, "color": "Blue"} for offset in offsets]
    calls, questions, notices = [], [], []

    class Client:
        def apply(self, proposals, start, end, expected_timeline=None):
            calls.append((deepcopy(proposals), start, end, expected_timeline))
            return deepcopy(result)

    window.client = Client()
    monkeypatch.setattr(Message, "ask", lambda *args: questions.append(args) or True)
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))

    def start(work, done):
        try:
            done(work(lambda _value: None))
        except RuntimeError as error:
            window._failed(str(error))

    monkeypatch.setattr(window, "_start", start)
    return window, calls, questions, notices


def test_confirmation_counts_only_the_eligible_range_and_reports_verified_placement(qapp, monkeypatch):
    offsets = [0, 5, 8] + list(range(10, 37)) + [40, 50]
    result = {"placed": list(range(10, 37)), "skipped": [], "failed": [],
              "outside": [0, 5, 8, 40, 50], "requested": 32, "attempted": 27, "verified": True}
    window, calls, questions, notices = _window(qapp, monkeypatch, offsets, result, [90010, 90040])
    before = deepcopy(window.proposals)

    window.write_markers()

    assert len(calls) == 1 and len(calls[0][0]) == 32
    assert calls[0][1:3] == (10, 40)
    assert calls[0][3] == IDENTITY
    assert "Place 27 markers" in questions[0][2]
    assert "27 proposals out of 32" in questions[0][3]
    assert "5 proposals outside" in questions[0][3]
    assert notices[0][2] == "27 markers placed and verified in Resolve."
    assert "5 proposals outside" in notices[0][3]
    assert window.proposals == before


def test_a_range_without_proposals_never_sends_a_delete_or_apply_command(qapp, monkeypatch):
    window, calls, questions, notices = _window(qapp, monkeypatch, [0, 40], {}, [90010, 90040])
    window.write_markers()
    assert calls == questions == []
    assert "Nothing to place" in notices[0][2]
    assert "No markers were changed" in notices[0][3]


@pytest.mark.parametrize("result", [None, {}, {"placed": [10], "verified": False},
                                    {"placed": [10], "verified": "true"}, {"placed": [10]}])
def test_an_old_or_unverified_reply_is_never_announced_as_success(qapp, monkeypatch, result):
    window, calls, questions, notices = _window(qapp, monkeypatch, [10], result)
    window.write_markers()
    assert calls and questions
    assert "did not verify" in window.status.text()
    assert "Workspace > Scripts > VISPA_MP" in notices[0][3]
    assert "placed and verified" not in " ".join(str(part) for part in notices[0][1:])


def test_partial_placement_distinguishes_failed_manual_and_outside_positions(qapp, monkeypatch):
    result = {"placed": [10], "skipped": [11, 12], "failed": [11], "outside": [99],
              "requested": 4, "attempted": 2, "verified": True}
    window, calls, questions, notices = _window(qapp, monkeypatch, [10, 11, 12, 99], result, [90000, 90040])
    window.write_markers()
    assert notices[0][2] == "1 marker placed and verified in Resolve."
    assert "1 marker could not be created or verified" in notices[0][3]
    assert "1 position kept: a hand-placed marker already exists" in notices[0][3]
    assert "1 proposal outside" in notices[0][3]


def test_zero_verified_markers_has_an_explicit_failure_notice(qapp, monkeypatch):
    result = {"placed": [], "skipped": [10, 11], "failed": [10, 11], "outside": [],
              "requested": 2, "attempted": 2, "verified": True}
    window, calls, questions, notices = _window(qapp, monkeypatch, [10, 11], result)
    window.write_markers()
    assert notices[0][2] == "No markers were placed."
    assert "2 markers could not be created or verified" in notices[0][3]


def test_cancelling_confirmation_has_no_rpc_or_completion_notice(qapp, monkeypatch):
    window, calls, questions, notices = _window(qapp, monkeypatch, [10], {"verified": True})
    monkeypatch.setattr(Message, "ask", lambda *args: False)
    window.write_markers()
    assert calls == notices == []

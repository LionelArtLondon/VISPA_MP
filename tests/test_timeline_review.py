"""Exact-frame additions are local, undoable, and portable with their candidates."""

from copy import deepcopy
import json
from pathlib import Path
from threading import Event
import time
from zipfile import ZipFile

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest

from tests.test_page_reorder_ui import _reading_order, _window
from tests.test_project import _rewrite
from vispa_mp.markers import CORE, EXTRA
from vispa_mp.project import load_project
from vispa_mp.ui import Message


def settle(qapp):
    for _ in range(10):
        qapp.processEvents()


@pytest.fixture
def review(qapp, tmp_path, monkeypatch):
    windows, calls, notices = [], [], []
    monkeypatch.setattr("vispa_mp.project_location.LOCATION_PATH", tmp_path / "locations.json")
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    pool = []
    for frame in (34, 35, 36):
        image = tmp_path / f"timeline-{frame}.jpg"
        Image.new("RGB", (40, 24), (frame, 80, 120)).save(image)
        pool.append({"frame": frame, "image": str(image)})

    def capture(snapshot, analysis, frame, cache, **_kwargs):
        calls.append((snapshot, analysis, frame, cache))
        return deepcopy(pool)

    monkeypatch.setattr("vispa_mp.timeline_review.capture_timeline_candidates", capture)

    def create(mode="strip", *, inline=True):
        window = _window(mode, manual=True)
        windows.append(window)
        window.resize(1600, 1000)
        window.show()
        window._resolve_timer.stop()
        monkeypatch.setattr(window, "_cache_dir", lambda: tmp_path / "cache")
        if inline:
            def start(work, done):
                try:
                    done(work(lambda _value: None))
                except Exception as error:
                    window._failed(str(error))
            monkeypatch.setattr(window, "_start", start)
        settle(qapp)
        window._project_dirty = False
        return window

    yield create, pool, calls, notices
    for window in windows:
        if window.worker is not None and hasattr(window.worker, "wait"):
            window.worker.wait(2000)
            settle(qapp)
        window.worker = None
        window._learning_job_busy = False
        window._project_dirty = False
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_exact_timeline_frame_adds_one_local_proposal_and_one_undo_without_mutating_analysis(qapp, review, monkeypatch):
    create, pool, calls, notices = review
    window = create()
    analysis, snapshot, originals = deepcopy((window.analysis, window.snapshot, window.proposals))

    def forbidden(*_args, **_kwargs):
        pytest.fail("Timeline additions must not run full analysis or contact Resolve")

    class NoRPC:
        read = apply = seek = forbidden
        def close(self):
            pass

    window.client = NoRPC()
    for name in ("run_analysis", "read_timeline", "write_markers", "seek_frame"):
        monkeypatch.setattr(window, name, forbidden)
    assert window._add_timeline_marker(35)
    settle(qapp)
    proposal = window._proposal(35)
    assert proposal["color"] == CORE and proposal["rule"] == "user"
    assert proposal["image"] == pool[1]["image"]
    assert proposal["timeline_candidates"] == pool
    assert window.selected_frame == 35 and window.selected_page_id == 10
    assert window._selected_keys == {(35, False)}
    assert window.analysis == analysis and window.snapshot == snapshot
    assert calls[0][2] == 35 and calls[0][0] == snapshot and calls[0][1] == analysis
    assert window.undo_stack.count() == 1 and window._project_dirty
    window._undo_review()
    assert window.proposals == originals and window.analysis == analysis
    window._redo_review()
    assert window._proposal(35)["timeline_candidates"] == pool
    assert notices == []


def test_real_worker_finishes_before_the_undoable_commit(qapp, review, monkeypatch):
    create, _pool, _calls, _notices = review
    window = create(inline=False)
    completed_while_busy, committed_idle = [], []
    original_start, original_commit = window._start, window._commit_timeline_marker

    def start(work, done):
        def completed(result):
            completed_while_busy.append(window.worker is not None)
            done(result)
        original_start(work, completed)

    def commit(*args):
        committed_idle.append(window.worker is None)
        return original_commit(*args)

    monkeypatch.setattr(window, "_start", start)
    monkeypatch.setattr(window, "_commit_timeline_marker", commit)
    assert window._add_timeline_marker(35)
    for _ in range(150):
        QTest.qWait(10)
        if window.worker is None and window._proposal(35) is not None:
            break
    assert completed_while_busy == [True]
    assert committed_idle == [True]
    assert window._proposal(35) is not None and window.undo_stack.count() == 1


def test_added_marker_and_candidate_images_roundtrip_inside_the_project(qapp, review, tmp_path):
    create, pool, _calls, _notices = review
    window = create()
    expected = {item["frame"]: Path(item["image"]).read_bytes() for item in pool}
    window._add_timeline_marker(35, EXTRA)
    settle(qapp)
    path = tmp_path / "timeline-added.vispamp"
    assert window.save_project_file(path)
    with ZipFile(path) as archive:
        metadata = json.loads(archive.read("project.json"))
        proposal = next(item for item in metadata["proposals"] if item["frame"] == 35)
        assert all(item["image"].startswith("images/") for item in proposal["timeline_candidates"])
        assert len([name for name in archive.namelist() if name.startswith("images/")]) == len(set(expected.values()))
    for item in pool:
        Path(item["image"]).unlink()
    project = load_project(path, tmp_path / "restored-cache")
    restored = next(item for item in project["proposals"] if item["frame"] == 35)
    assert restored["color"] == EXTRA
    assert {item["frame"]: Path(item["image"]).read_bytes() for item in restored["timeline_candidates"]} == expected


@pytest.mark.parametrize("invalid", [[], None, {}, [{"frame": True, "image": "images/x.jpg"}],
                                    [{"frame": 35, "image": 1}],
                                    [{"frame": 35, "image": ""}],
                                    [{"frame": 35, "image": "images/x.jpg"}] * 2,
                                    [{"frame": frame, "image": "images/x.jpg"} for frame in range(6)]])
def test_project_rejects_invalid_optional_candidate_pools(qapp, review, tmp_path, invalid):
    create, _pool, _calls, _notices = review
    window = create()
    window._add_timeline_marker(35)
    settle(qapp)
    path = tmp_path / "invalid-pool.vispamp"
    assert window.save_project_file(path)
    _rewrite(path, edit=lambda metadata:
             next(item for item in metadata["proposals"] if item["frame"] == 35).update(timeline_candidates=invalid))
    with pytest.raises(ValueError):
        load_project(path, tmp_path / "invalid-cache")


def test_manual_arrangement_uses_source_predecessor_page_and_keeps_other_page_order(qapp, review):
    create, _pool, _calls, _notices = review
    window = create("board")
    window._page_layout = [{"id": 10, "frames": [10, 50, 20, 30]}, {"id": 40, "frames": [40, 60]}]
    window._fill()
    window._choose_frame(60, False)
    window.board.zoom = 3
    window._add_timeline_marker(35)
    settle(qapp)
    assert _reading_order(window) == [(10, [10, 50, 20, 30, 35]), (40, [40, 60])]
    assert window.selected_page_id == 10 and window.selected_frame == 35
    assert window.board.zoom == 1
    assert window.analysis["manual_frames"] == [15]


@pytest.mark.parametrize("view_filter,color", [("core", EXTRA), ("starts", CORE)])
def test_new_primary_is_shown_when_the_old_filter_would_hide_it(qapp, review, view_filter, color):
    create, _pool, _calls, _notices = review
    window = create()
    window._set_filter(view_filter)
    window._add_timeline_marker(35, color)
    settle(qapp)
    assert window.view_filter == "all" and window.selected_frame == 35
    assert any(item.get("proposal", {}).get("frame") == 35 for item in window._view_items())


@pytest.mark.parametrize("frame", [15, 20])
def test_existing_manual_and_automatic_markers_are_never_replaced(qapp, review, frame):
    create, _pool, calls, _notices = review
    window = create()
    before = deepcopy((window.proposals, window.analysis, window.snapshot))
    assert not window._add_timeline_marker(frame)
    settle(qapp)
    assert calls == [] and window.undo_stack.count() == 0
    assert (window.proposals, window.analysis, window.snapshot) == before


@pytest.mark.parametrize("problem", ["worker", "learning", "identity", "timebase", "clock", "shown-rate", "outside"])
def test_busy_unverified_or_outside_requests_do_not_extract_images(qapp, review, problem):
    create, _pool, calls, _notices = review
    window = create()
    frame = 35
    if problem == "worker":
        window.worker = object()
    elif problem == "learning":
        window._learning_job_busy = True
    elif problem == "identity":
        window.snapshot["timeline_identity"]["timeline_id"] = "other"
    elif problem == "timebase":
        window.analysis["timebase"]["fps"] = 0
    elif problem == "clock":
        window.snapshot["start_timecode"] = "02:00:00:00"
    elif problem == "shown-rate":
        window.analysis["timebase"]["timecode_fps"] = 12
    else:
        frame = 100
    assert not window._add_timeline_marker(frame)
    settle(qapp)
    assert calls == [] and window._proposal(35) is None and window.undo_stack.count() == 0


@pytest.mark.parametrize("changed", ["analysis", "snapshot", "generation", "timebase", "source-edit"])
def test_late_capture_from_a_stale_preparation_cannot_commit(qapp, review, monkeypatch, changed):
    create, pool, _calls, _notices = review
    window = create()
    done = []
    monkeypatch.setattr(window, "_start", lambda _work, callback: done.append(callback))
    assert window._add_timeline_marker(35)
    if changed == "analysis":
        window.analysis = deepcopy(window.analysis)
    elif changed == "snapshot":
        window.snapshot = deepcopy(window.snapshot)
    elif changed == "generation":
        window._clear_review_history()
    elif changed == "timebase":
        window.analysis["timebase"]["start_timecode"] = "02:00:00:00"
    else:
        window.snapshot["video_clips"].append({"path": "changed.mp4", "start": 0, "end": 100})
    before = deepcopy(window.proposals)
    done[0](deepcopy(pool))
    settle(qapp)
    assert window.proposals == before and window.undo_stack.count() == 0


@pytest.mark.parametrize("failure", ["gap", "offline"])
def test_capture_failure_keeps_the_preparation_and_reports_why(qapp, review, monkeypatch, failure):
    create, _pool, _calls, notices = review
    window = create()
    before = deepcopy((window.proposals, window.analysis))

    def fail(*_args, **_kwargs):
        raise ValueError("No source clip at this frame" if failure == "gap" else "Source media is offline")

    monkeypatch.setattr("vispa_mp.timeline_review.capture_timeline_candidates", fail)
    assert window._add_timeline_marker(35)
    settle(qapp)
    assert (window.proposals, window.analysis) == before and window.undo_stack.count() == 0
    assert notices


def test_timeline_menu_uses_exact_display_timecode_and_core_is_the_default(qapp, review, monkeypatch):
    create, _pool, calls, _notices = review
    window = create()
    window.snapshot["start_timecode"] = "01:00:00:00"
    window.analysis["timebase"]["start_timecode"] = "01:00:00:00"
    menu = window._timeline_menu(35)
    try:
        assert menu.actions()[0].text() == "01:00:01:11"
        assert not menu.actions()[0].isEnabled()
        assert menu.defaultAction().text() == "Add Core marker here"
        menu.defaultAction().trigger()
        settle(qapp)
        assert calls[0][2] == 35 and window._proposal(35)["frame"] == 35
    finally:
        menu.deleteLater()


def test_user_timeline_marker_and_its_pool_survive_recalculation(qapp, review, monkeypatch):
    create, pool, _calls, _notices = review
    window = create()
    initial = deepcopy(window.proposals)
    window._add_timeline_marker(35)
    settle(qapp)
    monkeypatch.setattr("vispa_mp.ui.propose", lambda *_args, **_kwargs:
                        {"proposals": initial, "warnings": []})
    window.recompute()
    assert window._proposal(35)["timeline_candidates"] == pool
    assert window._proposal(35)["rule"] == "user"


def test_a_refreshed_manual_marker_in_the_snapshot_blocks_addition(qapp, review):
    create, _pool, calls, _notices = review
    window = create()
    window.snapshot["markers"].append({"frame": 35, "automatic": False})
    assert 35 not in window.analysis["manual_frames"]
    assert not window._add_timeline_marker(35)
    settle(qapp)
    assert calls == [] and window._proposal(35) is None


def test_the_new_markers_neighbors_open_without_changing_the_automatic_suggestions_preference(qapp, review):
    create, pool, _calls, _notices = review
    window = create()
    assert not window.suggestions_auto_open
    window._add_timeline_marker(35)
    settle(qapp)
    assert window._suggestions_open and not window.suggestions_auto_open
    assert {item["frame"] for item in pool} <= set(window._suggestion_cards)


def test_capture_without_the_exact_requested_image_never_places_a_neighbor_instead(qapp, review, monkeypatch):
    create, pool, _calls, _notices = review
    window = create()
    monkeypatch.setattr("vispa_mp.timeline_review.capture_timeline_candidates",
                        lambda *_args, **_kwargs: [item for item in pool if item["frame"] != 35])
    assert window._add_timeline_marker(35)
    settle(qapp)
    assert window._proposal(35) is None and window.undo_stack.count() == 0
    assert "exact requested frame" in window.status.text().lower()


def test_page_start_role_menu_explains_that_manual_reading_order_is_preserved(qapp, review):
    create, _pool, _calls, _notices = review
    window = create()
    window._page_layout = [{"id": 10, "frames": [10, 20, 30]}, {"id": 40, "frames": [40, 50, 60]}]
    window._fill()
    before = deepcopy(window._page_layout)
    menu = window._timeline_menu(35)
    try:
        action = next(action for action in menu.actions() if action.text() == "Add Page start marker here")
        assert action.isEnabled()
        assert "Manual page order is preserved" in action.toolTip()
        assert window._page_layout == before
    finally:
        menu.deleteLater()


def test_capture_can_be_cancelled_through_the_existing_toolbar_with_a_real_worker(qapp, review, monkeypatch):
    create, _pool, _calls, notices = review
    window = create(inline=False)
    entered = Event()

    def cancellable(_snapshot, _analysis, _frame, _cache, *, cancel):
        entered.set()
        for _ in range(300):
            if cancel():
                raise InterruptedError("Stopped")
            time.sleep(0.005)
        pytest.fail("The cancellation request did not reach the frame capture")

    monkeypatch.setattr("vispa_mp.timeline_review.capture_timeline_candidates", cancellable)
    before = deepcopy((window.proposals, window.analysis, window.snapshot, window._selected_keys))
    assert window._add_timeline_marker(35)
    for _ in range(100):
        QTest.qWait(5)
        if entered.is_set():
            break
    assert entered.is_set() and window.worker is not None
    assert window.analyze_button.isEnabled()
    assert window.analyze_button.accessibleName() == "Cancel image capture"
    assert "Cancel image capture" in window.analyze_button.toolTip()
    stop = window._stop_analysis
    window.analyze_button.click()
    assert stop.is_set()
    for _ in range(150):
        QTest.qWait(10)
        if window.worker is None:
            break
    settle(qapp)
    assert window.worker is None and window._stop_analysis is None
    assert window.analyze_button.accessibleName() == "Analyze"
    assert (window.proposals, window.analysis, window.snapshot, window._selected_keys) == before
    assert window.undo_stack.count() == 0 and not window._project_dirty
    assert window.status.text() == "Image capture cancelled. Your preparation was kept."
    assert notices == []


def test_a_stop_after_the_result_was_delivered_still_prevents_the_deferred_commit(qapp, review, monkeypatch):
    create, pool, _calls, _notices = review
    window = create()

    def start(_work, done):
        stop = window._stop_analysis
        done(deepcopy(pool))
        stop.set()

    monkeypatch.setattr(window, "_start", start)
    assert window._add_timeline_marker(35)
    assert window._stop_analysis is None
    assert window.analyze_button.accessibleName() == "Analyze"
    settle(qapp)
    assert window._proposal(35) is None and window.undo_stack.count() == 0
    assert window.status.text() == "Image capture cancelled. Your preparation was kept."


def test_an_added_suggestion_keeps_its_timeline_neighbors_without_changing_analysis(qapp, review):
    create, pool, _calls, _notices = review
    window = create()
    original_analysis = deepcopy(window.analysis)
    window._add_timeline_marker(35)
    settle(qapp)
    assert window.selected_frame == 35
    window._add_suggestion_marker(34, EXTRA)
    settle(qapp)
    assert window._proposal(34)["color"] == EXTRA
    assert window._proposal(34)["timeline_candidates"] == pool
    window._choose_frame(34, False)
    assert {34, 35, 36} <= {item["frame"] for item in window._suggestion_frames()}
    assert window.analysis == original_analysis
    assert window.undo_stack.count() == 2

"""Save and resume the marker review, while Resolve still controls the target."""

from copy import deepcopy
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QFileDialog

from tests.test_ui import action_analysis
from tests.test_project import _rewrite
from vispa_mp.markers import NAMES
from vispa_mp.snapshot import normalize
from vispa_mp.ui import MainWindow, Message


IDENTITY = {"project_id": "project-1", "timeline_id": "timeline-1"}
PROJECT_NAME = "Tome 05"
TIMELINE_NAME = "Chapter 04"


@pytest.fixture(autouse=True)
def project_locations(tmp_path, monkeypatch):
    monkeypatch.setattr("vispa_mp.project_location.LOCATION_PATH", tmp_path / "locations.json")


def _review(qapp, tmp_path):
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"source media")
    window = MainWindow(client=None)
    window.snapshot = normalize({
        "project_name": PROJECT_NAME, "timeline_name": TIMELINE_NAME,
        "timeline_identity": dict(IDENTITY), "script_version": 3,
        "fps": 24, "start_frame": 0, "end_frame": 24,
        "start_timecode": "00:00:00:00", "drop": False,
        "video_clips": [{"path": str(media), "name": media.name, "fps": 24,
                         "start": 0, "end": 24, "source_start": 0, "source_end": 24, "speed": 1}],
        "audio_clips": [], "markers": [], "warnings": [],
    })
    window.set_setting("action_extras", 0)
    window.set_setting("mouth_min", 0.41)
    analysis = action_analysis()
    analysis["timebase"]["start_timecode"] = window.snapshot["start_timecode"]
    analysis.update(timeline_identity=dict(IDENTITY), project_name=PROJECT_NAME,
                    timeline_name=TIMELINE_NAME)
    for frame in analysis["shots"][0]["frames"]:
        image = tmp_path / f"candidate-{frame['frame']}.jpg"
        Image.new("RGB", (16, 9), (frame["frame"], 80, 120)).save(image)
        frame["image"] = str(image)
    window.show_analysis(analysis)
    marker = window.proposals[0]
    window._choose_frame(marker["frame"], False)
    window._use_suggestion(12)
    window._set_marker_color("Green")
    assert window.proposals[0]["frame"] == 12
    assert window.proposals[0]["name"] == NAMES["Green"]
    return window


def _worker_inline(window, monkeypatch):
    monkeypatch.setattr(window, "_start", lambda work, done: done(work(lambda _value: None)))


def _client(snapshot, error=None):
    class Client:
        reads = 0
        closes = 0

        def read(self):
            self.reads += 1
            if error is not None:
                raise error
            return deepcopy(snapshot)

        def apply(self, *args, **kwargs):
            pytest.fail("Opening a review must never place markers")

        def close(self):
            self.closes += 1

    return Client()


def _semantic_proposals(proposals):
    result = deepcopy(proposals)
    for proposal in result:
        if proposal.get("image"):
            proposal["image"] = Path(proposal["image"]).read_bytes()
    return result


def test_a_review_saves_without_resolve_and_loads_exact_choices_without_reanalysis(qapp, tmp_path, monkeypatch):
    original = _review(qapp, tmp_path)
    original._choose_format("B5")
    original._choose_orientation("landscape")
    original._set_mode("board")
    original._set_filter("core")
    original.set_suggestions_height(360)
    original.open_pages = {12}
    original.seek_frame(14)
    expected = _semantic_proposals(original.proposals)
    settings = original.settings()
    path = tmp_path / "prepared.vispamp"
    monkeypatch.setattr("vispa_mp.project_ui.open_client", lambda: pytest.fail("Saving needs no Resolve connection"))
    assert original.save_project_file(path) is True

    # The working cache is disposable: its disappearance must not lose the review.
    for image in tmp_path.glob("candidate-*.jpg"):
        image.unlink()

    current = _client(original.snapshot)
    restored = MainWindow(client=current)
    _worker_inline(restored, monkeypatch)
    monkeypatch.setattr(restored, "_cache_dir", lambda: tmp_path / "new-cache")
    monkeypatch.setattr(restored, "recompute", lambda: pytest.fail("Loading must preserve the saved proposals"))
    monkeypatch.setattr("vispa_mp.ui.analyze", lambda *args, **kwargs: pytest.fail("Loading must not run inference"))
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    restored.open_project_file(path)

    assert notices == []
    assert current.reads == 1
    assert _semantic_proposals(restored.proposals) == expected
    assert restored.settings() == settings
    assert restored.analysis["timeline_identity"] == IDENTITY
    assert restored.page_format == "B5" and restored.orientation == "landscape"
    assert restored.mode == "board" and restored.view_filter == "core"
    assert restored.get_suggestions_height() == 360
    assert restored.selected_frame == 12 and restored.selected_manual is False
    assert restored.playhead_frame == 14 and restored.open_pages == {12}
    assert restored.resolve_payload()["expected_timeline"] == IDENTITY


def test_a_project_saved_before_resizable_suggestions_uses_the_default_height(qapp, tmp_path, monkeypatch):
    original = _review(qapp, tmp_path)
    original.set_suggestions_height(360)
    path = tmp_path / "older-preparation.vispamp"
    assert original.save_project_file(path)
    with ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    metadata = json.loads(files["project.json"])
    metadata["view"].pop("suggestions_height")
    files["project.json"] = json.dumps(metadata).encode("utf-8")
    with ZipFile(path, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)

    restored = MainWindow(client=_client(original.snapshot))
    restored.set_suggestions_height(500)
    _worker_inline(restored, monkeypatch)
    monkeypatch.setattr(restored, "_cache_dir", lambda: tmp_path / "cache")
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    restored.open_project_file(path)
    assert notices == []
    assert restored.get_suggestions_height() == 200
    assert restored.proposals[0]["frame"] == original.proposals[0]["frame"]


def _settle_view(qapp):
    for _ in range(5):
        qapp.processEvents()


def _assert_camera_near(actual, expected):
    assert actual is not None and expected is not None
    assert actual["zoom"] == pytest.approx(expected["zoom"])
    assert actual["center"] == pytest.approx(expected["center"], abs=0.02)
    if "columns" in expected:
        assert actual["columns"] == expected["columns"]


@pytest.mark.parametrize("active_mode", ["strip", "board"])
def test_a_saved_project_restores_both_views_independent_zoom_and_position(qapp, tmp_path, monkeypatch, active_mode):
    original = _review(qapp, tmp_path)
    original.resize(1600, 900)
    original.show()
    _settle_view(qapp)
    original.set_review_cameras({
        "strip": {"zoom": 320, "center": [0.3, 0.7], "columns": 1},
        "board": {"zoom": 2.3, "center": [-0.1, 0.8]},
    })
    for mode in ("board", "strip", active_mode):
        original._set_mode(mode)
        _settle_view(qapp)
    expected = deepcopy(original.get_review_cameras())
    proposals = _semantic_proposals(original.proposals)
    path = tmp_path / "camera-preparation.vispamp"
    assert original.save_project_file(path)

    restored = MainWindow(client=_client(original.snapshot))
    restored.resize(1700, 850)
    restored.show()
    _settle_view(qapp)
    _worker_inline(restored, monkeypatch)
    monkeypatch.setattr(restored, "_cache_dir", lambda: tmp_path / "restored-camera-cache")
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    restored.open_project_file(path)
    _settle_view(qapp)

    assert notices == []
    assert restored.mode == active_mode
    for mode in ("board", "strip", active_mode):
        restored._set_mode(mode)
        _settle_view(qapp)
        _assert_camera_near(restored.get_review_cameras()[mode], expected[mode])
    assert _semantic_proposals(restored.proposals) == proposals


def test_an_older_project_resets_the_previous_projects_view_cameras(qapp, tmp_path, monkeypatch):
    original = _review(qapp, tmp_path)
    path = tmp_path / "legacy-camera-preparation.vispamp"
    assert original.save_project_file(path)
    _rewrite(path, edit=lambda metadata: metadata["view"].pop("cameras"))

    restored = _review(qapp, tmp_path)
    restored.resize(1600, 900)
    restored.show()
    _settle_view(qapp)
    restored.set_review_cameras({
        "strip": {"zoom": 400, "center": [0.1, 0.9], "columns": 1},
        "board": {"zoom": 3, "center": [-0.1, 1.2]},
    })
    restored._set_mode("board")
    _settle_view(qapp)
    restored.client = _client(original.snapshot)
    monkeypatch.setattr(restored, "_confirm_project_discard", lambda: True)
    _worker_inline(restored, monkeypatch)
    monkeypatch.setattr(restored, "_cache_dir", lambda: tmp_path / "legacy-camera-cache")
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    restored.open_project_file(path)
    _settle_view(qapp)
    assert notices == []
    restored._set_mode("board")
    _settle_view(qapp)
    assert restored.board.zoom == 1
    assert restored.board.offset.x() == pytest.approx(0)
    assert restored.board.offset.y() == pytest.approx(0)
    restored._set_mode("strip")
    _settle_view(qapp)
    assert restored._thumb_zoom is None


def test_invalid_project_cameras_do_not_replace_the_current_marker_review(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    path = tmp_path / "invalid-camera-preparation.vispamp"
    assert window.save_project_file(path)
    _rewrite(path, edit=lambda metadata: metadata["view"].update(cameras={
        "board": {"zoom": 2, "center": [float("inf"), 0.5]},
    }))
    before = deepcopy(window.proposals)
    settings = window.settings()
    analysis = window.analysis
    monkeypatch.setattr(window, "_confirm_project_discard", lambda: True)
    _worker_inline(window, monkeypatch)
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    window.open_project_file(path)
    assert notices
    assert window.proposals == before
    assert window.settings() == settings
    assert window.analysis is analysis


@pytest.mark.parametrize("failure", ["timeline", "project", "offline", "missing-identity"])
def test_loading_explains_the_required_resolve_target_and_preserves_current_work(qapp, tmp_path, monkeypatch, failure):
    original = _review(qapp, tmp_path)
    path = tmp_path / "prepared.vispamp"
    assert original.save_project_file(path)
    target = deepcopy(original.snapshot)
    if failure in ("timeline", "project"):
        target["timeline_identity"][f"{failure}_id"] = "other"
    elif failure == "missing-identity":
        target.pop("timeline_identity")
    client = _client(target, RuntimeError("Resolve is not running") if failure == "offline" else None)
    window = _review(qapp, tmp_path)
    window.client = client
    window._set_marker_color("Cyan")
    before = deepcopy(window.proposals)
    before_settings = window.settings()
    before_analysis = window.analysis
    before_snapshot = window.snapshot
    before_path = window.project_path
    monkeypatch.setattr(window, "_confirm_project_discard", lambda: True)
    _worker_inline(window, monkeypatch)
    monkeypatch.setattr(window, "_cache_dir", lambda: tmp_path / "cache")
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))

    window.open_project_file(path)

    assert len(notices) == 1
    message = " ".join(str(part) for part in notices[0][1:])
    assert PROJECT_NAME in message and TIMELINE_NAME in message
    assert "Resolve" in message
    assert "open" in message.lower() or "ouvrir" in message.lower()
    assert window.proposals == before
    assert window.analysis is before_analysis and window.snapshot is before_snapshot
    assert window.settings() == before_settings
    assert window.project_path == before_path
    assert client.closes == 0


def test_loading_checks_resolve_again_instead_of_trusting_the_previous_read(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    path = tmp_path / "prepared.vispamp"
    assert window.save_project_file(path)
    target = deepcopy(window.snapshot)
    target["timeline_identity"]["timeline_id"] = "changed-after-read"
    window.client = _client(target)
    _worker_inline(window, monkeypatch)
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    window.open_project_file(path)
    assert window.client.reads == 1 and notices


@pytest.mark.parametrize("change", ["clock", "clip"])
def test_loading_rejects_an_edited_timeline_with_the_same_identity(qapp, tmp_path, monkeypatch, change):
    window = _review(qapp, tmp_path)
    path = tmp_path / "prepared.vispamp"
    assert window.save_project_file(path)
    target = deepcopy(window.snapshot)
    if change == "clock":
        target["start_timecode"] = "01:00:00:00"
    else:
        target["video_clips"][0]["source_start"] = 1
    window.client = _client(target)
    before = deepcopy(window.proposals)
    _worker_inline(window, monkeypatch)
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    window.open_project_file(path)
    assert notices
    message = " ".join(str(part) for part in notices[0][1:])
    assert "edit" in message.lower() and PROJECT_NAME in message and TIMELINE_NAME in message
    assert window.proposals == before


def test_a_disconnected_mailbox_explains_the_target_without_waiting_for_a_read(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    path = tmp_path / "prepared.vispamp"
    assert window.save_project_file(path)
    client = _client(window.snapshot)
    client.mailbox = True
    window.client = client
    _worker_inline(window, monkeypatch)
    monkeypatch.setattr("vispa_mp.project_ui.link_running", lambda: False)
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    window.open_project_file(path)
    assert client.reads == 0
    message = " ".join(str(part) for part in notices[0][1:])
    assert PROJECT_NAME in message and TIMELINE_NAME in message and "VISPA_MP" in message


def test_opening_without_any_client_reports_which_resolve_project_to_open(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    path = tmp_path / "prepared.vispamp"
    assert window.save_project_file(path)
    assert window.client is None
    _worker_inline(window, monkeypatch)

    def offline():
        raise RuntimeError("Resolve is not open")

    monkeypatch.setattr("vispa_mp.project_ui.open_client", offline)
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    window.open_project_file(path)
    assert notices
    message = " ".join(str(part) for part in notices[0][1:])
    assert "Resolve" in message and PROJECT_NAME in message and TIMELINE_NAME in message


def test_a_new_bridge_is_closed_when_its_target_does_not_match(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    path = tmp_path / "prepared.vispamp"
    assert window.save_project_file(path)
    target = deepcopy(window.snapshot)
    target["timeline_identity"]["timeline_id"] = "other"
    acquired = _client(target)
    monkeypatch.setattr("vispa_mp.project_ui.open_client", lambda: acquired)
    monkeypatch.setattr(Message, "tell", lambda *args: None)
    _worker_inline(window, monkeypatch)
    window.open_project_file(path)
    assert window.client is None
    assert acquired.closes == 1


def test_cancelling_a_project_open_keeps_the_unsaved_review(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    before = deepcopy(window.proposals)
    monkeypatch.setattr(window, "_confirm_project_discard", lambda: False)
    monkeypatch.setattr("vispa_mp.project_ui.load_project", lambda *args: pytest.fail("Cancelled open read a file"))
    window.open_project_file(tmp_path / "other.vispamp")
    assert window.proposals == before


def test_save_failure_is_reported_without_switching_the_current_project_file(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    original = tmp_path / "original.vispamp"
    assert window.save_project_file(original)
    before = original.read_bytes()
    old_path = window.project_path
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))

    def fail(*args, **kwargs):
        raise OSError("Disk full")

    monkeypatch.setattr("vispa_mp.project_ui.save_project", fail)
    assert window.save_project_file(tmp_path / "new.vispamp") is False
    assert window.project_path == old_path
    assert original.read_bytes() == before
    assert "Disk full" in " ".join(str(part) for part in notices[0])


def test_project_actions_offer_open_save_and_save_as_shortcuts(qapp):
    window = MainWindow(client=None)
    assert window.project_button.menu() is window.project_menu
    actions = (window.open_project_action, window.save_project_action, window.save_project_as_action)
    assert [action.shortcut().toString() for action in actions] == ["Ctrl+O", "Ctrl+S", "Ctrl+Shift+S"]


def test_save_dialog_defaults_to_the_chosen_davinci_project_folder(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    folder = tmp_path / "DaVinci project"
    folder.mkdir()
    monkeypatch.setattr("vispa_mp.project_ui.get_project_folder", lambda _identity: folder)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs:
                        pytest.fail("The known project folder should already be selected"))
    dialogs = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: dialogs.append(args) or ("", ""))
    assert window._choose_save_project() is False
    assert len(dialogs) == 1
    assert Path(dialogs[0][2]).parent == folder
    assert Path(dialogs[0][2]).suffix == ".vispamp"


def test_the_davinci_folder_is_chosen_once_and_reused_for_save_as(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    folder = tmp_path / "DaVinci project"
    folder.mkdir()
    choices, saves = [], []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        lambda *args, **kwargs: choices.append(args) or str(folder))

    def save_dialog(*args, **kwargs):
        saves.append(args)
        return str(folder / f"prepared-{len(saves)}.vispamp"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_dialog)
    assert window._choose_save_project() is True
    assert window._choose_save_project(force_new=True) is True
    assert len(choices) == 1 and len(saves) == 2
    assert all(Path(args[2]).parent == folder for args in saves)


def test_save_as_uses_the_davinci_folder_even_when_the_previous_file_is_elsewhere(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    old_path = tmp_path / "old" / "preparation.vispamp"
    assert window.save_project_file(old_path)
    folder = tmp_path / "DaVinci project"
    folder.mkdir()
    monkeypatch.setattr("vispa_mp.project_ui.get_project_folder", lambda _identity: folder)
    dialogs = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: dialogs.append(args) or ("", ""))
    assert window._choose_save_project(force_new=True) is False
    assert Path(dialogs[0][2]) == folder / old_path.name


def test_a_damaged_project_does_not_replace_the_current_review(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    path = tmp_path / "damaged.vispamp"
    path.write_bytes(b"not a project")
    before = deepcopy(window.proposals)
    monkeypatch.setattr(window, "_confirm_project_discard", lambda: True)
    _worker_inline(window, monkeypatch)
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    window.open_project_file(path)
    assert notices
    assert window.proposals == before


def test_an_invalid_saved_view_is_rejected_without_partially_restoring_settings(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    path = tmp_path / "prepared.vispamp"
    assert window.save_project_file(path)
    with ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    metadata = json.loads(files["project.json"])
    metadata["view"]["page_format"] = "Unknown format"
    metadata["settings"]["mouth_min"] = 0.87
    files["project.json"] = json.dumps(metadata).encode("utf-8")
    with ZipFile(path, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    window.client = _client(window.snapshot)
    _worker_inline(window, monkeypatch)
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    before = window.settings()
    window.open_project_file(path)
    assert notices
    assert window.settings() == before


def test_an_out_of_range_setting_is_rejected_before_restoring_any_current_work(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    path = tmp_path / "prepared.vispamp"
    assert window.save_project_file(path)
    with ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    metadata = json.loads(files["project.json"])
    metadata["settings"]["sharpness_floor"] = 1e100
    files["project.json"] = json.dumps(metadata).encode("utf-8")
    invalid = tmp_path / "invalid-setting.vispamp"
    with ZipFile(invalid, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    window.client = _client(window.snapshot)
    _worker_inline(window, monkeypatch)
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args: notices.append(args))
    monkeypatch.setattr(window, "_restore_project", lambda *args: pytest.fail("Invalid controls reached restoration"))
    before_settings = window.settings()
    before_proposals = deepcopy(window.proposals)
    before_analysis = window.analysis
    before_path = window.project_path

    window.open_project_file(invalid)

    assert len(notices) == 1
    assert "sharpness_floor" in " ".join(str(part) for part in notices[0])
    assert window.settings() == before_settings
    assert window.proposals == before_proposals
    assert window.analysis is before_analysis
    assert window.project_path == before_path


def test_a_pending_project_load_disables_review_edits_until_the_worker_finishes(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    path = tmp_path / "prepared.vispamp"
    assert window.save_project_file(path)

    class Signal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def emit(self, *args):
            for callback in self.callbacks:
                callback(*args)

    class PendingWorker:
        def __init__(self, fn):
            self.fn = fn
            for name in ("progressed", "failed", "done", "finished"):
                setattr(self, name, Signal())

        def start(self):
            pass  # Leave the actual load pending while exercising the review.

    monkeypatch.setattr("vispa_mp.ui.Worker", PendingWorker)
    window.open_project_file(path)
    pending = window.worker
    assert pending is not None
    controls = (window.review_center, window.review_adjust, window.pages_panel, window.project_button,
                window.open_project_action, window.save_project_action, window.save_project_as_action)
    assert all(not control.isEnabled() for control in controls)
    before = deepcopy(window.proposals)
    selected, head = window.selected_frame, window.playhead_frame
    window._set_marker_color("Cyan")
    window._use_suggestion(2)
    window._arrow(1)
    assert window.proposals == before
    assert (window.selected_frame, window.playhead_frame) == (selected, head)

    pending.finished.emit()

    assert window.worker is None
    assert all(control.isEnabled() for control in controls)
    window._set_marker_color("Cyan")
    assert window.proposals[0]["color"] == "Cyan"


def test_unsaved_review_can_cancel_close_or_save_before_leaving(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    choices = iter(("cancel", "save"))
    monkeypatch.setattr(Message, "save_changes", lambda *args: next(choices))
    assert window._confirm_project_discard() is False
    saved = []
    monkeypatch.setattr(window, "_choose_save_project", lambda *args, **kwargs: saved.append(True) or True)
    assert window._confirm_project_discard() is True
    assert saved == [True]


def test_cancelling_close_leaves_the_window_open(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    monkeypatch.setattr(window, "_confirm_project_discard", lambda: False)
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted() is False

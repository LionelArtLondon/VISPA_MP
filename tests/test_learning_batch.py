"""A batch persists each completed reference before navigating to the next."""

from copy import deepcopy

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from tests.test_learning_ui import inline, local_learning, notices, prepared_window, reference
from vispa_mp import learning_batch as batch
from vispa_mp.learning_batch_ui import LearningBatchDialog


class Client:
    timeout = 10

    def __init__(self, events, failures=None):
        self.events, self.failures = events, failures or {}

    def request(self, command, **kwargs):
        assert command == "learning_open"
        name = kwargs["entry"]["name"]
        self.events.append(("open", name))
        if name in self.failures:
            raise self.failures[name]
        return {"project_name": name, "timeline_name": "Personal Learning", "script_version": 5,
                "timeline_identity": {"project_id": name, "timeline_id": name + "-timeline"},
                "fps": 25, "start_frame": 100, "end_frame": 200, "mark_in": 110, "mark_out": 190,
                "markers": [{"frame": 12, "color": "Blue"}]}


def entries():
    return [{"name": name, "folder": [], "database": {"DbName": "Local"}} for name in ("First", "Second", "Third")]


def mocked_import(monkeypatch, events, *, cancel_on=None):
    def importer(snapshot, settings, cache, **kwargs):
        name = kwargs["name"]
        events.append(("extract", name))
        assert snapshot["markers"][0]["frame"] == 112  # Raw offset normalized exactly once.
        assert kwargs["use_in_out"] is True and kwargs["include_automatic"] is False
        if cancel_on == name:
            raise InterruptedError()
        return reference(name, name)

    monkeypatch.setattr(batch, "import_timeline_reference", importer)
    monkeypatch.setattr(batch, "save_imported_reference", lambda ref: events.append(("save", ref["name"])))


def test_sequential_batch_saves_before_opening_next_and_does_not_change_settings(tmp_path, monkeypatch):
    events, progress = [], []
    mocked_import(monkeypatch, events)
    settings = {"custom": [1, 2]}
    before = deepcopy(settings)
    result = batch.import_project_batch(Client(events), entries(), settings, tmp_path, progress=progress.append)
    assert result["saved"] == 3 and not result["cancelled"] and not result["stopped_error"]
    assert events == [(kind, name) for name in ("First", "Second", "Third") for kind in ("open", "extract", "save")]
    assert settings == before
    assert [value["batch_row"] for value in progress if value["batch_state"] == "Saved"] == [0, 1, 2]


def test_one_missing_timeline_does_not_prevent_other_chapters(tmp_path, monkeypatch):
    events = []
    mocked_import(monkeypatch, events)
    client = Client(events, {"Second": RuntimeError("Learning import: missing timeline")})
    result = batch.import_project_batch(client, entries(), {}, tmp_path)
    assert result["saved"] == 2 and not result["stopped_error"]
    assert [item["status"] for item in result["outcomes"]] == ["Saved", "Failed", "Saved"]


def test_lost_bridge_stops_without_opening_later_projects(tmp_path, monkeypatch):
    events = []
    mocked_import(monkeypatch, events)
    result = batch.import_project_batch(Client(events, {"Second": RuntimeError("Resolve did not answer")}), entries(), {}, tmp_path)
    assert result["saved"] == 1 and result["stopped_error"]
    assert ("open", "Third") not in events


def test_cancel_keeps_completed_reference_and_does_not_open_next(tmp_path, monkeypatch):
    events = []
    mocked_import(monkeypatch, events, cancel_on="Second")
    result = batch.import_project_batch(Client(events), entries(), {}, tmp_path)
    assert result["saved"] == 1 and result["cancelled"]
    assert ("save", "First") in events and ("save", "Second") not in events and ("open", "Third") not in events


def test_wrong_snapshot_identity_or_project_cannot_be_imported(tmp_path, monkeypatch):
    events = []
    mocked_import(monkeypatch, events)
    client = Client(events)
    request = client.request
    client.request = lambda *args, **kwargs: dict(request(*args, **kwargs), project_name="Unrelated")
    result = batch.import_project_batch(client, entries(), {}, tmp_path)
    assert result["saved"] == 0 and all(item[0] == "open" for item in events)


def test_real_batch_import_uses_each_chapters_own_range(tmp_path, local_learning, monkeypatch):
    from tests.test_learning_data import Sources, snapshot
    from vispa_mp.learning_data import import_timeline_reference
    from vispa_mp.preset import DEFAULTS
    raw = snapshot(tmp_path)
    raw["script_version"] = 5
    raw["timeline_name"] = "Personal Learning"
    raw["markers"] = [dict(marker, frame=marker["frame"] - raw["start_frame"]) for marker in raw["markers"]]

    class Chapters:
        def request(self, command, **kwargs):
            name = kwargs["entry"]["name"]
            return dict(deepcopy(raw), project_name=name, mark_in=100 if name == "First" else 118,
                        mark_out=120 if name == "First" else 126,
                        timeline_identity={"project_id": name, "timeline_id": name + "-timeline"})

    monkeypatch.setattr(batch, "import_timeline_reference", lambda *args, **kwargs: import_timeline_reference(*args, sources=Sources(), **kwargs))
    result = batch.import_project_batch(Chapters(), entries()[:2], DEFAULTS, tmp_path / "cache")
    assert result["saved"] == 2
    references = {ref["name"]: ref for ref in local_learning.list_references()}
    assert references["First"]["source"]["range"] == [100, 120]
    assert references["Second"]["source"]["range"] == [118, 126]
    assert {sample["frame"] for sample in references["First"]["samples"] if sample["roles"]} == {103, 117}
    assert {sample["frame"] for sample in references["Second"]["samples"] if sample["roles"]} == {125}


def test_batch_dialog_lists_only_saved_projects_and_preserves_review(qapp, local_learning, notices, monkeypatch):
    window = prepared_window(qapp)
    original = deepcopy((window.snapshot, window.analysis, window.proposals))
    window._ensure_learning_dialog().approved.setChecked(True)
    window.learning_batch_dialog = LearningBatchDialog(window)
    dialog = window.learning_batch_dialog

    class LibraryClient(Client):
        def request(self, command, **kwargs):
            if command == "learning_library":
                return {"projects": entries()}
            return super().request(command, **kwargs)

    events = []
    window.client = LibraryClient(events)
    inline(window, monkeypatch)
    window._load_learning_batch_library()
    assert dialog.projects.topLevelItemCount() == 3 and not dialog.start.isEnabled()
    assert "Local" in dialog.library.text()
    assert dialog.timeline_name.text() == "Personal Learning" and dialog.in_out.isChecked()
    dialog.projects.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    assert dialog.start.isEnabled()
    monkeypatch.setattr(batch, "import_timeline_reference", lambda *args, **kwargs: reference(kwargs["name"], kwargs["name"]))
    window._start_learning_batch()
    assert [ref["name"] for ref in local_learning.list_references()] == ["First"]
    assert "1/1 references saved" in dialog.status.text()
    assert (window.snapshot, window.analysis, window.proposals) == original
    assert window.client.timeout == 10 and window._learning_profile is None


def test_project_name_keyboard_toggle_and_status_keep_their_correct_columns(qapp, local_learning, notices, monkeypatch):
    window = prepared_window(qapp)
    window._ensure_learning_dialog().approved.setChecked(True)
    window.learning_batch_dialog = LearningBatchDialog(window)
    dialog = window.learning_batch_dialog

    class Library:
        def request(self, *_args, **_kwargs):
            return {"projects": entries()}

    window.client = Library()
    inline(window, monkeypatch)
    window._load_learning_batch_library()
    dialog.show()
    qapp.processEvents()
    item = dialog.projects.topLevelItem(1)
    index = dialog.projects.indexFromItem(item, 1)
    QTest.mouseClick(dialog.projects.viewport(), Qt.MouseButton.LeftButton,
                     pos=dialog.projects.visualRect(index).center())
    QTest.keyClick(dialog.projects, Qt.Key.Key_Space)
    assert item.checkState(0) == Qt.CheckState.Checked and dialog.start.isEnabled()
    assert item.text(1) == "Second" and dialog.entries[item.data(0, Qt.ItemDataRole.UserRole)]["name"] == "Second"
    dialog._job_entries = [item]
    window._update_learning_batch_progress({"batch_row": 0, "batch_state": "Saved", "detail": "Reference saved"})
    assert item.text(2) == "Library root" and item.text(3) == "Saved"
    assert item.toolTip(3) == "Reference saved"
    QTest.keyClick(dialog.projects, Qt.Key.Key_Space)
    assert item.checkState(0) == Qt.CheckState.Unchecked and not dialog.start.isEnabled()
    viewport_height, report_height = dialog.projects.viewport().height(), dialog.report.height()
    dialog.resize(dialog.width(), dialog.height() + 200)
    qapp.processEvents()
    assert dialog.projects.viewport().height() >= viewport_height + 190
    assert dialog.report.height() == report_height
    dialog.close()


def test_old_script_gives_refresh_instruction(qapp, local_learning, notices, monkeypatch):
    window = prepared_window(qapp)
    window._ensure_learning_dialog()
    window.learning_batch_dialog = LearningBatchDialog(window)

    class OldClient:
        def request(self, *_args, **_kwargs):
            raise RuntimeError("Unknown command: learning_library")

    window.client = OldClient()
    inline(window, monkeypatch)
    window._load_learning_batch_library()
    assert "Workspace > Scripts > VISPA_MP" in notices[0][-1][3]
    assert "Workspace > Scripts > VISPA_MP" in window.learning_batch_dialog.report.toPlainText()
    assert "Reading" not in window.learning_batch_dialog.status.text()


def test_library_name_type_and_successfully_empty_library_are_explained(qapp, local_learning, notices, monkeypatch):
    window = prepared_window(qapp)
    window._ensure_learning_dialog()
    window.learning_batch_dialog = LearningBatchDialog(window)

    class EmptyLibrary:
        def request(self, *_args, **_kwargs):
            return {"database": {"DbName": "Anime Chapters", "DbType": "Disk"}, "projects": []}

    window.client = EmptyLibrary()
    inline(window, monkeypatch)
    window._load_learning_batch_library()
    dialog = window.learning_batch_dialog
    assert dialog.library.text() == "Connected library: Anime Chapters (Disk)"
    assert "read successfully" in dialog.status.text() and "no saved projects" in dialog.status.text()
    assert "Project Manager" in dialog.report.toPlainText() and "Import Project" in dialog.report.toPlainText()
    assert "Reading" not in window.learning_dialog.operation.text()
    assert not dialog.start.isEnabled() and notices[0] == []


def test_failed_refresh_removes_stale_selection_and_cannot_import(qapp, local_learning, notices, monkeypatch):
    window = prepared_window(qapp)
    window._ensure_learning_dialog().approved.setChecked(True)
    window.learning_batch_dialog = LearningBatchDialog(window)

    class Library:
        fail = False

        def request(self, *_args, **_kwargs):
            if self.fail:
                raise RuntimeError("Learning import: an invalid library name was returned.")
            return {"database": {"DbName": "Anime", "DbType": "Disk"}, "projects": entries()}

    window.client = Library()
    inline(window, monkeypatch)
    window._load_learning_batch_library()
    dialog = window.learning_batch_dialog
    dialog.projects.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    assert dialog.start.isEnabled()
    window.client.fail = True
    window._load_learning_batch_library()
    assert dialog.entries == [] and dialog.projects.topLevelItemCount() == 0 and not dialog.start.isEnabled()
    assert "not verified" in dialog.library.text()
    assert "not been confirmed empty" in dialog.status.text()
    assert "invalid library name" in dialog.report.toPlainText()
    assert "Reading" not in window.learning_dialog.operation.text()
    monkeypatch.setattr(batch, "import_project_batch", lambda *_args, **_kwargs: pytest.fail("A failed scan cannot import its stale entries"))
    window._start_learning_batch()


@pytest.mark.parametrize("result", [None, {"projects": [42]}, {"projects": []}])
def test_malformed_scan_result_has_a_visible_error_instead_of_reading_forever(qapp, local_learning, notices, monkeypatch, result):
    window = prepared_window(qapp)
    window._ensure_learning_dialog()
    window.learning_batch_dialog = LearningBatchDialog(window)

    class Malformed:
        def request(self, *_args, **_kwargs):
            return result

    window.client = Malformed()
    inline(window, monkeypatch)
    window._load_learning_batch_library()
    dialog = window.learning_batch_dialog
    assert "Could not read" in dialog.status.text()
    assert "Project Manager" in dialog.report.toPlainText()
    assert not dialog.start.isEnabled() and notices[0]


def test_failed_connection_is_reported_in_the_batch_dialog(qapp, local_learning, notices, monkeypatch):
    window = prepared_window(qapp)
    window._ensure_learning_dialog()
    window.learning_batch_dialog = LearningBatchDialog(window)

    def disconnected():
        raise RuntimeError("No Resolve connection")

    monkeypatch.setattr("vispa_mp.learning_batch_ui.open_client", disconnected)
    inline(window, monkeypatch)
    window._load_learning_batch_library()
    dialog = window.learning_batch_dialog
    assert "No Resolve connection" in dialog.report.toPlainText()
    assert "Reading" not in dialog.status.text()
    assert not dialog.start.isEnabled()

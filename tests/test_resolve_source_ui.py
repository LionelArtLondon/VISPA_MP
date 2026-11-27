"""The displayed source names must never mix two Resolve projects."""

from copy import deepcopy

from PySide6.QtCore import QCoreApplication, QEvent, Qt
import pytest

from tests.test_project_ui import _client, _review, _worker_inline
from vispa_mp.ui import MainWindow


@pytest.fixture
def window(qapp):
    current = MainWindow(client=None)
    yield current
    current._project_dirty = False
    current.close()
    current.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_reading_another_project_with_the_same_timeline_name_updates_both_names(qapp, tmp_path, monkeypatch):
    current = _review(qapp, tmp_path)
    try:
        next_source = deepcopy(current.snapshot)
        next_source["project_name"] = "Tome 06"
        next_source["timeline_identity"] = {"project_id": "project-2", "timeline_id": "timeline-2"}
        current.client = _client(next_source)
        _worker_inline(current, monkeypatch)
        monkeypatch.setattr(current, "_confirm_project_discard", lambda: True)
        monkeypatch.setattr("vispa_mp.ui.saved_analysis", lambda *_args: None)
        current.read_timeline()
        assert current.analysis is None
        assert current.timeline_label.text() == "Project: Tome 06\nTimeline: Chapter 04"
        assert "Tome 06 · Chapter 04" in current.status.text()
    finally:
        current._project_dirty = False
        current.close()
        current.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_verified_source_renames_are_shown_without_changing_the_saved_analysis(window):
    identity = {"project_id": "project-1", "timeline_id": "timeline-1"}
    window.analysis = {"timeline_identity": identity, "project_name": "Old chapter", "timeline_name": "Timeline"}
    window.snapshot = {"timeline_identity": dict(identity), "project_name": "Chapter final", "timeline_name": "Personal Learning"}
    before = deepcopy(window.analysis)
    window._sync_header()
    assert window.timeline_label.text() == "Project: Chapter final\nTimeline: Personal Learning"
    assert window.analysis == before


def test_an_unknown_legacy_project_is_not_borrowed_from_a_different_resolve_source(window):
    window.analysis = {"timeline_name": "Saved timeline"}
    window.snapshot = {"project_name": "Unrelated project", "timeline_name": "Another timeline",
                       "timeline_identity": {"project_id": "project-2", "timeline_id": "timeline-2"}}
    window._sync_header()
    assert window.timeline_label.text() == "Project: unknown\nTimeline: Saved timeline"
    assert "Unrelated project" not in window.timeline_label.toolTip()


def test_source_names_are_plain_text_and_fully_available_when_the_header_is_narrow(window, qapp):
    window.snapshot = {"project_name": "Short", "timeline_name": "Timeline"}
    window._sync_header()
    window.resize(1000, 700)
    window.show()
    qapp.processEvents()
    baseline_width = window.width()
    project = "Chapter <Final> & source " + "long-name-" * 20
    window.snapshot = {"project_name": project, "timeline_name": "Timeline <1>"}
    window._sync_header()
    window.resize(1000, 700)
    window.show()
    qapp.processEvents()
    assert window.timeline_label.textFormat() == Qt.TextFormat.PlainText
    assert project in window.timeline_label.toolTip()
    assert project in window.timeline_label.accessibleName()
    assert window.width() == baseline_width
    assert window.timeline_label.grab().width() == window.timeline_label.width()

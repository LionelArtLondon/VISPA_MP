"""Recent reviews are convenient entry points into the normal guarded opener."""

from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QFileDialog

from tests.test_project_ui import _client, _review, _worker_inline
from vispa_mp import recent_projects
from vispa_mp.ui import MainWindow, Message


@pytest.fixture
def windows(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("vispa_mp.project_location.LOCATION_PATH", tmp_path / "locations.json")
    notices = []
    monkeypatch.setattr(Message, "tell", lambda *args, **_kwargs: notices.append(args))
    created = []

    def create(*, prepared=False):
        window = _review(qapp, tmp_path) if prepared else MainWindow(client=None)
        created.append(window)
        window._resolve_timer.stop()
        return window

    yield create, notices
    for window in created:
        window.worker = None
        window._project_dirty = False
        window._resolve_timer.stop()
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def refresh_menu(window):
    window.recent_projects_menu.aboutToShow.emit()
    return window.recent_projects_menu


def file_actions(window):
    return [action for action in refresh_menu(window).actions()
            if isinstance(action.data(), str) and action.data()]


def recent_paths():
    return [Path(path) for path in recent_projects.load_recent()]


def action_for(window, path):
    return next(action for action in file_actions(window) if Path(action.data()) == path.resolve())


def test_empty_recent_menu_explains_that_there_are_no_saved_entries(windows):
    create, _notices = windows
    window = create()
    menu = refresh_menu(window)
    assert menu.menuAction() in window.project_menu.actions()
    assert file_actions(window) == []
    placeholder = next(action for action in menu.actions() if action.text() == "No recent projects")
    assert not placeholder.isEnabled()


def test_successful_saves_form_a_persistent_mru_list_across_main_windows(windows, tmp_path, user_settings):
    create, notices = windows
    original = create(prepared=True)
    paths = [tmp_path / f"chapter-{index:02d}.vispamp" for index in range(12)]
    for path in paths:
        assert original.save_project_file(path)
    assert original.save_project_file(paths[4])
    expected = [paths[4], *reversed(paths[5:]), paths[3], paths[2]]
    assert recent_paths() == expected
    assert user_settings.with_name("recent-projects.json").is_file()
    reopened = create()
    assert [Path(action.data()) for action in file_actions(reopened)] == expected
    assert all(action.isEnabled() for action in file_actions(reopened))
    assert notices == []


def test_a_successful_open_promotes_the_file_after_the_review_has_been_restored(windows, tmp_path, monkeypatch):
    create, notices = windows
    source = create(prepared=True)
    first, second = tmp_path / "first.vispamp", tmp_path / "second.vispamp"
    assert source.save_project_file(first)
    assert source.save_project_file(second)
    restored = create()
    restored.client = _client(source.snapshot)
    _worker_inline(restored, monkeypatch)
    monkeypatch.setattr(restored, "_cache_dir", lambda: tmp_path / "loaded-cache")
    action_for(restored, first).trigger()
    assert restored.project_path == first
    assert restored.selected_frame == source.selected_frame
    assert restored.proposals[0]["color"] == source.proposals[0]["color"]
    assert recent_paths() == [first, second]
    assert [Path(action.data()) for action in file_actions(restored)] == [first, second]
    assert restored.client.reads == 1
    assert notices == []


def test_a_failed_save_does_not_remember_or_promote_its_destination(windows, tmp_path, monkeypatch):
    create, notices = windows
    window = create(prepared=True)
    original, failed = tmp_path / "original.vispamp", tmp_path / "failed.vispamp"
    assert window.save_project_file(original)
    before = recent_paths()

    def fail(*_args, **_kwargs):
        raise OSError("Disk full")

    monkeypatch.setattr("vispa_mp.project_ui.save_project", fail)
    assert not window.save_project_file(failed)
    assert recent_paths() == before
    assert window.project_path == original
    assert not failed.exists()
    assert notices


def test_a_cancelled_save_dialog_does_not_add_a_recent_file(windows, tmp_path, monkeypatch):
    create, _notices = windows
    window = create(prepared=True)
    monkeypatch.setattr("vispa_mp.project_ui.get_project_folder", lambda _identity: tmp_path)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: ("", ""))
    assert not window._choose_save_project(force_new=True)
    assert recent_paths() == []
    assert file_actions(window) == []


def test_a_broken_recent_file_does_not_replace_the_review_or_change_mru(windows, tmp_path, monkeypatch):
    create, notices = windows
    window = create(prepared=True)
    broken = tmp_path / "broken.vispamp"
    broken.write_bytes(b"not a VISPA MP project")
    recent_projects.remember_project(broken)
    current = tmp_path / "current.vispamp"
    assert window.save_project_file(current)
    before = deepcopy((window.proposals, window.snapshot, window.analysis, recent_paths()))
    _worker_inline(window, monkeypatch)
    monkeypatch.setattr(window, "_cache_dir", lambda: tmp_path / "failed-cache")
    action_for(window, broken).trigger()
    assert (window.proposals, window.snapshot, window.analysis, recent_paths()) == before
    assert window.project_path == current
    assert notices


def test_recent_open_honors_unsaved_work_cancellation_before_reading_a_file(windows, tmp_path, monkeypatch):
    create, _notices = windows
    window = create(prepared=True)
    target = tmp_path / "target.vispamp"
    assert window.save_project_file(target)
    current = tmp_path / "current.vispamp"
    assert window.save_project_file(current)
    window._set_marker_color("Cyan")
    before = deepcopy((window.proposals, recent_paths()))
    confirmations = []
    monkeypatch.setattr(Message, "save_changes", lambda _window:
                        confirmations.append(True) or "cancel")
    monkeypatch.setattr("vispa_mp.project_ui.load_project", lambda *_args, **_kwargs:
                        pytest.fail("Cancelling a recent open must not load the file"))
    action_for(window, target).trigger()
    assert confirmations == [True]
    assert (window.proposals, recent_paths()) == before
    assert window.project_path == current and window._project_dirty


def test_recent_open_keeps_resolve_identity_validation_and_does_not_promote_rejected_files(windows, tmp_path, monkeypatch):
    create, notices = windows
    window = create(prepared=True)
    target, current = tmp_path / "target.vispamp", tmp_path / "current.vispamp"
    assert window.save_project_file(target)
    assert window.save_project_file(current)
    live = deepcopy(window.snapshot)
    live["timeline_identity"]["project_id"] = "another-Resolve-project"
    window.client = _client(live)
    _worker_inline(window, monkeypatch)
    monkeypatch.setattr(window, "_cache_dir", lambda: tmp_path / "identity-cache")
    before = deepcopy((window.proposals, window.snapshot, window.analysis, recent_paths()))
    action_for(window, target).trigger()
    assert (window.proposals, window.snapshot, window.analysis, recent_paths()) == before
    assert window.project_path == current
    assert window.client.reads == 1
    assert notices and "Resolve" in " ".join(str(part) for part in notices[-1])


def test_recent_entries_keep_full_paths_and_disambiguate_duplicate_filenames(windows, tmp_path):
    create, _notices = windows
    files = [tmp_path / folder / "selection.vispamp" for folder in ("Chapter A", "Chapter B")]
    for path in files:
        path.parent.mkdir()
        path.touch()
        recent_projects.remember_project(path)
    window = create()
    actions = file_actions(window)
    assert len(actions) == 2
    assert actions[0].text() != actions[1].text()
    for action in actions:
        path = Path(action.data())
        assert path.is_absolute()
        assert path.name in action.text()
        assert path.parent.name in action.text()
        assert action.toolTip() == str(path)


def test_missing_recent_files_are_visible_but_disabled_and_can_be_cleared_without_deletion(windows, tmp_path):
    create, _notices = windows
    present, missing = tmp_path / "present.vispamp", tmp_path / "missing.vispamp"
    present.write_bytes(b"keep this file")
    missing.touch()
    recent_projects.remember_project(present)
    recent_projects.remember_project(missing)
    missing.unlink()
    window = create()
    action = action_for(window, missing)
    assert "(missing)" in action.text()
    assert not action.isEnabled()
    assert action_for(window, present).isEnabled()
    clear = next(action for action in refresh_menu(window).actions()
                 if action.text() == "Clear recent projects")
    assert clear.isEnabled()
    clear.trigger()
    assert recent_paths() == []
    assert file_actions(window) == []
    assert present.read_bytes() == b"keep this file"
    assert not missing.exists()


def test_recent_action_routes_to_the_normal_opener_at_activation_time(windows, tmp_path, monkeypatch):
    create, _notices = windows
    path = tmp_path / "review.vispamp"
    path.touch()
    recent_projects.remember_project(path)
    window = create()
    action = action_for(window, path)
    calls = []
    monkeypatch.setattr(window, "open_project_file", lambda selected: calls.append(Path(selected)))
    action.trigger()
    assert calls == [path]


def test_busy_review_disables_recent_projects_and_restores_them_when_idle(windows, tmp_path):
    create, _notices = windows
    path = tmp_path / "review.vispamp"
    path.touch()
    recent_projects.remember_project(path)
    window = create()
    assert refresh_menu(window).isEnabled()
    window.worker = object()
    window._set_review_busy(True)
    try:
        menu = refresh_menu(window)
        assert not menu.isEnabled()
        assert not menu.menuAction().isEnabled()
    finally:
        window.worker = None
        window._set_review_busy(False)
    assert refresh_menu(window).isEnabled()
    assert action_for(window, path).isEnabled()


@pytest.mark.parametrize("busy", ["worker", "learning"])
def test_an_already_displayed_recent_action_cannot_open_after_an_operation_starts(windows, tmp_path, monkeypatch, busy):
    create, _notices = windows
    path = tmp_path / "review.vispamp"
    path.touch()
    recent_projects.remember_project(path)
    window = create()
    action = action_for(window, path)
    calls = []
    monkeypatch.setattr(window, "open_project_file", lambda selected: calls.append(selected))
    if busy == "worker":
        window.worker = object()
    else:
        window._learning_job_busy = True
    try:
        action.trigger()
        assert calls == []
        assert not refresh_menu(window).isEnabled()
    finally:
        window.worker = None
        window._learning_job_busy = False


def test_a_recent_history_write_failure_does_not_undo_a_successful_project_save(windows, tmp_path, monkeypatch):
    create, _notices = windows
    window = create(prepared=True)
    target = tmp_path / "saved.vispamp"

    def fail(_path):
        raise OSError("Recent list is read-only")

    monkeypatch.setattr("vispa_mp.project_ui.remember_project", fail)
    assert window.save_project_file(target)
    assert target.is_file()
    assert window.project_path == target
    assert window._project_dirty is False
    assert recent_paths() == []

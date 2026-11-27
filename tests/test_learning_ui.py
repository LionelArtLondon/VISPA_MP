"""Approved references never replace the live review or activate a profile implicitly."""

from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest

from tests.test_ui import action_analysis
from vispa_mp.learning_model import FEATURE_NAMES, save_profile, train_profile
from vispa_mp.ui import MainWindow, Message
from vispa_mp.learning_ui import profile_report


def reference(group="chapter-a", name="Approved chapter"):
    def sample(number, role, **values):
        features = [0.0] * len(FEATURE_NAMES)
        for key, value in values.items():
            features[FEATURE_NAMES.index(key)] = value
        return {"frame": number, "shot": 0, "features": features, "roles": role}
    return {
        "kind": "vispa-mp-reference", "version": 1, "id": group, "name": name,
        "group_id": group, "feature_names": list(FEATURE_NAMES),
        "samples": [sample(0, ["core", "page"], open_mouth=1, expression=1),
                    sample(12, [], sharpness=1),
                    sample(24, ["extra"], motion=1, expression=0.5),
                    sample(36, [], closed_mouth=1)],
        "timebase": {"fps": 24},
        "summary": {"markers": 2, "core": 1, "page": 1, "extra": 1, "samples": 4,
                    "unlabelled": 2, "ignored_automatic": 0, "ignored_other_colors": 0},
    }


@pytest.fixture
def local_learning(tmp_path, monkeypatch):
    import vispa_mp.learning_data as data
    monkeypatch.setattr(data, "REFERENCES_DIR", tmp_path / "references")
    monkeypatch.setattr(data, "PROFILES_DIR", tmp_path / "profiles")
    return data


@pytest.fixture
def notices(monkeypatch):
    messages, questions = [], []
    monkeypatch.setattr(Message, "tell", lambda *args: messages.append(args))
    monkeypatch.setattr(Message, "ask", lambda *args: questions.append(args) or True)
    return messages, questions


def inline(window, monkeypatch):
    monkeypatch.setattr(window, "_start", lambda work, done: done(work(lambda _value: None)))


def prepared_window(qapp):
    window = MainWindow(client=None)
    window.show_analysis(action_analysis())
    window._project_dirty = False
    return window


def test_learning_dialog_is_lazy_and_empty_corpus_cannot_train(qapp, local_learning, notices):
    window = MainWindow()
    assert window.learning_dialog is None
    assert window._learning_profile is None
    assert window.learning_button.text() == "Learning"
    window._refresh_learning_lists()
    dialog = window.learning_dialog
    assert dialog.references.topLevelItemCount() == 0
    assert not dialog.train.isEnabled()
    assert "standard rules" in dialog.active.text()
    window._train_learning_profile()
    assert "at least one" in notices[0][-1][2]
    assert window._learning_profile is None


def test_reference_list_counts_green_as_core_and_separates_source_groups(qapp, local_learning):
    local_learning.save_reference(reference())
    local_learning.save_reference(reference("chapter-b", "Second chapter"))
    window = MainWindow()
    window._refresh_learning_lists()
    table = window.learning_dialog.references
    assert table.topLevelItemCount() == 2
    assert table.topLevelItem(0).text(2) == "1"
    assert table.topLevelItem(0).text(3) == "1"
    assert table.topLevelItem(0).text(4) == "1"
    assert window.learning_dialog.validation.count() == 3
    assert window.learning_dialog.train.isEnabled()


def test_opaque_source_identifiers_stay_in_item_data_instead_of_product_labels(qapp, local_learning):
    group = "media-" + "abc123" * 10
    local_learning.save_reference(reference(group, "Chapter four"))
    window = MainWindow()
    window._refresh_learning_lists()
    dialog = window.learning_dialog
    row = dialog.references.topLevelItem(0)
    assert row.text(1) == "Chapter four"
    assert "media-" not in dialog.validation.itemText(1)
    assert dialog.validation.itemData(1) == group
    profile = train_profile([reference(group, "Chapter four"),
                             reference("media-" + "f" * 60, "Chapter five")])
    text = profile_report(profile)
    assert "Chapter five" in text
    assert "media-" not in text


def test_unapproved_choices_cannot_read_resolve(qapp, local_learning, notices):
    window = MainWindow()

    class NoRead:
        def read(self):
            pytest.fail("Unapproved reference choices cannot be imported")

    window.client = NoRead()
    window._import_current_learning_reference()
    assert "approve" in notices[0][-1][2]
    assert notices[1] == []


def _resolve_client():
    class Client:
        reads = 0
        closes = 0

        def read(self):
            self.reads += 1
            return {"project_name": "Manual chapter", "timeline_name": "Chapter 4",
                    "script_version": 5, "fps": 24, "start_frame": 90000, "end_frame": 90100,
                    "video_clips": [], "audio_clips": [],
                    "markers": [{"frame": 12, "color": "Blue", "automatic": False},
                                {"frame": 24, "color": "Cyan", "automatic": True}], "warnings": []}

        def close(self):
            self.closes += 1

        def apply(self, *args, **kwargs):
            pytest.fail("Learning import must not write Resolve markers")

    return Client()


def test_resolve_import_is_read_only_and_preserves_the_current_review(qapp, local_learning, notices, monkeypatch):
    window = prepared_window(qapp)
    client = _resolve_client()
    window.client = client
    original = deepcopy((window.snapshot, window.analysis, window.proposals))
    dialog = window._ensure_learning_dialog()
    dialog.approved.setChecked(True)
    dialog.reference_name.setText("My approved chapter")
    dialog.reference_group.setText("episode-four")
    received = []

    def import_reference(snapshot, settings, cache, **kwargs):
        received.append((deepcopy(snapshot), deepcopy(settings), kwargs))
        return reference()

    monkeypatch.setattr(local_learning, "import_timeline_reference", import_reference)
    inline(window, monkeypatch)
    window._import_current_learning_reference()
    qapp.processEvents()
    assert len(received) == 1
    snapshot, _settings, options = received[0]
    assert snapshot["markers"][0]["frame"] == 90012
    assert options["include_automatic"] is False
    assert options["name"] == "My approved chapter" and options["group_id"] == "episode-four"
    assert "1 approved markers" in notices[1][0][2]
    assert client.reads == 1 and client.closes == 0
    assert (window.snapshot, window.analysis, window.proposals) == original
    assert window._project_dirty is False
    assert len(local_learning.list_references()) == 1


def test_cancelled_reference_confirmation_never_extracts_or_saves(qapp, local_learning, notices, monkeypatch):
    window = MainWindow(client=_resolve_client())
    window._ensure_learning_dialog().approved.setChecked(True)
    monkeypatch.setattr(Message, "ask", lambda *args: False)
    monkeypatch.setattr(local_learning, "import_timeline_reference", lambda *args, **kwargs:
                        pytest.fail("Cancelled reference must not extract video frames"))
    inline(window, monkeypatch)
    window._import_current_learning_reference()
    qapp.processEvents()
    assert local_learning.list_references() == []


def test_reference_include_automatic_requires_explicit_option(qapp, local_learning, notices, monkeypatch):
    window = MainWindow(client=_resolve_client())
    dialog = window._ensure_learning_dialog()
    dialog.approved.setChecked(True)
    dialog.include_automatic.setChecked(True)
    imported = []
    monkeypatch.setattr(local_learning, "import_timeline_reference", lambda *args, **kwargs:
                        imported.append(kwargs) or reference())
    inline(window, monkeypatch)
    window._import_current_learning_reference()
    qapp.processEvents()
    assert imported[0]["include_automatic"] is True
    assert "2 approved markers" in notices[1][0][2]


def test_second_import_stage_waits_until_the_read_worker_has_finished(qapp, local_learning, notices, monkeypatch):
    window = MainWindow(client=_resolve_client())
    window._ensure_learning_dialog().approved.setChecked(True)
    imported, phases = [], []
    monkeypatch.setattr(local_learning, "import_timeline_reference", lambda *args, **kwargs:
                        imported.append(kwargs) or reference())

    class Signal:
        callbacks = None

        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def emit(self):
            for callback in self.callbacks:
                callback()

    class ReadWorker:
        finished = Signal()

    held = ReadWorker()

    def start(work, done):
        phases.append("read" if not phases else "extract")
        if len(phases) == 1:
            window.worker = held
        done(work(lambda _value: None))

    monkeypatch.setattr(window, "_start", start)
    window._import_current_learning_reference()
    qapp.processEvents()
    assert phases == ["read"] and imported == []
    # Real Worker.done is emitted before Worker.finished; only the latter frees
    # MainWindow.worker and allows the extraction phase to start.
    window.worker = None
    held.finished.emit()
    QTest.qWait(25)
    assert phases == ["read", "extract"]
    assert len(imported) == 1
    assert not window._learning_job_busy


def test_a_review_file_can_be_imported_without_resolve_or_replacing_live_choices(qapp, local_learning, notices, monkeypatch, tmp_path):
    import vispa_mp.learning_ui as ui
    window = prepared_window(qapp)
    window._ensure_learning_dialog().approved.setChecked(True)
    before = deepcopy((window.snapshot, window.analysis, window.proposals))
    project = {"approved": "portable choices"}
    seen = []
    monkeypatch.setattr(ui.QFileDialog, "getOpenFileName", lambda *args: (str(tmp_path / "approved.vispamp"), ""))
    monkeypatch.setattr(ui, "load_project", lambda *args: project)
    monkeypatch.setattr(local_learning, "reference_from_project", lambda value, **kwargs:
                        seen.append(value) or reference())
    monkeypatch.setattr(ui, "open_client", lambda: pytest.fail("Portable reference import does not connect to Resolve"))
    inline(window, monkeypatch)
    window._import_learning_project()
    assert seen == [project]
    assert (window.snapshot, window.analysis, window.proposals) == before
    assert window._learning_profile is None


def test_training_saves_a_real_profile_but_activation_requires_a_separate_action(qapp, local_learning, notices, monkeypatch):
    local_learning.save_reference(reference())
    window = prepared_window(qapp)
    window._refresh_learning_lists()
    window.learning_dialog.profile_name.setText("My illustrated chapters")
    original = deepcopy(window.proposals)
    inline(window, monkeypatch)
    window._train_learning_profile()
    assert len(list(local_learning.PROFILES_DIR.glob("*.json"))) == 1
    assert window._learning_profile is None
    assert window.proposals == original
    assert "not independently validated" in window.learning_dialog.report.toPlainText().lower()
    assert "Use selected profile" in window.learning_dialog.operation.text()
    path = Path(window.learning_dialog.profiles.currentData())
    assert path.is_file()
    recomputes = []
    monkeypatch.setattr(window, "recompute", lambda: recomputes.append(True))
    window._activate_learning_profile()
    assert window._learning_profile["name"] == "My illustrated chapters"
    assert window._stored_settings["learning_profile"] == str(path)
    assert recomputes == [True]
    assert window._project_dirty is True
    assert "My illustrated chapters" in window.learning_button.toolTip()
    window.learning_dialog.profiles.setCurrentIndex(0)
    window._activate_learning_profile()
    assert window._learning_profile is None
    assert window._stored_settings["learning_profile"] == ""
    assert recomputes == [True, True]


def test_profile_report_names_the_visual_baseline_and_keeps_validation_honest():
    one = train_profile([reference()], name="One chapter")
    text = profile_report(one)
    assert "Not independently validated" in text
    assert "not the accuracy of a complete page layout" in text
    two = train_profile([reference(), reference("chapter-b")], name="Two chapters")
    text = profile_report(two)
    assert "excluded from training" in text
    assert "visual baseline" in text
    assert "standard 100" not in text


def test_embedded_profile_restore_is_portable_and_does_not_recompute(qapp, local_learning, monkeypatch):
    window = prepared_window(qapp)
    profile = train_profile([reference()], name="Embedded")
    monkeypatch.setattr(window, "recompute", lambda:
                        pytest.fail("Restoring an embedded profile must preserve saved marker choices"))
    window._restore_learning_profile(profile)
    assert window._learning_profile == profile
    assert window._stored_settings["learning_profile"] == ""
    embedded = window._project_learning_profile()
    embedded["name"] = "Changed copy"
    assert window._learning_profile["name"] == "Embedded"
    window._refresh_learning_lists()
    assert window.learning_dialog.profiles.currentData() == "embedded"
    window._restore_learning_profile(None)
    assert window._learning_profile is None
    assert window._project_learning_profile() is None


def test_missing_saved_profile_falls_back_to_standard_without_startup_modal(qapp, local_learning, notices, tmp_path):
    window = MainWindow()
    window._stored_settings["learning_profile"] = str(tmp_path / "missing.json")
    window._load_selected_learning_profile()
    assert window._learning_profile is None
    assert window._stored_settings["learning_profile"] == ""
    assert "could not be loaded" in window.status.text()
    assert notices[0] == []


def test_an_external_active_profile_is_present_in_the_dialog(qapp, local_learning, tmp_path):
    profile = train_profile([reference()], name="External")
    path = tmp_path / "external.json"
    save_profile(profile, path)
    window = MainWindow()
    window._stored_settings["learning_profile"] = str(path)
    window._load_selected_learning_profile()
    window._refresh_learning_lists()
    assert window.learning_dialog.profiles.currentData() == str(path.resolve())
    assert window.learning_dialog.profiles.currentText() == "External"


def test_loading_an_invalid_profile_keeps_the_current_profile(qapp, local_learning, notices, monkeypatch, tmp_path):
    import vispa_mp.learning_ui as ui
    window = MainWindow()
    current = train_profile([reference()], name="Keep")
    window._restore_learning_profile(current)
    corrupt = tmp_path / "bad.json"
    corrupt.write_text('{"kind":"wrong"}', encoding="utf-8")
    monkeypatch.setattr(ui.QFileDialog, "getOpenFileName", lambda *args: (str(corrupt), ""))
    window._load_learning_profile_file()
    assert window._learning_profile == current
    assert "cannot be loaded" in notices[0][-1][2]


def test_cancel_operation_disables_new_actions_but_leaves_the_current_review(qapp, local_learning, notices):
    window = prepared_window(qapp)
    dialog = window._ensure_learning_dialog()
    before = deepcopy(window.proposals)
    import threading
    window._learning_stop = threading.Event()
    window._set_learning_busy(True, "Training…")
    assert not dialog.import_resolve.isEnabled()
    assert dialog.cancel.isEnabled()
    window._cancel_learning_job()
    assert window._learning_stop.is_set()
    assert not dialog.cancel.isEnabled()
    assert window._handle_learning_failure("Stopped") is True
    assert window.proposals == before
    assert not window._learning_job_busy
    assert notices[0] == []


def test_long_import_progress_is_visible_in_the_dialog_and_can_still_be_cancelled(qapp, local_learning):
    window = MainWindow()
    dialog = window._ensure_learning_dialog()
    window._set_learning_busy(True, "Preparing reference…")
    window._update_learning_progress("Training Core preferences…")
    assert dialog.operation.text() == "Training Core preferences…"
    assert dialog.progress.minimum() == 0 and dialog.progress.maximum() == 0
    window._update_learning_progress({"step": 4, "steps": 5, "label": "Extracting images",
                                      "fraction": 0.5, "detail": "10/20 marked images", "left": "about 1 min left"})
    assert "10/20 marked images" in dialog.operation.text()
    assert dialog.progress.value() == 70
    assert dialog.cancel.isEnabled()
    assert not dialog.import_resolve.isEnabled()
    window._learning_job_finished()
    assert dialog.progress.isHidden()


def test_progress_does_not_replace_the_cancel_request_message(qapp, local_learning):
    import threading
    window = MainWindow()
    dialog = window._ensure_learning_dialog()
    window._learning_stop = threading.Event()
    window._set_learning_busy(True)
    window._cancel_learning_job()
    window._update_learning_progress("Late progress from current step")
    assert "Cancelling" in dialog.operation.text()
    window._learning_job_finished()


def test_failed_reference_refresh_cannot_train_on_a_stale_corpus(qapp, local_learning, monkeypatch):
    local_learning.save_reference(reference())
    window = MainWindow()
    window._refresh_learning_lists()
    assert window.learning_dialog.train.isEnabled()
    monkeypatch.setattr(local_learning, "list_references", lambda:
                        (_ for _ in ()).throw(ValueError("Unreadable reference")))
    with pytest.raises(ValueError, match="Unreadable"):
        window._refresh_learning_lists()
    assert window._learning_refs == []
    assert window.learning_dialog.references.topLevelItemCount() == 0
    assert not window.learning_dialog.train.isEnabled()


def test_active_profile_path_is_restored_on_the_next_launch(qapp, local_learning, user_settings, tmp_path):
    profile = train_profile([reference()], name="Remember my choices")
    path = tmp_path / "remember.json"
    save_profile(profile, path)
    window = MainWindow()
    window._stored_settings["learning_profile"] = str(path)
    window._load_selected_learning_profile()
    window.save_settings()
    assert user_settings.is_file()
    reopened = MainWindow()
    assert reopened._learning_profile == profile
    assert reopened._learning_profile_path == str(path.resolve())


def test_loading_marker_settings_can_select_a_saved_profile(qapp, local_learning, tmp_path):
    profile = train_profile([reference()], name="Preset profile")
    profile_path = tmp_path / "preset-profile.json"
    save_profile(profile, profile_path)
    window = MainWindow()
    window._stored_settings["learning_profile"] = str(profile_path)
    settings_path = tmp_path / "settings.json"
    window.save_settings_file(settings_path)
    window._restore_learning_profile(None)
    assert window._learning_profile is None
    window.load_settings_file(settings_path)
    assert window._learning_profile == profile


def _reference_item(window, identifier):
    tree = window.learning_dialog.references
    return next(tree.topLevelItem(index) for index in range(tree.topLevelItemCount())
                if tree.topLevelItem(index).data(0, Qt.ItemDataRole.UserRole) == identifier)


def test_reference_checkboxes_persist_and_only_active_groups_reach_training_choices(qapp, local_learning, monkeypatch):
    local_learning.save_reference(reference("chapter-a", "First chapter"))
    local_learning.save_reference(reference("chapter-b", "Second chapter"))
    window = prepared_window(qapp)
    before = deepcopy(window.proposals)
    profile = train_profile([reference()], name="Already active")
    window._restore_learning_profile(profile)
    window._refresh_learning_lists()
    dialog = window.learning_dialog
    monkeypatch.setattr(window, "recompute", lambda: pytest.fail("Corpus selection must not change the open review"))
    assert dialog.validate_corpus.isEnabled()
    assert _reference_item(window, "chapter-a").checkState(0) == Qt.CheckState.Checked
    item = _reference_item(window, "chapter-b")
    item.setCheckState(0, Qt.CheckState.Unchecked)
    assert item is _reference_item(window, "chapter-b")  # Qt's current item stays alive through itemChanged.
    assert [ref["id"] for ref in window._active_learning_references()] == ["chapter-a"]
    assert dialog.validation.findData("chapter-b") == -1
    assert not dialog.validate_corpus.isEnabled()
    stored = {ref["id"]: ref for ref in local_learning.list_references()}
    assert stored["chapter-b"]["enabled"] is False
    assert window._learning_profile == profile and window.proposals == before
    # A fast second toggle is based on the saved selection, not the initial list.
    item.setCheckState(0, Qt.CheckState.Checked)
    assert dialog.validate_corpus.isEnabled()
    assert dialog.validation.findData("chapter-b") >= 0
    _reference_item(window, "chapter-a").setCheckState(0, Qt.CheckState.Unchecked)
    _reference_item(window, "chapter-b").setCheckState(0, Qt.CheckState.Unchecked)
    assert not dialog.train.isEnabled() and not dialog.validate_corpus.isEnabled()
    assert window._learning_profile == profile
    reopened = MainWindow()
    reopened._refresh_learning_lists()
    assert all(ref.get("enabled") is False for ref in reopened._learning_refs)
    assert _reference_item(reopened, "chapter-a").checkState(0) == Qt.CheckState.Unchecked


def test_reference_checkbox_failure_keeps_previous_ui_and_saved_selection(qapp, local_learning, notices, monkeypatch):
    local_learning.save_reference(reference())
    window = MainWindow()
    window._refresh_learning_lists()
    monkeypatch.setattr(local_learning, "update_reference", lambda *args, **kwargs:
                        (_ for _ in ()).throw(OSError("Read-only reference folder")))
    item = _reference_item(window, "chapter-a")
    item.setCheckState(0, Qt.CheckState.Unchecked)
    assert item.checkState(0) == Qt.CheckState.Checked
    assert window._active_learning_references()[0]["id"] == "chapter-a"
    assert local_learning.list_references()[0].get("enabled", True) is True
    assert "previous selection was kept" in notices[0][-1][2]


def test_refresh_does_not_save_checkbox_values_or_change_profile(qapp, local_learning, monkeypatch):
    selected = reference()
    selected["enabled"] = False
    local_learning.save_reference(selected)
    window = MainWindow()
    monkeypatch.setattr(local_learning, "update_reference", lambda *args, **kwargs:
                        pytest.fail("Refreshing the table must not save checkbox state"))
    window._refresh_learning_lists()
    window._refresh_learning_lists()
    assert _reference_item(window, "chapter-a").checkState(0) == Qt.CheckState.Unchecked
    assert window._learning_profile is None


def test_training_receives_only_checked_references(qapp, local_learning, notices, monkeypatch):
    import vispa_mp.learning_model as model
    local_learning.save_reference(reference("chapter-a", "Included"))
    excluded = reference("chapter-b", "Excluded")
    excluded["enabled"] = False
    local_learning.save_reference(excluded)
    window = MainWindow()
    window._refresh_learning_lists()
    trained = []
    original_train = model.train_profile

    def train(references, **kwargs):
        trained.extend(ref["id"] for ref in references)
        return original_train(references, **kwargs)

    monkeypatch.setattr(model, "train_profile", train)
    inline(window, monkeypatch)
    window._train_learning_profile()
    assert trained == ["chapter-a"]
    assert window._learning_profile is None
    assert window.learning_dialog.validation.findData("chapter-b") == -1


def test_source_group_can_be_edited_for_multiple_selected_references(qapp, local_learning, monkeypatch):
    import vispa_mp.learning_ui as ui
    local_learning.save_reference(reference("media-" + "a" * 32, "Chapter four v1"))
    local_learning.save_reference(reference("chapter-b", "Chapter four v2"))
    window = prepared_window(qapp)
    before = deepcopy(window.proposals)
    window._refresh_learning_lists()
    for ref in window._learning_refs:
        _reference_item(window, ref["id"]).setSelected(True)
    prompts = []
    monkeypatch.setattr(ui.QInputDialog, "getText", lambda *args:
                        prompts.append(args) or (" Chapter four ", True))
    monkeypatch.setattr(window, "recompute", lambda: pytest.fail("Group edits cannot replace the review"))
    assert window.learning_dialog.edit_source_group.isEnabled()
    window._edit_learning_source_group()
    assert {ref["group_id"] for ref in local_learning.list_references()} == {"Chapter four"}
    assert window.learning_dialog.validation.count() == 2
    assert not window.learning_dialog.validate_corpus.isEnabled()
    assert window.proposals == before and window._learning_profile is None
    assert "all versions" in prompts[0][2]
    assert all(_reference_item(window, ref["id"]).text(1) == "Chapter four" for ref in window._learning_refs)


def test_single_automatic_group_has_a_readable_edit_default_and_cancel_is_noop(qapp, local_learning, monkeypatch):
    import vispa_mp.learning_ui as ui
    identifier = "media-" + "f" * 40
    local_learning.save_reference(reference(identifier, "Desert chapter"))
    window = MainWindow()
    window._refresh_learning_lists()
    _reference_item(window, identifier).setSelected(True)
    prompts = []
    monkeypatch.setattr(ui.QInputDialog, "getText", lambda *args:
                        prompts.append(args) or ("Ignored", False))
    window._edit_learning_source_group()
    assert prompts[0][-1] == "Desert chapter"
    assert local_learning.list_references()[0]["group_id"] == identifier


def test_group_batch_save_failure_rolls_back_previously_changed_groups(qapp, local_learning, notices, monkeypatch):
    import vispa_mp.learning_ui as ui
    local_learning.save_reference(reference("chapter-a"))
    local_learning.save_reference(reference("chapter-b"))
    window = MainWindow()
    window._refresh_learning_lists()
    originals = {ref["id"]: ref["group_id"] for ref in window._learning_refs}
    failing = window._learning_refs[1]["id"]
    for ref in window._learning_refs:
        _reference_item(window, ref["id"]).setSelected(True)
    monkeypatch.setattr(ui.QInputDialog, "getText", lambda *args: ("New group", True))
    update = local_learning.update_reference

    def fail_second(identifier, **kwargs):
        if identifier == failing and kwargs.get("group_id") == "New group":
            raise OSError("Second reference could not be written")
        return update(identifier, **kwargs)

    monkeypatch.setattr(local_learning, "update_reference", fail_second)
    window._edit_learning_source_group()
    assert {ref["id"]: ref["group_id"] for ref in local_learning.list_references()} == originals
    assert "previous groups were kept" in notices[0][-1][2]


def test_corpus_tools_are_disabled_during_a_job_and_wired_to_validation_owner(qapp, local_learning, monkeypatch):
    local_learning.save_reference(reference("chapter-a"))
    local_learning.save_reference(reference("chapter-b"))
    window = MainWindow()
    window._refresh_learning_lists()
    _reference_item(window, "chapter-a").setSelected(True)
    dialog = window.learning_dialog
    calls = []
    monkeypatch.setattr(window, "_validate_learning_corpus", lambda: calls.append("validate"), raising=False)
    monkeypatch.setattr(window, "_show_learning_validation_report", lambda: calls.append("view"), raising=False)
    dialog.validate_corpus.click()
    assert calls == ["validate"]
    window._set_learning_busy(True)
    assert not dialog.validate_corpus.isEnabled()
    assert not dialog.edit_source_group.isEnabled()
    assert not dialog.view_validation.isEnabled()
    window._learning_job_finished()
    assert dialog.validate_corpus.isEnabled() and dialog.edit_source_group.isEnabled()
    monkeypatch.setattr(window, "_update_learning_corpus_summary", lambda:
                        dialog.view_validation.setEnabled(not window._learning_job_busy), raising=False)
    window._sync_learning_corpus_controls()
    dialog.view_validation.click()
    assert calls == ["validate", "view"]


def test_reference_reimport_keeps_a_disabled_reference_and_edited_group(qapp, local_learning, notices, monkeypatch):
    window = MainWindow(client=_resolve_client())
    dialog = window._ensure_learning_dialog()
    dialog.approved.setChecked(True)
    monkeypatch.setattr(local_learning, "import_timeline_reference", lambda *args, **kwargs: reference())
    inline(window, monkeypatch)
    window._import_current_learning_reference()
    qapp.processEvents()
    local_learning.update_reference("chapter-a", enabled=False, group_id="My approved group")
    window._import_current_learning_reference()
    qapp.processEvents()
    stored = local_learning.list_references()[0]
    assert stored["enabled"] is False and stored["group_id"] == "My approved group"
    assert _reference_item(window, "chapter-a").checkState(0) == Qt.CheckState.Unchecked


def test_external_profile_inspection_survives_refresh_import_and_group_edits(qapp, local_learning, notices, monkeypatch, tmp_path):
    import vispa_mp.learning_ui as ui
    local_learning.save_reference(reference())
    window = prepared_window(qapp)
    current = train_profile([reference()], name="Keep active")
    window._restore_learning_profile(current)
    before = deepcopy((window.snapshot, window.analysis, window.proposals, window._learning_profile))
    window._refresh_learning_lists()
    external = train_profile([reference()], name="External inspection")
    path = tmp_path / "outside-profile-library.json"
    save_profile(external, path)
    monkeypatch.setattr(ui.QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    window._load_learning_profile_file()
    dialog = window.learning_dialog
    expected_report = dialog.report.toPlainText()
    assert dialog.profiles.currentText() == "External inspection"
    assert window._learning_profile == current

    def assert_inspection_kept():
        assert dialog.profiles.currentData() == str(path.resolve())
        assert dialog.report.toPlainText() == expected_report
        assert (window.snapshot, window.analysis, window.proposals, window._learning_profile) == before

    window._refresh_learning_lists()
    assert_inspection_kept()
    window.client = _resolve_client()
    dialog.approved.setChecked(True)
    monkeypatch.setattr(local_learning, "import_timeline_reference", lambda *args, **kwargs:
                        reference("chapter-new", "New reference"))
    inline(window, monkeypatch)
    window._import_current_learning_reference()
    qapp.processEvents()
    assert_inspection_kept()
    _reference_item(window, "chapter-a").setSelected(True)
    monkeypatch.setattr(ui.QInputDialog, "getText", lambda *args: ("Edited source group", True))
    window._edit_learning_source_group()
    assert_inspection_kept()
    assert not window._project_dirty


def test_reference_refresh_uses_only_validated_explicit_profile_memory(qapp, local_learning, monkeypatch, tmp_path):
    import vispa_mp.learning_ui as ui
    import vispa_mp.learning_model as model
    window = MainWindow()
    window._refresh_learning_lists()
    external = train_profile([reference()], name="Loaded once")
    path = tmp_path / "external.json"
    save_profile(external, path)
    monkeypatch.setattr(ui.QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    window._load_learning_profile_file()
    window._learning_loaded_profiles[str(tmp_path / "invalid.json")] = {"kind": "invalid"}
    monkeypatch.setattr(model, "load_profile", lambda *args:
                        pytest.fail("A reference refresh must not scan or reload external profile files"))
    window._refresh_learning_lists()
    assert window.learning_dialog.profiles.currentText() == "Loaded once"
    assert window.learning_dialog.profiles.count() == 2
    assert window._learning_profile is None

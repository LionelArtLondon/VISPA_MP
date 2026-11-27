"""Explicit profile saving exports a usable model and preserves the working review."""

from copy import deepcopy
from pathlib import Path

import pytest

from tests.test_learning_ui import inline, local_learning, notices, prepared_window, reference
from vispa_mp.learning_model import load_profile, train_profile
from vispa_mp.ui import MainWindow


def trained_window(qapp, local_learning, monkeypatch):
    local_learning.save_reference(reference())
    window = prepared_window(qapp)
    window._refresh_learning_lists()
    window.learning_dialog.profile_name.setText("My illustrated / chapters")
    inline(window, monkeypatch)
    window._train_learning_profile()
    return window


def test_local_saving_is_explicit_and_export_requires_a_trained_profile(qapp, local_learning, notices):
    window = MainWindow()
    window._refresh_learning_lists()
    dialog = window.learning_dialog
    assert dialog.train.text() == "Train and save profile"
    assert not dialog.save_profile_as.isEnabled()
    assert "saved locally after each import" in dialog.report.toPlainText()
    window._save_learning_profile_as()
    assert "Train and save" in notices[0][-1][2]
    local_learning.save_reference(reference())
    window._refresh_learning_lists()
    assert "saved locally" in dialog.corpus_summary.text()
    assert dialog.train.isEnabled() and not dialog.save_profile_as.isEnabled()


def test_save_as_exports_the_inspected_model_without_retraining_or_activation(qapp, local_learning, notices, monkeypatch, tmp_path):
    import vispa_mp.learning_ui as ui
    window = trained_window(qapp, local_learning, monkeypatch)
    dialog = window.learning_dialog
    original_path = Path(dialog.profiles.currentData())
    expected = load_profile(original_path)
    assert dialog.save_profile_as.isEnabled()
    assert "saved locally" in dialog.operation.text()
    assert "Profile saved locally." in dialog.report.toPlainText()
    before = deepcopy((window.snapshot, window.analysis, window.proposals, window._stored_settings,
                       window._learning_profile, window._learning_refs))
    choices = []
    target = tmp_path / "my-profile"
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *args: choices.append(args) or (str(target), ""))
    monkeypatch.setattr("vispa_mp.learning_model.train_profile", lambda *args, **kwargs: pytest.fail("Saving a copy must not retrain"))
    window._save_learning_profile_as()
    assert load_profile(target.with_suffix(".json")) == expected
    assert load_profile(original_path) == expected
    assert Path(choices[0][2]).name == "vispa-profile-My illustrated _ chapters.json"
    assert (window.snapshot, window.analysis, window.proposals, window._stored_settings,
            window._learning_profile, window._learning_refs) == before
    assert not window._project_dirty
    assert "Profile copy saved" in dialog.operation.text()
    assert str(target.with_suffix(".json")) == dialog.operation.toolTip()
    assert notices[0] == []


def test_save_as_can_export_a_profile_embedded_in_a_project(qapp, local_learning, notices, monkeypatch, tmp_path):
    import vispa_mp.learning_ui as ui
    window = prepared_window(qapp)
    model = train_profile([reference()], name="Embedded choices")
    window._restore_learning_profile(model)
    window._refresh_learning_lists()
    assert window.learning_dialog.profiles.currentData() == "embedded"
    target = tmp_path / "embedded.json"
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    monkeypatch.setattr(window, "recompute", lambda: pytest.fail("Saving must not change the preparation"))
    window._save_learning_profile_as()
    assert load_profile(target) == model
    assert window._learning_profile == model and window._learning_profile_path == ""
    assert not window._project_dirty


def test_cancelled_save_keeps_the_existing_local_profile_and_review(qapp, local_learning, notices, monkeypatch):
    import vispa_mp.learning_ui as ui
    window = trained_window(qapp, local_learning, monkeypatch)
    original = Path(window.learning_dialog.profiles.currentData())
    saved = original.read_bytes()
    message = window.learning_dialog.operation.text()
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    window._save_learning_profile_as()
    assert original.read_bytes() == saved
    assert window.learning_dialog.operation.text() == message
    assert window._learning_export_folder is None
    assert not window._project_dirty
    assert notices[0] == []


def test_failed_copy_reports_failure_without_claiming_success_or_losing_original(qapp, local_learning, notices, monkeypatch, tmp_path):
    import vispa_mp.learning_ui as ui
    window = trained_window(qapp, local_learning, monkeypatch)
    original = Path(window.learning_dialog.profiles.currentData())
    saved = original.read_bytes()
    target = tmp_path / "failed.json"
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    monkeypatch.setattr("vispa_mp.learning_model.save_profile", lambda *args: (_ for _ in ()).throw(PermissionError("Read-only folder")))
    window._save_learning_profile_as()
    assert not target.exists() and original.read_bytes() == saved
    assert "could not be saved" in notices[0][-1][2]
    assert window._learning_export_folder is None
    assert window._learning_profile is None and not window._project_dirty


def test_copy_is_disabled_during_jobs_and_when_standard_rules_are_selected(qapp, local_learning, monkeypatch):
    import vispa_mp.learning_ui as ui
    window = trained_window(qapp, local_learning, monkeypatch)
    dialog = window.learning_dialog
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *args: pytest.fail("A busy window must not open Save"))
    window._set_learning_busy(True)
    assert not dialog.save_profile_as.isEnabled()
    window._save_learning_profile_as()
    window._learning_job_finished()
    assert dialog.save_profile_as.isEnabled()
    dialog.profiles.setCurrentIndex(0)
    assert not dialog.save_profile_as.isEnabled()

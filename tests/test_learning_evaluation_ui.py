"""A chapter comparison is inspectable and never changes the working edit."""

from copy import deepcopy

from tests.test_learning_ui import inline, local_learning, notices, prepared_window, reference
from vispa_mp.learning_evaluation_ui import cross_validation_text, validation_report_path
from vispa_mp.ui import MainWindow


def test_corpus_coverage_shows_only_included_examples(qapp, local_learning):
    first = reference()
    second = reference("chapter-b", "Excluded chapter")
    second["enabled"] = False
    local_learning.save_reference(first)
    local_learning.save_reference(second)
    window = MainWindow()
    window._refresh_learning_lists()
    text = window.learning_dialog.corpus_summary.text()
    assert "1/2 references" in text
    assert "1 source chapter group" in text
    assert "Core incl. starts: 1" in text and "Extra: 1" in text
    assert "Extras per Core: 1.00" in text
    assert "Core/page: 1.0" in text and "Extra/page: 1.0" in text
    assert not window.learning_dialog.validate_corpus.isEnabled()
    assert not window.learning_dialog.view_validation.isEnabled()
    assert not validation_report_path().exists()


def test_validation_requires_two_included_source_chapters(qapp, local_learning, notices):
    local_learning.save_reference(reference())
    excluded = reference("chapter-b")
    excluded["enabled"] = False
    local_learning.save_reference(excluded)
    window = MainWindow()
    window._refresh_learning_lists()
    window._validate_learning_corpus()
    assert "at least two" in notices[0][-1][2]
    assert not validation_report_path().exists()


def test_cross_chapter_comparison_is_saved_without_changing_the_live_review(qapp, local_learning, notices, monkeypatch):
    from vispa_mp.learning_model import load_cross_validation_report, train_profile
    local_learning.save_reference(reference())
    local_learning.save_reference(reference("chapter-b", "Second chapter"))
    window = prepared_window(qapp)
    profile = train_profile([reference()], name="Current profile")
    window._restore_learning_profile(profile)
    original = deepcopy((window.snapshot, window.analysis, window.proposals, window._learning_profile, window.settings()))
    inline(window, monkeypatch)
    window._refresh_learning_lists()
    assert window.learning_dialog.validate_corpus.isEnabled()
    window._validate_learning_corpus()
    qapp.processEvents()
    report = load_cross_validation_report(validation_report_path())
    assert report["fold_count"] == 2
    assert (window.snapshot, window.analysis, window.proposals, window._learning_profile, window.settings()) == original
    assert not window._project_dirty
    assert not list(local_learning.PROFILES_DIR.glob("*.json"))
    assert window.learning_dialog.view_validation.isEnabled()
    assert window.learning_validation_dialog.isVisible()
    text = window.learning_validation_dialog.report.toPlainText()
    assert "Second chapter" in text and "equal weight per chapter" in text
    assert "regressed" in text and "without a comparison" in text
    assert "complete page layout" in text
    assert notices[0] == []


def test_saved_comparison_can_be_reopened_after_restart(qapp, local_learning):
    from vispa_mp.learning_model import cross_validate, save_cross_validation_report
    report = cross_validate([reference(), reference("chapter-b", "Second chapter")])
    save_cross_validation_report(report, validation_report_path())
    window = MainWindow()
    window._refresh_learning_lists()
    assert window.learning_dialog.view_validation.isEnabled()
    assert window._learning_profile is None
    window._show_learning_validation_report()
    assert window.learning_validation_dialog.validation_report == report
    assert "Second chapter" in window.learning_validation_dialog.report.toPlainText()
    assert not window._learning_refs


def test_corrupt_saved_comparison_explains_how_to_recover(qapp, local_learning, notices):
    target = validation_report_path()
    target.parent.mkdir(parents=True)
    target.write_text('{"kind": "not-a-comparison"}', encoding="utf-8")
    window = prepared_window(qapp)
    original = deepcopy((window.analysis, window.proposals))
    window._refresh_learning_lists()
    window._show_learning_validation_report()
    assert "Run validation again" in notices[0][-1][2]
    assert (window.analysis, window.proposals) == original
    assert window._learning_profile is None
    assert not getattr(window, "learning_validation_dialog", None)


def test_cancelling_comparison_keeps_the_previous_saved_report(qapp, local_learning, notices, monkeypatch):
    import vispa_mp.learning_model as model
    target = validation_report_path()
    previous = model.cross_validate([reference(), reference("chapter-b")])
    model.save_cross_validation_report(previous, target)
    saved = target.read_bytes()
    local_learning.save_reference(reference())
    local_learning.save_reference(reference("chapter-b"))
    window = prepared_window(qapp)
    window._refresh_learning_lists()
    inline(window, monkeypatch)

    def stopped(*args, **kwargs):
        window._cancel_learning_job()
        return previous

    monkeypatch.setattr(model, "cross_validate", stopped)
    window._validate_learning_corpus()
    assert target.read_bytes() == saved
    assert not window._learning_job_busy
    assert not getattr(window, "learning_validation_dialog", None)
    assert not window._project_dirty
    assert notices[0] == []


def test_comparison_export_remains_a_valid_json_report(qapp, local_learning, monkeypatch, tmp_path):
    import vispa_mp.learning_evaluation_ui as ui
    from vispa_mp.learning_model import cross_validate, load_cross_validation_report, save_cross_validation_report
    report = cross_validate([reference(), reference("chapter-b")])
    save_cross_validation_report(report, validation_report_path())
    window = MainWindow()
    window._refresh_learning_lists()
    window._show_learning_validation_report()
    target = tmp_path / "comparison"
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    window.learning_validation_dialog._save_report()
    assert load_cross_validation_report(target.with_suffix(".json")) == report


def test_comparison_report_explains_missing_extra_training_in_a_fold():
    from vispa_mp.learning_model import cross_validate
    first = reference()
    for sample in first["samples"]:
        if sample["roles"] == ["extra"]:
            sample["roles"] = []
    report = cross_validate([first, reference("chapter-b", "Only Extra chapter")])
    text = cross_validation_text(report)
    assert "No usable training comparisons in the other chapters." in text
    assert "no_training_pairs" not in text
    assert "fixed visual weights" in text
    assert "Train and activate a profile separately" in text


def test_comparison_completion_waits_for_worker_release(qapp, local_learning, notices, monkeypatch):
    local_learning.save_reference(reference())
    local_learning.save_reference(reference("chapter-b"))
    window = MainWindow()
    window._refresh_learning_lists()
    deferred = []
    monkeypatch.setattr(window, "_when_learning_idle", lambda callback: deferred.append(callback))
    inline(window, monkeypatch)
    window._validate_learning_corpus()
    assert validation_report_path().exists()
    assert not getattr(window, "learning_validation_dialog", None)
    assert len(deferred) == 1
    deferred[0]()
    assert window.learning_validation_dialog.isVisible()


def test_real_validation_worker_releases_controls_before_showing_report(qapp, local_learning, notices):
    from time import monotonic
    from PySide6.QtTest import QTest
    local_learning.save_reference(reference())
    local_learning.save_reference(reference("chapter-b"))
    window = prepared_window(qapp)
    window._refresh_learning_lists()
    window._validate_learning_corpus()
    assert window.worker is not None
    assert not window.learning_dialog.train.isEnabled()
    limit = monotonic() + 10
    while monotonic() < limit and (window.worker is not None or not getattr(window, "learning_validation_dialog", None)):
        QTest.qWait(10)
    # Always stop a failed worker before pytest releases the parent QWidget.
    if window.worker is not None:
        window._cancel_learning_job()
        window.worker.wait(10_000)
        qapp.processEvents()
    assert window.worker is None
    assert not window._learning_job_busy
    assert window.learning_validation_dialog.isVisible()
    assert window.learning_dialog.train.isEnabled()
    assert window.learning_dialog.validate_corpus.isEnabled()
    assert window.learning_dialog.view_validation.isEnabled()
    assert not window._project_dirty
    assert notices[0] == []

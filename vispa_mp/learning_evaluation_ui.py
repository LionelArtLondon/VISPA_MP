"""Inspect corpus coverage and compare local preferences across whole chapters."""

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from vispa_mp.window_chrome import ChromeDialog


def validation_report_path():
    # Keep reports beside the local references, including in isolated test libraries.
    from vispa_mp.learning_data import REFERENCES_DIR
    return Path(REFERENCES_DIR).parent / "validation" / "last.json"


def _chapter_name(report, group):
    from vispa_mp.learning_ui import _chapter_label
    return _chapter_label((report.get("group_names") or {}).get(group, []))


def cross_validation_text(report):
    """Label weak ranking scores and their coverage, without claiming editorial accuracy."""
    lines = ["Cross-chapter validation",
             f"{report['reference_count']} references · {report['sample_count']} examined images",
             "Each source chapter group was kept out in turn. Each comparison uses a fresh model trained on the other groups.",
             "", "Mean agreement across comparable held-out chapters (equal weight per chapter):"]
    roles = (("core", "Core"), ("extra", "Extra"), ("page", "Page start"))
    for role, label in roles:
        metrics = report["roles"][role]
        base, personal = metrics.get("baseline_accuracy"), metrics.get("personal_accuracy")
        if base is None or personal is None:
            lines.append(f"{label}: no independent comparison available (0/{metrics['groups_total']} chapter groups).")
        else:
            delta = (personal - base) * 100
            lines.append(f"{label}: visual baseline {base:.1%}, personal {personal:.1%} "
                         f"({delta:+.1f} percentage points); {metrics['groups_evaluated']} chapter group(s), "
                         f"{metrics['validation_pairs']} comparisons.")
            lines.append(f"  Chapters: {metrics['groups_improved']} improved, {metrics['groups_regressed']} regressed, "
                         f"{metrics['groups_unchanged']} unchanged, {metrics['groups_skipped']} without a comparison.")
    lines.extend(["", "By held-out source chapter:"])
    for fold in report["folds"]:
        lines.append(_chapter_name(report, fold["heldout_group"]))
        for role, label in roles:
            metrics = fold["roles"][role]
            base, personal = metrics.get("baseline_accuracy"), metrics.get("personal_accuracy")
            if base is None or personal is None:
                reason = {"no_training_pairs": "No usable training comparisons in the other chapters.",
                          "no_validation_pairs": "No usable validation comparisons in this chapter."}.get(
                              metrics.get("reason"), "No usable training or validation comparisons.")
                lines.append(f"  {label}: {reason}")
            else:
                lines.append(f"  {label}: visual baseline {base:.1%}, personal {personal:.1%} "
                             f"({metrics['validation_pairs']} comparisons).")
    lines.extend(["", "Unmarked images are weak alternatives, not confirmed mistakes.",
                  "These scores compare candidate preferences with fixed visual weights. They do not measure the quality of a complete page layout.",
                  "This comparison saves a report. Train and activate a profile separately after reviewing it."])
    lines.extend(str(warning) for warning in report.get("warnings") or [])
    return "\n".join(lines)


class ValidationReportDialog(ChromeDialog):
    def __init__(self, owner, report):
        super().__init__(owner.learning_dialog or owner, "Cross-chapter validation")
        self.owner = owner
        self.validation_report = deepcopy(report)
        self.resize(830, 680)
        self.setStyleSheet(owner.styleSheet())
        column = QVBoxLayout(self.body)
        column.setContentsMargins(20, 16, 20, 16)
        intro = QLabel("Saved comparison for the chapters listed below. Run validation again after changing references or their groups.")
        intro.setWordWrap(True)
        column.addWidget(intro)
        self.report = QPlainTextEdit(cross_validation_text(report))
        self.report.setReadOnly(True)
        column.addWidget(self.report, 1)
        row = QHBoxLayout()
        self.export = QPushButton("Save report as…")
        self.export.clicked.connect(self._save_report)
        row.addWidget(self.export)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        column.addLayout(row)

    def _save_report(self):
        path, _filter = QFileDialog.getSaveFileName(self, "Save chapter comparison", "chapter-validation.json",
                                                  "VISPA MP validation report (*.json)")
        if not path:
            return
        if not Path(path).suffix:
            path += ".json"
        try:
            from vispa_mp.learning_model import save_cross_validation_report
            save_cross_validation_report(self.validation_report, path)
        except (OSError, ValueError) as error:
            self.owner._learning_error("The validation report could not be saved.", error)


class LearningEvaluationMixin:
    def _update_learning_corpus_summary(self):
        if self.learning_dialog is None:
            return
        from vispa_mp.learning_data import corpus_summary
        # Selecting rows only changes the group-edit button. Reuse the coverage
        # calculation until imports or persisted corpus metadata reload the list.
        key = tuple((id(ref), ref.get("enabled", True), ref.get("group_id")) for ref in self._learning_refs)
        cached = getattr(self, "_learning_corpus_summary_cache", None)
        if cached is None or cached[0] != key:
            cached = (key, corpus_summary(self._learning_refs))
            self._learning_corpus_summary_cache = cached
        summary = cached[1]
        lines = [f"Included: {summary['active_references']}/{summary['references']} references · "
                 f"{summary['groups']} source chapter group(s) · saved locally",
                 f"Page starts: {summary['page']} · Core incl. starts: {summary['core']} · Extra: {summary['extra']}"]
        ratio = summary.get("extra_core_ratio")
        if ratio is not None:
            lines.append(f"Extras per Core: {ratio:.2f}")
        if summary["observed_pages"]:
            lines.append(f"Observed marked pages: {summary['observed_pages']} · Core/page: {summary['core_per_page']['mean']:.1f} · "
                         f"Extra/page: {summary['extra_per_page']['mean']:.1f}")
        warnings = summary.get("warnings") or []
        lines.extend(warnings[:2])
        self.learning_dialog.corpus_summary.setText("\n".join(lines))
        explanation = "Page counts use chronological marker choices from the first page start onward; a final page may be partial. They describe the references and do not change selection settings."
        self.learning_dialog.corpus_summary.setToolTip("\n".join([explanation, *warnings]))
        available = getattr(self, "_learning_validation_report", None) is not None or validation_report_path().is_file()
        self.learning_dialog.view_validation.setEnabled(available and not self._learning_job_busy and self.worker is None)

    def _validate_learning_corpus(self):
        if self.worker is not None or self._learning_job_busy:
            return
        self._ensure_learning_dialog()
        references = deepcopy([ref for ref in self._learning_refs if ref.get("enabled", True)])
        if len({ref["group_id"] for ref in references}) < 2:
            self._learning_error("Include at least two different source chapter groups before cross-chapter validation.")
            return

        def work(progress, cancel):
            from vispa_mp.learning_model import cross_validate, save_cross_validation_report
            report = cross_validate(references, progress=progress, cancel=cancel)
            if cancel():
                raise InterruptedError("Chapter validation was stopped.")
            save_cross_validation_report(report, validation_report_path())
            return report

        def done(report):
            self._learning_validation_report = report
            self._update_learning_corpus_summary()
            self.learning_dialog.operation.setText("Chapter comparison saved. Review its coverage before training a profile.")
            self.status.setText("Cross-chapter validation completed; the current review and active profile were kept.")
            # Worker.done precedes Worker.finished; show once MainWindow releases it.
            self._when_learning_idle(self._show_learning_validation_report)

        self._run_learning_job("Comparing preferences across source chapters…", work, done)

    def _show_learning_validation_report(self):
        if self.worker is not None or self._learning_job_busy:
            return
        try:
            from vispa_mp.learning_model import load_cross_validation_report, validate_cross_validation_report
            report = getattr(self, "_learning_validation_report", None)
            report = (validate_cross_validation_report(report) if report is not None
                      else load_cross_validation_report(validation_report_path()))
        except (OSError, ValueError) as error:
            self._learning_error("The saved chapter comparison could not be opened. Run validation again to create a new report.", error)
            return
        self._learning_validation_report = report
        old_dialog = getattr(self, "learning_validation_dialog", None)
        if old_dialog is not None:
            old_dialog.close()
            old_dialog.deleteLater()
        self.learning_validation_dialog = ValidationReportDialog(self, report)
        self.learning_validation_dialog.show()
        self.learning_validation_dialog.raise_()
        self.learning_validation_dialog.activateWindow()

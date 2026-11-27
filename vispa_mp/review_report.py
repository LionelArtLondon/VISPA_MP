"""Keep analysis diagnostics available without taking space from the review."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from vispa_mp.window_chrome import ChromeDialog


class ReviewReportMixin:
    def _build_report_button(self):
        self.review_report_button = QPushButton("Analysis details")
        self.review_report_button.setObjectName("analysisDetailsButton")
        self.review_report_button.setAccessibleName("Analysis details")
        self.review_report_button.setProperty("hasWarnings", False)
        self.review_report_button.setProperty("warningCount", 0)
        self.review_report_button.setToolTip("View marker totals and the complete analysis warnings.")
        self.review_report_button.clicked.connect(self._show_review_report)
        return self.review_report_button

    def _init_review_report(self):
        if getattr(self, "review_report_dialog", None) is not None:
            self._sync_review_report()
            return
        dialog = self.review_report_dialog = ChromeDialog(self, "Analysis details")
        dialog.setModal(False)
        dialog.finished.connect(self._sync_review_report)
        dialog.resize(760, 520)
        dialog.setMinimumSize(420, 260)
        outer = QVBoxLayout(dialog.body)
        outer.setContentsMargins(12, 12, 12, 12)
        self.review_report_source = QLabel()
        self.review_report_source.setWordWrap(True)
        self.review_report_source.setTextFormat(Qt.TextFormat.PlainText)
        self.review_report_source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.review_report_source)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(4, 4, 12, 4)
        column.setSpacing(12)
        for title, label in (("Global markers", self.marker_budget_summary), ("Warnings", self.warnings)):
            heading = QLabel(title)
            heading.setProperty("role", "section")
            column.addWidget(heading)
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                          Qt.TextInteractionFlag.TextSelectableByKeyboard)
            label.setContentsMargins(0, 0, 0, 0)
            column.addWidget(label)
        self.review_report_warning_heading = QLabel("Full warning details")
        self.review_report_warning_heading.setProperty("role", "muted")
        column.addWidget(self.review_report_warning_heading)
        self.review_report_warning_details = QLabel()
        self.review_report_warning_details.setWordWrap(True)
        self.review_report_warning_details.setTextFormat(Qt.TextFormat.PlainText)
        self.review_report_warning_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                                                  Qt.TextInteractionFlag.TextSelectableByKeyboard)
        column.addWidget(self.review_report_warning_details)
        self.review_report_empty = QLabel("No analysis warnings.")
        self.review_report_empty.setProperty("role", "muted")
        column.addWidget(self.review_report_empty)
        column.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        close = QPushButton("Close")
        close.clicked.connect(dialog.close)
        outer.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self._sync_review_report()

    def _review_report_lines(self):
        provider = getattr(self, "_warning_lines", None)
        lines = list(provider()) if callable(provider) else self.warnings.text().splitlines()
        lines.extend(getattr(self, "marker_budget_review_warnings", []))
        if hasattr(self, "marker_budget_summary"):
            lines.extend(self.marker_budget_summary.toolTip().splitlines())
        return list(dict.fromkeys(str(line) for line in lines if line))

    def _sync_review_report(self):
        button = getattr(self, "review_report_button", None)
        if button is None:
            return
        lines = self._review_report_lines()
        count = len(lines)
        button.setText(f"Analysis details ({count})" if count else "Analysis details")
        changed = button.property("hasWarnings") != bool(count)
        button.setProperty("hasWarnings", bool(count))
        button.setProperty("warningCount", count)
        if changed:
            button.style().unpolish(button)
            button.style().polish(button)
        budget = getattr(self, "marker_budget_summary", None)
        summary = budget.text().splitlines()[0] if budget is not None and budget.text() else ""
        detail = f"{count} warning{'s' if count != 1 else ''}. Open the full analysis report." if count else "No analysis warnings."
        button.setToolTip("\n".join(part for part in (summary, detail) if part))
        dialog = getattr(self, "review_report_dialog", None)
        if dialog is None:
            return
        source = getattr(self, "analysis", None) or getattr(self, "snapshot", None) or {}
        self.review_report_source.setText(" · ".join(str(source[key]) for key in
                                                   ("project_name", "timeline_name") if source.get(key)))
        self.review_report_source.setVisible(bool(self.review_report_source.text()))
        # Keep the original folded warning label and its tooltip unchanged.
        # When that summary omits per-page details, make the raw report visible.
        raw = "\n".join(lines)
        self.review_report_warning_details.setText(raw)
        self.review_report_warning_details.setToolTip(raw)
        expanded = bool(raw) and raw != self.warnings.text()
        self.review_report_warning_heading.setVisible(expanded)
        self.review_report_warning_details.setVisible(expanded)
        self.warnings.setVisible(dialog.isVisible() and bool(self.warnings.text()))
        self.marker_budget_summary.setVisible(dialog.isVisible() and bool(self.marker_budget_summary.text()))
        self.review_report_empty.setVisible(not lines)

    def _show_review_report(self):
        if getattr(self, "review_report_dialog", None) is None:
            self._init_review_report()
        self._sync_review_report()
        self.review_report_dialog.show()
        self._sync_review_report()
        self.review_report_dialog.raise_()
        self.review_report_dialog.activateWindow()

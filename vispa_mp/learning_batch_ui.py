"""Select existing Resolve projects and import their matching learning timeline."""

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFormLayout, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QProgressBar, QPushButton, QSizeGrip, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from vispa_mp.client import open_client
from vispa_mp.ui_tokens import BORDER_ROW, SELECTED_ROW, TEXT_MAIN, px
from vispa_mp.window_chrome import ChromeDialog


class LearningProjectTable(QTreeWidget):
    """Space includes the current project, even when its name column has focus."""

    def keyPressEvent(self, event):
        item = self.currentItem()
        if event.key() == Qt.Key.Key_Space and event.modifiers() == Qt.KeyboardModifier.NoModifier and item is not None:
            state = Qt.CheckState.Unchecked if item.checkState(0) == Qt.CheckState.Checked else Qt.CheckState.Checked
            item.setCheckState(0, state)
            event.accept()
            return
        super().keyPressEvent(event)


class LearningBatchDialog(ChromeDialog):
    def __init__(self, owner):
        super().__init__(owner.learning_dialog or owner, "Import Resolve projects in a batch")
        self.owner = owner
        self.entries = []
        self._job_entries = []
        self.resize(900, 720)
        self.setMinimumSize(700, 560)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(owner.styleSheet())
        column = QVBoxLayout(self.body)
        column.setContentsMargins(20, 16, 20, 16)
        intro = QLabel("Select saved projects from the connected Resolve library. MP opens them one at a time and reads their markers. Save current Resolve work before starting; the projects and markers are not edited.")
        intro.setWordWrap(True)
        column.addWidget(intro)
        form = QFormLayout()
        self.timeline_name = QLineEdit("Personal Learning")
        self.timeline_name.setToolTip("Exact timeline name used in every selected project. Leave empty only when each project has a single timeline.")
        form.addRow("Timeline in every project", self.timeline_name)
        column.addLayout(form)
        self.in_out = QCheckBox("Use each timeline's In/Out range")
        self.in_out.setChecked(True)
        self.in_out.setToolTip("Both In and Out must already be set on each selected learning timeline; missing or invalid ranges are reported.")
        column.addWidget(self.in_out)
        self.approved = QCheckBox("The selected chapters' marker choices have been reviewed and approved")
        self.approved.setChecked(owner.learning_dialog.approved.isChecked())
        self.approved.toggled.connect(owner._sync_learning_batch_controls)
        column.addWidget(self.approved)
        self.include_automatic = QCheckBox("Also include reviewed markers created by MP")
        self.include_automatic.setChecked(owner.learning_dialog.include_automatic.isChecked())
        column.addWidget(self.include_automatic)
        self.library = QLabel("Connected library: not read yet")
        self.library.setWordWrap(True)
        column.addWidget(self.library)
        self.projects = LearningProjectTable()
        self.projects.setObjectName("learningProjectTable")
        self.projects.setHeaderLabels(["", "Resolve project", "Library folder", "Status"])
        self.projects.setRootIsDecorated(False)
        self.projects.setUniformRowHeights(True)
        self.projects.setAlternatingRowColors(True)
        self.projects.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.projects.setStyleSheet(f"""
            QTreeWidget#learningProjectTable::item {{ min-height: {px(26)}px;
                padding: {px(3)}px {px(10)}px; border-bottom: 1px solid {BORDER_ROW}; }}
            QTreeWidget#learningProjectTable::item:selected {{ background: {SELECTED_ROW}; color: {TEXT_MAIN}; }}
        """)
        header = self.projects.header()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, px(40))
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(2, px(190))
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(3, px(144))
        self.projects.headerItem().setToolTip(0, "Choose the projects to import")
        self.projects.itemChanged.connect(owner._sync_learning_batch_controls)
        column.addWidget(self.projects, 1)
        row = QHBoxLayout()
        self.refresh = QPushButton("Refresh project library")
        self.refresh.clicked.connect(owner._load_learning_batch_library)
        self.start = QPushButton("Import selected projects")
        self.start.clicked.connect(owner._start_learning_batch)
        self.cancel = QPushButton("Cancel operation")
        self.cancel.clicked.connect(owner._cancel_learning_job)
        self.cancel.setEnabled(False)
        row.addWidget(self.refresh)
        row.addWidget(self.start)
        row.addStretch(1)
        row.addWidget(self.cancel)
        column.addLayout(row)
        self.status = QLabel("Refresh the library, then check the projects to import.")
        self.status.setWordWrap(True)
        column.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.hide()
        column.addWidget(self.progress)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(150)
        column.addWidget(self.report)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        column.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        grip = self.findChild(QSizeGrip)
        if grip is not None:
            grip.setToolTip("Drag this corner to resize the window and show more projects")
            grip.setAccessibleName("Resize import window")

    def closeEvent(self, event):
        if self.owner._learning_job_busy:
            self.owner._cancel_learning_job()
            event.ignore()
            return
        super().closeEvent(event)


class LearningBatchMixin:
    def _show_learning_batch(self):
        if self.worker is not None or self._learning_job_busy:
            return
        self._ensure_learning_dialog()
        if getattr(self, "learning_batch_dialog", None) is None:
            self.learning_batch_dialog = LearningBatchDialog(self)
        dialog = self.learning_batch_dialog
        self._sync_learning_batch_controls()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        if not dialog.entries:
            self._load_learning_batch_library()

    def _sync_learning_batch_controls(self, *_args):
        dialog = getattr(self, "learning_batch_dialog", None)
        if dialog is None:
            return
        idle = self.worker is None and not self._learning_job_busy
        for control in (dialog.refresh, dialog.projects, dialog.timeline_name, dialog.in_out, dialog.approved, dialog.include_automatic):
            control.setEnabled(idle)
        selected = any(dialog.projects.topLevelItem(index).checkState(0) == Qt.CheckState.Checked
                       for index in range(dialog.projects.topLevelItemCount()))
        dialog.start.setEnabled(idle and selected and dialog.approved.isChecked())
        dialog.cancel.setEnabled(self._learning_job_busy and (self._learning_stop is None or not self._learning_stop.is_set()))
        dialog.progress.setVisible(self._learning_job_busy)

    def _load_learning_batch_library(self):
        if self.worker is not None or self._learning_job_busy:
            return
        dialog = self.learning_batch_dialog
        # A failed refresh must not leave a previously checked project list
        # available for import from a different or unverified connection.
        dialog.entries = []
        dialog._job_entries = []
        dialog.projects.clear()
        dialog.report.clear()
        dialog.library.setText("Connected library: checking Resolve…")
        self._sync_learning_batch_controls()

        def work(_progress, cancel):
            client = None
            try:
                client = self.client or open_client()
                result = client.request("learning_library")
                if cancel():
                    return {"cancelled": True}
                return {"result": result}
            except (OSError, ValueError, RuntimeError) as error:
                if cancel():
                    return {"cancelled": True}
                if "Unknown command" in str(error):
                    return {"error": "Run Workspace > Scripts > VISPA_MP again in Resolve to enable batch imports, then refresh the library."}
                return {"error": str(error)}
            finally:
                if client is not None and self.client is None:
                    client.close()

        def done(outcome):
            if outcome.get("cancelled"):
                self._learning_batch_scan_failed("Library scan cancelled. Refresh the library to try again.", cancelled=True)
                return
            if "error" in outcome:
                self._learning_batch_scan_failed(outcome["error"])
                return
            result = outcome.get("result")
            entries = result.get("projects") if isinstance(result, dict) else None
            if (not isinstance(entries, list) or any(not isinstance(entry, dict) or not isinstance(entry.get("name"), str)
                                                   or not isinstance(entry.get("folder"), list)
                                                   or any(not isinstance(part, str) for part in entry["folder"]) for entry in entries)):
                self._learning_batch_scan_failed("The Resolve project list could not be read.")
                return
            database = result.get("database") or (entries[0].get("database") if entries else None)
            if not isinstance(database, dict) or not isinstance(database.get("DbName"), str) or not database["DbName"]:
                self._learning_batch_scan_failed("Resolve did not identify the connected project library. Refresh after opening the intended library in Project Manager.")
                return
            kind = database.get("DbType") or "type unavailable"
            dialog.library.setText(f"Connected library: {database['DbName']} ({kind})")
            dialog.entries = entries
            blocked = dialog.projects.blockSignals(True)
            dialog.projects.clear()
            try:
                for index, entry in enumerate(entries):
                    folder = " / ".join(entry["folder"]) or "Library root"
                    item = QTreeWidgetItem(["", entry["name"], folder, "Not started"])
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                    item.setData(0, Qt.ItemDataRole.UserRole, index)
                    item.setData(0, Qt.ItemDataRole.AccessibleTextRole, "Include " + entry["name"])
                    item.setToolTip(0, "Include this project in the import")
                    item.setToolTip(1, entry["name"])
                    item.setToolTip(2, folder)
                    item.setTextAlignment(2, Qt.AlignmentFlag.AlignCenter)
                    item.setTextAlignment(3, Qt.AlignmentFlag.AlignCenter)
                    dialog.projects.addTopLevelItem(item)
            finally:
                dialog.projects.blockSignals(blocked)
            if entries:
                dialog.status.setText(f"{len(entries)} saved project(s) found. Check only the chapters to import.")
            else:
                dialog.status.setText("Library read successfully: no saved projects found in this connected library.")
                dialog.report.setPlainText(
                    "In Resolve, open Project Manager with the Home button and check the project library selected in its left sidebar. "
                    "Open the library containing your chapters, then refresh here. A .drp file must first be imported into that library with Import Project; "
                    "the recent-project list and a folder of .drp exports are not the library scanned by MP.")
            self.learning_dialog.operation.setText(dialog.status.text())
            self.status.setText(dialog.status.text())
            self._sync_learning_batch_controls()

        self._run_learning_job("Reading Resolve project library…", work, done)

    def _learning_batch_scan_failed(self, detail, *, cancelled=False):
        dialog = self.learning_batch_dialog
        dialog.entries = []
        dialog._job_entries = []
        dialog.projects.clear()
        dialog.library.setText("Connected library: not verified")
        text = "Library scan cancelled." if cancelled else "Could not read the Resolve project library. The library has not been confirmed empty."
        dialog.status.setText(text)
        dialog.report.setPlainText(str(detail) + "\n\nOpen Resolve's Project Manager, check the intended project library, then refresh. No references were imported by this scan.")
        self.learning_dialog.operation.setText(text)
        self.status.setText(text)
        self._sync_learning_batch_controls()
        if not cancelled:
            self._learning_error("The Resolve project library could not be read.", detail)

    def _start_learning_batch(self):
        if self.worker is not None or self._learning_job_busy:
            return
        dialog = self.learning_batch_dialog
        if not dialog.approved.isChecked():
            return
        selected = [dialog.projects.topLevelItem(index) for index in range(dialog.projects.topLevelItemCount())
                    if dialog.projects.topLevelItem(index).checkState(0) == Qt.CheckState.Checked]
        entries = [deepcopy(dialog.entries[item.data(0, Qt.ItemDataRole.UserRole)]) for item in selected]
        if not entries:
            return
        dialog._job_entries = selected
        name = dialog.timeline_name.text().strip()
        use_in_out, automatic = dialog.in_out.isChecked(), dialog.include_automatic.isChecked()
        settings = deepcopy(self.settings())
        dialog.report.clear()

        def work(progress, cancel):
            from vispa_mp.learning_batch import import_project_batch
            client = self.client or open_client()
            timeout = getattr(client, "timeout", None)
            if timeout is not None:
                client.timeout = max(120, timeout)
            try:
                return import_project_batch(client, entries, settings, self._cache_dir(), timeline_name=name,
                                            use_in_out=use_in_out, include_automatic=automatic,
                                            progress=progress, cancel=cancel)
            finally:
                if timeout is not None:
                    client.timeout = timeout
                if self.client is None:
                    client.close()

        def done(result):
            self._refresh_learning_lists()
            lines = [f"{item['name']}: {item['status']} · {item['detail']}" for item in result["outcomes"]]
            if result["stopped_error"]:
                lines.append("Batch stopped: " + result["stopped_error"])
            if result["cancelled"]:
                lines.append("Batch cancelled. Completed references remain saved.")
            dialog.report.setPlainText("\n".join(lines))
            dialog.status.setText(f"{result['saved']}/{result['requested']} references saved locally. The current MP review was kept; Resolve remains on the last opened project.")
            self.learning_dialog.operation.setText(dialog.status.text())
            self.status.setText(dialog.status.text())
            self._sync_learning_batch_controls()

        self._run_learning_job("Importing the selected Resolve projects…", work, done)

    def _update_learning_batch_progress(self, value):
        dialog = getattr(self, "learning_batch_dialog", None)
        if dialog is None:
            return
        if self.learning_dialog is not None:
            source = self.learning_dialog.progress
            dialog.progress.setRange(source.minimum(), source.maximum())
            dialog.progress.setValue(source.value())
        if not isinstance(value, dict) or "batch_row" not in value:
            return
        index = value["batch_row"]
        if type(index) is int and 0 <= index < len(dialog._job_entries):
            item = dialog._job_entries[index]
            item.setText(3, str(value.get("batch_state") or "Importing"))
            item.setToolTip(3, str(value.get("detail") or ""))
            dialog.status.setText(str(value.get("label") or "") + " · " + str(value.get("detail") or ""))

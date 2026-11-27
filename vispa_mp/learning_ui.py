"""Collect approved chapter references and explicitly activate a local profile."""

from copy import deepcopy
from pathlib import Path
import threading
import uuid
import math
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem,
    QStyle, QVBoxLayout,
)

from vispa_mp.client import open_client
from vispa_mp.project import FILE_FILTER, load_project
from vispa_mp.snapshot import normalize
from vispa_mp.window_chrome import ChromeDialog


def _counts(reference):
    summary = reference.get("summary") or {}
    return {role: int(summary.get(role, sum(role in sample.get("roles", [])
                                          for sample in reference.get("samples", []))))
            for role in ("page", "core", "extra")}


def _chapter_label(names, fallback="Source chapter"):
    names = [names] if isinstance(names, str) else names
    names = names if isinstance(names, (list, tuple, set)) else []
    names = sorted({name.strip() for name in names if isinstance(name, str) and name.strip()})
    if not names:
        return fallback
    return names[0] if len(names) == 1 else f"{names[0]} (+{len(names) - 1} version(s))"


def _source_group_label(group, names):
    opaque = (group.startswith("media-") or re.fullmatch(r"[0-9a-fA-F-]{24,}", group))
    return _chapter_label(names) if opaque else group


def profile_report(profile):
    """Describe measured preference agreement without presenting it as accuracy of art."""
    report = profile.get("report") or {}
    lines = [profile.get("name") or "Personal profile",
             f"{report.get('reference_count', 0)} references · {report.get('sample_count', 0)} examined images"]
    training = report.get("train_groups") or []
    validation = report.get("validation_groups") or []
    lines.append(f"Training: {len(training)} source chapter group(s).")
    if report.get("validation_unavailable", not validation) or not validation:
        lines.append("Not independently validated: add another source chapter group for a held-out comparison.")
    else:
        group_names = report.get("group_names")
        group_names = group_names if isinstance(group_names, dict) else {}
        labels = [_chapter_label(group_names.get(group, []), f"Source chapter {index + 1}")
                  for index, group in enumerate(validation)]
        lines.append("Validation source chapter group(s), excluded from training: " + ", ".join(labels))
        if not any((entry or {}).get("validation_pairs") and (entry or {}).get("personal_accuracy") is not None
                   for entry in (report.get("roles") or {}).values()):
            lines.append("The held-out chapter has no usable independent ranking comparisons for this profile.")
    for role, label in (("core", "Core"), ("extra", "Extra"), ("page", "Page start")):
        metrics = (report.get("roles") or {}).get(role) or {}
        if not metrics.get("trained"):
            lines.append(f"{label}: insufficient preference pairs; standard selection remains available.")
            continue
        base, personal = metrics.get("baseline_accuracy"), metrics.get("personal_accuracy")
        pairs = metrics.get("validation_pairs", 0)
        if base is not None and personal is not None and pairs:
            lines.append(f"{label}: held-out preference agreement, visual baseline {base:.1%}, personal {personal:.1%} ({pairs} comparisons).")
        else:
            lines.append(f"{label}: trained on {metrics.get('train_pairs', 0)} preference comparisons; no independent score yet.")
    assignment = profile.get("role_assignment")
    if assignment:
        assignment_report = assignment.get("report") or {}
        counts = assignment_report.get("train_counts") or {}
        lines.append(f"Core/Extra assignment: learned from {counts.get('core', 0)} approved Core images "
                     f"and {counts.get('extra', 0)} approved Extras; unmarked images are excluded.")
        score = assignment_report.get("validation_balanced_accuracy")
        if score is None:
            lines.append("Core/Extra assignment has no independent score yet: a held-out chapter needs both roles.")
        else:
            lines.append(f"Core/Extra assignment: held-out balanced agreement {score:.1%} "
                         "(equal weight for Core and Extra).")
        lines.append("Role preferences guide intermediate movement images; page starts, dialogue and manual choices remain protected.")
    else:
        lines.append("Core/Extra assignment: standard contextual rules; this profile has no learned role model.")
    lines.append("Unmarked images are weak alternatives, not confirmed mistakes. This comparison does not guarantee a better edit.")
    lines.append("These scores cover candidate choices, not the accuracy of a complete page layout.")
    lines.extend(str(warning) for warning in report.get("warnings") or [])
    return "\n".join(lines)


class LearningDialog(ChromeDialog):
    def __init__(self, owner):
        super().__init__(owner, "Personal learning")
        self.owner = owner
        self.resize(800, 760)
        self.setStyleSheet(owner.styleSheet())
        column = QVBoxLayout(self.body)
        column.setContentsMargins(20, 16, 20, 16)
        intro = QLabel("Import chapters whose marker choices you have approved. Learning stays on this computer and never places or changes Resolve markers.")
        intro.setWordWrap(True)
        column.addWidget(intro)
        form = QFormLayout()
        self.reference_name = QLineEdit()
        self.reference_name.setPlaceholderText("Use the chapter or timeline name")
        self.reference_group = QLineEdit()
        self.reference_group.setPlaceholderText("Automatic grouping by source video")
        self.reference_group.setToolTip("Keep all versions of the same source chapter in the same group, so they cannot appear in both training and validation.")
        form.addRow("Reference name", self.reference_name)
        form.addRow("Source chapter group", self.reference_group)
        column.addLayout(form)
        self.approved = QCheckBox("These marker choices have been reviewed and approved as references")
        self.include_automatic = QCheckBox("Also include reviewed markers created by MP")
        self.include_automatic.setToolTip("Leave this off for chapters marked by hand. Enable it only after checking the automatic markers yourself.")
        self.reference_in_out = QCheckBox("Import only Resolve In/Out range")
        self.reference_in_out.setToolTip("For Resolve imports: set both In and Out on the timeline to exclude intros or credits. Only markers and image examples inside that range are imported.")
        column.addWidget(self.approved)
        column.addWidget(self.include_automatic)
        column.addWidget(self.reference_in_out)
        imports = QHBoxLayout()
        self.import_resolve = QPushButton("Import current Resolve timeline")
        self.import_project = QPushButton("Import reviewed .vispamp…")
        self.import_resolve.clicked.connect(owner._import_current_learning_reference)
        self.import_project.clicked.connect(owner._import_learning_project)
        imports.addWidget(self.import_resolve)
        imports.addWidget(self.import_project)
        column.addLayout(imports)
        self.import_batch = QPushButton("Batch import Resolve projects…")
        self.import_batch.clicked.connect(owner._show_learning_batch)
        column.addWidget(self.import_batch)
        self.references = QTreeWidget()
        self.references.setHeaderLabels(["Chapter", "Source group", "Page starts", "Core incl. starts", "Extra"])
        self.references.setRootIsDecorated(False)
        self.references.setAlternatingRowColors(True)
        self.references.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.references.setMinimumHeight(100)
        self.references.itemChanged.connect(owner._learning_reference_toggled)
        self.references.itemSelectionChanged.connect(owner._learning_reference_selection_changed)
        self.references.itemDoubleClicked.connect(owner._inspect_learning_reference)
        column.addWidget(self.references, 1)
        self.corpus_summary = QLabel("")
        self.corpus_summary.setWordWrap(True)
        column.addWidget(self.corpus_summary)
        groups = QHBoxLayout()
        self.inspect_reference = QPushButton("Inspect reference…")
        self.inspect_reference.setToolTip("Check imported marker images and their roles without changing the current review.")
        self.inspect_reference.clicked.connect(lambda: owner._inspect_learning_reference())
        self.inspect_reference.setEnabled(False)
        groups.addWidget(self.inspect_reference)
        self.edit_source_group = QPushButton("Edit source group…")
        self.edit_source_group.setToolTip("Assign the same source group to all versions of one chapter. Existing profiles and the current review stay unchanged.")
        self.edit_source_group.clicked.connect(owner._edit_learning_source_group)
        self.edit_source_group.setEnabled(False)
        groups.addWidget(self.edit_source_group)
        self.remove_reference = QPushButton("Remove reference…")
        self.remove_reference.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.remove_reference.setToolTip("Remove selected references from the learning library. Resolve projects and markers stay untouched.")
        self.remove_reference.clicked.connect(owner._remove_learning_references)
        self.remove_reference.setEnabled(False)
        groups.addWidget(self.remove_reference)
        groups.addStretch(1)
        column.addLayout(groups)
        training = QFormLayout()
        self.profile_name = QLineEdit("My selection")
        self.validation = QComboBox()
        self.validation.setToolTip("A different source chapter group is kept out of training when available. One group can train a profile, but cannot provide independent validation.")
        training.addRow("Profile name", self.profile_name)
        training.addRow("Validation source group", self.validation)
        column.addLayout(training)
        tools = QHBoxLayout()
        self.train = QPushButton("Train and save profile")
        self.train.setToolTip("Train from the included references and save the new profile locally. Review it before activation.")
        self.train.clicked.connect(owner._train_learning_profile)
        self.validate_corpus = QPushButton("Validate across chapters")
        self.validate_corpus.setToolTip("Compare profiles on source chapters held out from training. At least two selected source groups are needed.")
        self.validate_corpus.clicked.connect(lambda: owner._validate_learning_corpus())
        self.validate_corpus.setEnabled(False)
        self.view_validation = QPushButton("View validation report")
        self.view_validation.clicked.connect(lambda: owner._show_learning_validation_report())
        self.view_validation.setEnabled(False)
        self.load_profile = QPushButton("Load profile…")
        self.load_profile.clicked.connect(owner._load_learning_profile_file)
        self.cancel = QPushButton("Cancel operation")
        self.cancel.clicked.connect(owner._cancel_learning_job)
        self.cancel.hide()
        tools.addWidget(self.train)
        tools.addWidget(self.validate_corpus)
        tools.addWidget(self.view_validation)
        tools.addWidget(self.load_profile)
        tools.addStretch(1)
        tools.addWidget(self.cancel)
        column.addLayout(tools)
        self.profiles = QComboBox()
        self.profiles.currentIndexChanged.connect(owner._show_selected_learning_report)
        self.use_profile = QPushButton("Use selected profile")
        self.use_profile.clicked.connect(owner._activate_learning_profile)
        self.save_profile_as = QPushButton("Save profile as…")
        self.save_profile_as.setToolTip("Save a copy of the selected trained profile in a folder of your choice. It can be loaded again with Load profile.")
        self.save_profile_as.clicked.connect(owner._save_learning_profile_as)
        self.save_profile_as.setEnabled(False)
        selection = QHBoxLayout()
        selection.addWidget(self.profiles, 1)
        selection.addWidget(self.save_profile_as)
        selection.addWidget(self.use_profile)
        column.addLayout(selection)
        self.active = QLabel()
        self.active.setWordWrap(True)
        column.addWidget(self.active)
        self.operation = QLabel("")
        self.operation.setWordWrap(True)
        column.addWidget(self.operation)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        column.addWidget(self.progress)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMinimumHeight(120)
        column.addWidget(self.report, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        column.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self.controls = (self.reference_name, self.reference_group, self.approved, self.include_automatic, self.reference_in_out,
                         self.import_resolve, self.import_project, self.import_batch, self.references, self.profile_name,
                         self.validation, self.train, self.validate_corpus, self.view_validation,
                         self.inspect_reference, self.edit_source_group, self.remove_reference, self.load_profile, self.profiles,
                         self.save_profile_as, self.use_profile)
        self.resize(920, 860)

    def closeEvent(self, event):
        if self.owner._learning_job_busy:
            self.owner._cancel_learning_job()
            event.ignore()
        else:
            super().closeEvent(event)


class LearningReviewMixin:
    def _init_learning_workflow(self, message):
        self._learning_message = message
        self._learning_profile = None
        self._learning_profile_path = ""
        self._learning_job_busy = False
        self._learning_stop = None
        self._learning_refs = []
        self._learning_corpus_summary_cache = None
        self._learning_profile_choices = {}
        self._learning_loaded_profiles = {}
        self._learning_export_folder = None
        self._learning_refreshing = False
        self._selection_profile_key = ""
        self.learning_dialog = None

    def _build_learning_button(self):
        self.learning_button = QPushButton("Learning")
        self.learning_button.setObjectName("learningButton")
        self.learning_button.clicked.connect(self._show_learning)
        self._sync_learning_active()
        return self.learning_button

    def _ensure_learning_dialog(self):
        if self.learning_dialog is None:
            self.learning_dialog = LearningDialog(self)
        return self.learning_dialog

    def _show_learning(self):
        if self.worker is not None:
            return
        dialog = self._ensure_learning_dialog()
        try:
            self._refresh_learning_lists()
        except (OSError, ValueError) as error:
            self._learning_error("The local references could not be read.", error)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _learning_error(self, heading, error=None):
        self._learning_message.tell(self.learning_dialog or self, "Personal learning", heading,
                                    str(error) if error is not None else "")

    def _active_selection_profile_key(self):
        return (self._learning_profile_path or "embedded") if self._learning_profile is not None else ""

    def _refresh_learning_profile_choices(self, select_path=None):
        """Read the small profile catalog without opening the reference library."""
        from vispa_mp.learning_data import PROFILES_DIR
        from vispa_mp.learning_model import load_profile, validate_profile
        dialog = self.learning_dialog
        selected = str(select_path) if select_path is not None else (dialog.profiles.currentData() if dialog else None)
        choices, labels = {}, {}
        for path in sorted(Path(PROFILES_DIR).glob("*.json")):
            try:
                profile = load_profile(path)
            except (OSError, ValueError):
                continue
            key = str(path.resolve())
            choices[key], labels[key] = profile, profile["name"]
        for key, cached in self._learning_loaded_profiles.items():
            if key not in choices:
                try:
                    profile = validate_profile(cached)
                except ValueError:
                    continue
                choices[key], labels[key] = profile, profile["name"]
        active_key = self._active_selection_profile_key()
        if self._learning_profile is not None:
            if active_key == "embedded":
                choices[active_key] = self._learning_profile
                labels[active_key] = self._learning_profile["name"] + " (saved in project)"
                if selected is None:
                    selected = active_key
            elif active_key not in choices:
                choices[active_key], labels[active_key] = self._learning_profile, self._learning_profile["name"]
        self._learning_profile_choices = choices
        self._learning_profile_labels = labels
        if dialog is not None:
            blocked = dialog.profiles.blockSignals(True)
            try:
                dialog.profiles.clear()
                dialog.profiles.addItem("Standard rules (no personal profile)", "")
                for key, profile in choices.items():
                    dialog.profiles.addItem(labels[key], key)
                choice = active_key if selected is None else selected
                dialog.profiles.setCurrentIndex(max(0, dialog.profiles.findData(choice)))
            finally:
                dialog.profiles.blockSignals(blocked)
        self._sync_selection_profile_panels(select_key=str(select_path) if select_path is not None else None)

    def _sync_selection_profile_panels(self, select_key=None):
        active_key = self._active_selection_profile_key()
        choices = self._learning_profile_choices
        selected = self._selection_profile_key if select_key is None else select_key
        if selected and selected not in choices:
            selected = active_key
        self._selection_profile_key = selected
        idle = self.worker is None and not self._learning_job_busy
        for name in ("selection_profile_panel", "settings_profile_panel"):
            panel = getattr(self, name, None)
            if panel is None:
                continue
            blocked = panel.profiles.blockSignals(True)
            try:
                panel.profiles.clear()
                panel.profiles.addItem("MP standard rules", "")
                for key, profile in choices.items():
                    panel.profiles.addItem(getattr(self, "_learning_profile_labels", {}).get(key, profile["name"]), key)
                    panel.profiles.setItemData(panel.profiles.count() - 1, key if key != "embedded" else "Profile included in this project", Qt.ItemDataRole.ToolTipRole)
                panel.profiles.setCurrentIndex(max(0, panel.profiles.findData(selected)))
            finally:
                panel.profiles.blockSignals(blocked)
            active = self._learning_profile
            text = f"Active: {active['name']}" if active is not None else "Active: MP standard rules"
            panel.active.setText(text)
            panel.active.setToolTip(text + ". Your current settings and manual edits remain in effect.")
            panel.profiles.setToolTip(panel.profiles.currentText())
            pending = panel.profiles.currentData() != active_key
            panel.detail.setText("Selected, not applied. Click Use selection to activate." if pending else
                                 "Personal image ranking · your settings stay active." if active is not None else
                                 "Standard image ranking · your settings stay active.")
            for control in panel.controls:
                control.setEnabled(idle)
            panel.apply.setEnabled(idle and pending)
            panel.compare.setEnabled(idle and bool(self.analysis) and self._comparison_profile(panel) is not None)
            panel.compare.setToolTip(
                "Analyze a timeline first; comparison reuses its measured images." if not self.analysis else
                "Choose or load a personal profile to compare with MP standard rules." if self._comparison_profile(panel) is None else
                "Open standard rules and this personal profile side by side, without changing your current review.")

    def _selection_profile_chosen(self, panel):
        if self.worker is not None or self._learning_job_busy:
            return
        self._sync_selection_profile_panels(select_key=panel.profiles.currentData() or "")

    def _apply_selection_profile(self, panel):
        self._activate_learning_profile_key(panel.profiles.currentData() or "")

    def _load_selection_profile(self, panel):
        if self.worker is not None or self._learning_job_busy:
            return
        key = self._choose_learning_profile_file(panel.window())
        if key is not None:
            self._refresh_learning_profile_choices(select_path=key)
            self.status.setText("Profile loaded for inspection. Use selection activates it; the active profile was kept.")
            if self.learning_dialog is not None:
                self._show_selected_learning_report()

    def _show_selection_profile_settings(self):
        if self.worker is not None or self._learning_job_busy:
            return
        self._refresh_learning_profile_choices()
        self.settings_tabs.setCurrentWidget(self.settings_profile_panel)
        self._show_settings()

    def _refresh_learning_lists(self, select_path=None):
        from vispa_mp.learning_data import list_references
        dialog = self._ensure_learning_dialog()
        try:
            self._learning_refs = list_references()
            self._learning_corpus_summary_cache = None
        except (OSError, ValueError):
            self._learning_refs = []
            self._learning_corpus_summary_cache = None
            dialog.references.clear()
            self._sync_learning_corpus_controls()
            raise
        selected_ids = {item.data(0, Qt.ItemDataRole.UserRole) for item in dialog.references.selectedItems()}
        group_names = {}
        for reference in self._learning_refs:
            group = reference.get("group_id") or "unknown"
            group_names.setdefault(group, []).append(reference.get("name") or "Chapter")
        blocked = dialog.references.blockSignals(True)
        self._learning_refreshing = True
        try:
            dialog.references.clear()
            for reference in self._learning_refs:
                counts = _counts(reference)
                group = reference.get("group_id") or "Unknown source"
                enabled = reference.get("enabled", True)
                item = QTreeWidgetItem([reference.get("name") or "Chapter", _source_group_label(group, group_names[group]),
                                        str(counts["page"]), str(counts["core"]), str(counts["extra"])])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
                source = reference.get("source") or {}
                scope = source.get("range") if isinstance(source, dict) else None
                scope_text = " Imported In/Out frames: " + str(scope) + "." if scope else ""
                item.setToolTip(0, "Checked references take part in future training and validation. Existing profiles stay unchanged." + scope_text)
                media = (source.get("media") or []) if isinstance(source, dict) else []
                media = media if isinstance(media, (list, tuple)) else []
                paths = [entry.get("path") if isinstance(entry, dict) else entry for entry in media]
                filenames = [Path(path).name for path in paths if isinstance(path, str) and path]
                item.setToolTip(1, "\n".join(name for name in filenames if name) or _source_group_label(group, group_names[group]))
                item.setData(0, Qt.ItemDataRole.UserRole, reference.get("id"))
                item.setData(1, Qt.ItemDataRole.UserRole, group)
                dialog.references.addTopLevelItem(item)
                item.setSelected(reference.get("id") in selected_ids)
        finally:
            self._learning_refreshing = False
            dialog.references.blockSignals(blocked)
        for index in range(dialog.references.columnCount()):
            dialog.references.resizeColumnToContents(index)
        self._refresh_learning_validation_groups()
        self._refresh_learning_profile_choices(select_path)
        self._sync_learning_corpus_controls()
        self._sync_learning_active()
        self._show_selected_learning_report()

    def _active_learning_references(self):
        return [reference for reference in self._learning_refs if reference.get("enabled", True)]

    def _refresh_learning_validation_groups(self):
        dialog = self.learning_dialog
        chosen_group = dialog.validation.currentData()
        groups = {}
        for reference in self._active_learning_references():
            groups.setdefault(reference["group_id"], []).append(reference.get("name") or "Chapter")
        dialog.validation.clear()
        dialog.validation.addItem("Automatic held-out chapter group", None)
        for group, names in sorted(groups.items()):
            dialog.validation.addItem(f"{_source_group_label(group, names)} ({len(names)} reference(s))", group)
        dialog.validation.setCurrentIndex(max(0, dialog.validation.findData(chosen_group)))

    def _sync_learning_corpus_controls(self):
        if self.learning_dialog is None:
            return
        dialog = self.learning_dialog
        active = self._active_learning_references()
        idle = not self._learning_job_busy and self.worker is None
        dialog.train.setEnabled(idle and bool(active))
        dialog.validate_corpus.setEnabled(idle and len({reference["group_id"] for reference in active}) >= 2)
        dialog.inspect_reference.setEnabled(idle and len(dialog.references.selectedItems()) == 1)
        dialog.edit_source_group.setEnabled(idle and bool(dialog.references.selectedItems()))
        dialog.remove_reference.setEnabled(idle and bool(dialog.references.selectedItems()))
        dialog.save_profile_as.setEnabled(idle and dialog.profiles.currentData() in self._learning_profile_choices)
        updater = getattr(self, "_update_learning_corpus_summary", None)
        if callable(updater):
            updater()
        else:
            dialog.corpus_summary.setText(f"{len(active)} of {len(self._learning_refs)} references selected for learning.")

    def _learning_reference_selection_changed(self):
        if not self._learning_refreshing:
            self._sync_learning_corpus_controls()

    def _inspect_learning_reference(self, item=None, _column=0):
        if self.worker is not None or self._learning_job_busy:
            return
        dialog = self._ensure_learning_dialog()
        if item is None:
            selected = dialog.references.selectedItems()
            if len(selected) != 1:
                return
            item = selected[0]
        identifier = item.data(0, Qt.ItemDataRole.UserRole)
        reference = next((ref for ref in self._learning_refs if ref["id"] == identifier), None)
        if reference is None:
            self._learning_error("The selected reference is no longer available. Reopen Learning to refresh the chapter list.")
            return
        try:
            from vispa_mp.learning_reference_ui import ReferencePreviewDialog
            preview = ReferencePreviewDialog(self, reference)
        except (OSError, ValueError) as error:
            self._learning_error("The reference images could not be inspected.", error)
            return
        old_preview = getattr(self, "learning_reference_dialog", None)
        if old_preview is not None:
            old_preview.close()
            old_preview.deleteLater()
        self.learning_reference_dialog = preview
        preview.show()
        preview.raise_()
        preview.activateWindow()

    def _learning_reference_toggled(self, item, column):
        if self._learning_refreshing or column != 0:
            return
        identifier = item.data(0, Qt.ItemDataRole.UserRole)
        previous = next((reference for reference in self._learning_refs if reference["id"] == identifier), None)
        if previous is None:
            return
        enabled = item.checkState(0) == Qt.CheckState.Checked
        before = previous.get("enabled", True)
        if enabled == before:
            return
        try:
            if self.worker is not None or self._learning_job_busy:
                raise RuntimeError("Wait for the current learning operation before changing its reference selection.")
            from vispa_mp.learning_data import update_reference
            updated = update_reference(identifier, enabled=enabled)
        except (OSError, ValueError, RuntimeError) as error:
            blocked = self.learning_dialog.references.blockSignals(True)
            try:
                item.setCheckState(0, Qt.CheckState.Checked if before else Qt.CheckState.Unchecked)
            finally:
                self.learning_dialog.references.blockSignals(blocked)
            self._learning_error("The reference selection could not be saved. The previous selection was kept.", error)
            return
        # Keep this item alive until Qt has finished delivering itemChanged.
        # Enabling a reference only changes the corpus and validation choices.
        self._learning_refs = [updated if reference["id"] == identifier else reference
                               for reference in self._learning_refs]
        self._learning_corpus_summary_cache = None
        self._refresh_learning_validation_groups()
        self._sync_learning_corpus_controls()
        self.learning_dialog.operation.setText("Reference selection updated for future training. Existing profiles and the current review are unchanged.")

    def _edit_learning_source_group(self):
        if self.worker is not None or self._learning_job_busy:
            return
        dialog = self._ensure_learning_dialog()
        selected = {item.data(0, Qt.ItemDataRole.UserRole) for item in dialog.references.selectedItems()}
        references = [reference for reference in self._learning_refs if reference["id"] in selected]
        if not references:
            return
        groups = {reference["group_id"] for reference in references}
        names = [reference.get("name") or "Chapter" for reference in references]
        existing = (_source_group_label(next(iter(groups)), names) if len(groups) == 1 else _chapter_label(names))
        group, accepted = QInputDialog.getText(
            dialog, "Edit source chapter group",
            f"Source group for {len(references)} selected reference(s). Keep all versions of one chapter in the same group.\n"
            "This affects future training and validation; existing profiles stay unchanged.",
            QLineEdit.EchoMode.Normal, existing)
        if not accepted:
            return
        group = group.strip()
        if not group or len(group) > 2048:
            self._learning_error("Enter a source chapter group between 1 and 2048 characters.")
            return
        from vispa_mp.learning_data import update_reference
        changed = []
        try:
            for reference in references:
                if reference["group_id"] != group:
                    update_reference(reference["id"], group_id=group)
                    changed.append(reference)
        except (OSError, ValueError) as error:
            rollback_failed = False
            for reference in reversed(changed):
                try:
                    update_reference(reference["id"], group_id=reference["group_id"])
                except (OSError, ValueError):
                    rollback_failed = True
            try:
                self._refresh_learning_lists()
            except (OSError, ValueError):
                pass
            heading = ("Some source group changes may have been saved. Check the groups shown before training."
                       if rollback_failed else "The source groups could not be saved. The previous groups were kept.")
            self._learning_error(heading, error)
            return
        try:
            self._refresh_learning_lists()
        except (OSError, ValueError) as error:
            self._learning_error("The source groups were saved, but the reference list could not be read again.", error)
            return
        self.learning_dialog.operation.setText("Source groups updated for future training and validation. Existing profiles and the current review are unchanged.")

    def _sync_learning_active(self, *, reset_selection=False):
        name = self._learning_profile.get("name") if self._learning_profile else None
        text = f"Active: {name}" if name else "Active: standard rules"
        if getattr(self, "learning_button", None) is not None:
            self.learning_button.setText("Learning")
            self.learning_button.setToolTip(text)
        if self.learning_dialog is not None:
            self.learning_dialog.active.setText(text)
        self._sync_selection_profile_panels(select_key=self._active_selection_profile_key() if reset_selection else None)

    def _remove_learning_references(self):
        if self.worker is not None or self._learning_job_busy:
            return
        dialog = self._ensure_learning_dialog()
        ids = {item.data(0, Qt.ItemDataRole.UserRole) for item in dialog.references.selectedItems()}
        references = [ref for ref in self._learning_refs if ref["id"] in ids]
        if not references:
            return
        names = "\n".join(ref["name"] for ref in references)
        if not self._learning_message.ask(dialog, "Remove learning references",
                                          f"Remove {len(references)} reference(s) from this learning library?",
                                          names + "\nResolve projects, timelines, markers and previously trained profiles stay unchanged.",
                                          "Remove references"):
            return
        from vispa_mp.learning_data import remove_reference
        removed = 0
        error = None
        for ref in references:
            try:
                remove_reference(ref["id"])
                removed += 1
            except (OSError, ValueError) as failure:
                error = failure
                break
        self._refresh_learning_lists()
        text = f"{removed} reference(s) removed from the learning library. Resolve projects and markers were kept."
        dialog.operation.setText(text)
        self.status.setText(text)
        if error is not None:
            self._learning_error("Some selected references could not be removed. Check the chapter list before continuing.", error)

    def _show_selected_learning_report(self, *_args):
        if self.learning_dialog is None:
            return
        selected = self.learning_dialog.profiles.currentData()
        profile = self._learning_profile_choices.get(selected)
        self.learning_dialog.save_profile_as.setEnabled(bool(profile) and self.worker is None and not self._learning_job_busy)
        if profile:
            if selected == "embedded":
                saved = "Profile included in the current VISPA MP project."
            else:
                try:
                    exists = Path(selected).is_file()
                except OSError:
                    exists = False
                saved = ("Profile saved locally." if exists else
                         "Profile available in memory. Save profile as… keeps a copy.")
            self.learning_dialog.report.setPlainText(saved + "\n\n" + profile_report(profile))
        else:
            self.learning_dialog.report.setPlainText(
                "References are saved locally after each import. Name your profile, then choose Train and save profile to create it. Use selected profile activates it after review.")

    def _set_learning_busy(self, busy, label=None):
        self._learning_job_busy = bool(busy)
        self._sync_selection_profile_panels()
        if self.learning_dialog is None:
            return
        for control in self.learning_dialog.controls:
            control.setEnabled(not busy)
        self.learning_dialog.cancel.setVisible(busy)
        self.learning_dialog.cancel.setEnabled(busy)
        self.learning_dialog.progress.setVisible(busy)
        if busy:
            self.learning_dialog.progress.setRange(0, 0)
        if label is not None:
            self.learning_dialog.operation.setText(label)
            batch_dialog = getattr(self, "learning_batch_dialog", None)
            if batch_dialog is not None:
                batch_dialog.status.setText(label)
                batch_dialog.progress.setRange(0, 0)
        self._sync_learning_corpus_controls()
        self._sync_learning_batch_controls()

    def _update_learning_progress(self, value):
        if not self._learning_job_busy or self.learning_dialog is None:
            return
        dialog = self.learning_dialog
        if isinstance(value, dict):
            parts = [str(value.get(key) or "").strip() for key in ("label", "detail", "left")]
            text = " · ".join(part for part in parts if part)
            try:
                fraction = float(value.get("fraction") or 0)
                step = int(value.get("step") or 1)
                steps = max(1, int(value.get("steps") or 1))
                if not math.isfinite(fraction):
                    raise ValueError("Invalid progress")
            except (ValueError, TypeError, OverflowError):
                dialog.progress.setRange(0, 0)
            else:
                percent = round(100 * (step - 1 + min(1, max(0, fraction))) / steps)
                dialog.progress.setRange(0, 100)
                dialog.progress.setValue(min(100, max(0, percent)))
        else:
            text = str(value)
            dialog.progress.setRange(0, 0)
        if self._learning_stop is None or not self._learning_stop.is_set():
            dialog.operation.setText(text)
        self._update_learning_batch_progress(value)

    def _learning_job_finished(self):
        self._learning_stop = None
        self._set_learning_busy(False)

    def _handle_learning_failure(self, _message):
        if not self._learning_job_busy:
            return False
        cancelled = self._learning_stop is not None and self._learning_stop.is_set()
        self._learning_job_finished()
        if cancelled:
            self.status.setText("Learning operation cancelled. The current review was kept.")
            if self.learning_dialog is not None:
                self.learning_dialog.operation.setText("Operation cancelled; the current review was kept.")
        return cancelled

    def _run_learning_job(self, label, work, done):
        if self.worker is not None or self._learning_job_busy:
            return
        stop = threading.Event()
        self._learning_stop = stop
        self._set_learning_busy(True, label)

        def run(progress):
            if stop.is_set():
                raise InterruptedError("Learning operation was stopped.")
            return work(progress, stop.is_set)

        def complete(result):
            self._set_learning_busy(False)
            try:
                done(result)
            except (OSError, ValueError, RuntimeError) as error:
                self._learning_error("The learning operation could not be completed.", error)

        try:
            self._start(run, complete)
        except Exception as error:
            cancelled = stop.is_set()
            self._learning_job_finished()
            if not cancelled:
                self._learning_error("The learning operation failed.", error)
        if self.worker is not None:
            self.worker.finished.connect(self._learning_job_finished)
        else:
            self._learning_job_finished()

    def _cancel_learning_job(self):
        if self._learning_stop is not None:
            self._learning_stop.set()
            if self.learning_dialog is not None:
                self.learning_dialog.cancel.setEnabled(False)
                self.learning_dialog.operation.setText("Cancelling after the current step…")
            self._sync_learning_batch_controls()

    def _when_learning_idle(self, callback):
        def ready():
            if self.worker is not None:
                QTimer.singleShot(10, ready)
            else:
                callback()
        QTimer.singleShot(0, ready)

    def _reference_options(self):
        dialog = self._ensure_learning_dialog()
        return {"name": dialog.reference_name.text().strip() or None,
                "group_id": dialog.reference_group.text().strip() or None}

    def _reference_is_approved(self):
        if self._ensure_learning_dialog().approved.isChecked():
            return True
        self._learning_error("Review and approve the chapter's marker choices before importing them as learning references.")
        return False

    def _import_current_learning_reference(self):
        if self.worker is not None or not self._reference_is_approved():
            return
        options = self._reference_options()
        include_automatic = self.learning_dialog.include_automatic.isChecked()
        use_in_out = self.learning_dialog.reference_in_out.isChecked()
        settings = deepcopy(self.settings())

        def read(_progress, cancel):
            client = self.client or open_client()
            owned = self.client is None
            try:
                snapshot = normalize(client.read())
                if cancel():
                    raise InterruptedError("Reference import was stopped.")
                return snapshot
            finally:
                if owned:
                    client.close()

        def preview(snapshot):
            from vispa_mp.learning_data import reference_range
            span = reference_range(snapshot, use_in_out)
            selected = [marker for marker in snapshot.get("markers") or []
                        if marker.get("color") in ("Green", "Blue", "Cyan")
                        and (include_automatic or not marker.get("automatic"))
                        and (span is None or span[0] <= marker["frame"] < span[1])]
            if not selected:
                self._learning_error("No approved marker roles were found in this timeline.",
                                     "Use green Page starts, blue Core images or cyan Extras. MP-created markers are excluded unless explicitly enabled.")
                return
            project = snapshot.get("project_name") or "Resolve project"
            timeline = snapshot.get("timeline_name") or "Current timeline"
            scope = "Whole timeline."
            if span is not None:
                from vispa_mp.timebase import format_timecode
                scope = f"In/Out only: {format_timecode(span[0], snapshot)} – {format_timecode(span[1], snapshot)}."
            if not self._learning_message.ask(self.learning_dialog, "Import reference",
                                               f"Import {len(selected)} approved markers from {timeline}?",
                                               f"Project: {project}. {scope} Their exact source images will become learning examples. Nothing is placed or changed in Resolve.",
                                               "Import reference"):
                return

            def import_work(progress, cancel):
                from vispa_mp.learning_data import import_timeline_reference, save_imported_reference
                reference = import_timeline_reference(snapshot, settings, self._cache_dir(),
                                                       include_automatic=include_automatic,
                                                       progress=progress, cancel=cancel, use_in_out=use_in_out, **options)
                if cancel():
                    raise InterruptedError("Reference import was stopped.")
                path = save_imported_reference(reference, group_id=options.get("group_id"))
                return reference, path

            self._when_learning_idle(lambda: self._run_learning_job("Extracting approved reference images…", import_work,
                                                                    self._learning_reference_imported))

        self._run_learning_job("Reading the current Resolve timeline…", read, preview)

    def _learning_reference_imported(self, result):
        reference, _path = result
        self._refresh_learning_lists()
        counts = _counts(reference)
        text = (f"Reference imported: {reference.get('name') or 'Chapter'} · saved locally · {counts['core']} Core including starts, "
                f"{counts['extra']} Extras, {counts['page']} page starts. The current review is unchanged.")
        self.learning_dialog.operation.setText(text)
        self.status.setText(text)

    def _import_learning_project(self):
        if self.worker is not None or not self._reference_is_approved():
            return
        path, _filter = QFileDialog.getOpenFileName(self.learning_dialog, "Import an approved VISPA MP review", "", FILE_FILTER)
        if not path:
            return
        options = self._reference_options()
        if not self._learning_message.ask(self.learning_dialog, "Import reference", "Use this review as an approved reference?",
                                          f"{Path(path).name}. Its prepared marker choices will become learning examples; your current review will stay open.",
                                          "Import reference"):
            return

        def work(_progress, cancel):
            from vispa_mp.learning_data import reference_from_project, save_imported_reference
            project = load_project(path, self._cache_dir() / "learning" / "review_images")
            if cancel():
                raise InterruptedError("Reference import was stopped.")
            reference = reference_from_project(project, **options)
            if cancel():
                raise InterruptedError("Reference import was stopped.")
            return reference, save_imported_reference(reference, group_id=options.get("group_id"))

        self._run_learning_job("Reading the approved review…", work, self._learning_reference_imported)

    def _train_learning_profile(self):
        if self.worker is not None:
            return
        self._ensure_learning_dialog()
        references = deepcopy(self._active_learning_references())
        if not references:
            self._learning_error("Import at least one approved chapter before training a personal profile.")
            return
        name = self.learning_dialog.profile_name.text().strip() or "My selection"
        holdout = self.learning_dialog.validation.currentData()

        def work(progress, cancel):
            from vispa_mp.learning_data import PROFILES_DIR
            from vispa_mp.learning_model import save_profile, train_profile
            profile = train_profile(references, name=name, holdout_group=holdout,
                                    progress=progress, cancel=cancel)
            if cancel():
                raise InterruptedError("Profile training was stopped.")
            path = Path(PROFILES_DIR) / f"profile-{uuid.uuid4().hex}.json"
            save_profile(profile, path)
            return profile, path

        def done(result):
            profile, path = result
            self._refresh_learning_lists(select_path=path.resolve())
            self._show_selected_learning_report()
            self.learning_dialog.operation.setText("Profile trained and saved locally. Save profile as… keeps another copy; Use selected profile activates it after review.")
            self.learning_dialog.operation.setToolTip(str(path.resolve()))
            self.status.setText("Personal profile trained; the current selection profile has not changed.")

        self._run_learning_job("Training a local selection profile…", work, done)

    def _save_learning_profile_as(self):
        """Export the inspected trained profile without retraining or activation."""
        if self.worker is not None or self._learning_job_busy:
            return
        dialog = self._ensure_learning_dialog()
        selected = dialog.profiles.currentData()
        try:
            from vispa_mp.learning_model import save_profile, validate_profile
            profile = self._learning_profile_choices.get(selected)
            if profile is None:
                self._learning_error("Train and save a profile, or load an existing profile, before saving a copy.")
                return
            profile = validate_profile(profile)
        except ValueError as error:
            self._learning_error("The selected profile cannot be saved.", error)
            return
        name = re.sub(r"[^\w .-]+", "_", profile["name"]).strip(" .")[:80] or "selection"
        folder = self._learning_export_folder or Path.home()
        initial = str(Path(folder) / f"vispa-profile-{name}.json")
        path, _filter = QFileDialog.getSaveFileName(dialog, "Save a copy of the trained profile", initial,
                                                  "VISPA MP personal profile (*.json)")
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".json")
        try:
            save_profile(profile, target)
        except (OSError, ValueError) as error:
            self._learning_error("The profile copy could not be saved. The original profile and current review were kept.", error)
            return
        self._learning_export_folder = target.parent
        text = f"Profile copy saved: {target.name}. Load profile… can reopen it."
        dialog.operation.setText(text)
        dialog.operation.setToolTip(str(target.resolve()))
        self.status.setText(text)

    def _choose_learning_profile_file(self, parent):
        path, _filter = QFileDialog.getOpenFileName(parent, "Load a personal profile", "", "VISPA MP personal profile (*.json)")
        if not path:
            return None
        try:
            from vispa_mp.learning_model import load_profile
            profile = load_profile(path)
        except (OSError, ValueError) as error:
            self._learning_error("This personal profile cannot be loaded.", error)
            return None
        key = str(Path(path).resolve())
        self._learning_loaded_profiles[key] = deepcopy(profile)
        return key

    def _load_learning_profile_file(self):
        if self.worker is not None or self._learning_job_busy:
            return
        dialog = self._ensure_learning_dialog()
        key = self._choose_learning_profile_file(dialog)
        if key is None:
            return
        self._refresh_learning_profile_choices(select_path=key)
        self._show_selected_learning_report()
        dialog.operation.setText("Profile loaded for inspection. Choose Use selected profile to activate it.")

    def _activate_learning_profile(self):
        dialog = self._ensure_learning_dialog()
        self._activate_learning_profile_key(dialog.profiles.currentData() or "")

    def _activate_learning_profile_key(self, key):
        if self.worker is not None or self._learning_job_busy:
            return
        try:
            from vispa_mp.learning_model import load_profile, validate_profile
            profile = (validate_profile(self._learning_profile_choices[key]) if key == "embedded" else
                       load_profile(key) if key else None)
        except (OSError, ValueError, KeyError) as error:
            self._learning_error("This personal profile cannot be activated. The current profile was kept.", error)
            return
        self._learning_profile = profile
        self._learning_profile_path = "" if key == "embedded" else key
        self._stored_settings["learning_profile"] = self._learning_profile_path
        self._sync_learning_active(reset_selection=True)
        self.recompute()
        self._mark_project_dirty()
        self.save_settings()
        self.status.setText(f"Personal profile active: {profile['name']}." if profile else "Standard selection rules are active.")

    def _load_selected_learning_profile(self):
        path = (self._stored_settings or {}).get("learning_profile") or ""
        if not path:
            self._learning_profile = None
            self._learning_profile_path = ""
            self._refresh_learning_profile_choices()
            self._sync_learning_active(reset_selection=True)
            return
        try:
            from vispa_mp.learning_model import load_profile
            profile = load_profile(path)
        except (OSError, ValueError) as error:
            self._learning_profile = None
            self._learning_profile_path = ""
            self._stored_settings["learning_profile"] = ""
            self.status.setText(f"The saved personal profile could not be loaded. Standard rules are active: {error}")
        else:
            self._learning_profile = profile
            self._learning_profile_path = str(Path(path).resolve())
        self._refresh_learning_profile_choices()
        self._sync_learning_active(reset_selection=True)

    def _restore_learning_profile(self, profile=None):
        from vispa_mp.learning_model import validate_profile
        self._learning_profile = validate_profile(profile) if profile is not None else None
        self._learning_profile_path = ""
        self._stored_settings["learning_profile"] = ""
        self._refresh_learning_profile_choices(select_path=self._active_selection_profile_key())
        self._sync_learning_active(reset_selection=True)

    def _project_learning_profile(self):
        return deepcopy(self._learning_profile)

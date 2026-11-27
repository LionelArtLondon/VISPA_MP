"""Keep one live suggestions panel, docked or in a second-screen window."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from vispa_mp.suggestion_selection import SuggestionSelectionMixin
from vispa_mp.suggestion_layout import SuggestionsLayoutMixin


class SuggestionsReviewMixin(SuggestionSelectionMixin, SuggestionsLayoutMixin):
    def _build_suggestions_header(self):
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.suggestion_title = QLabel("Suggestions")
        self.suggestion_title.setProperty("role", "panelTitle")
        self.suggestion_title.setMinimumWidth(0)
        self.suggestion_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.suggestion_title, 1)
        row.addWidget(QLabel("Rows"))
        self.suggestions_rows_box = QComboBox()
        self.suggestions_rows_box.setFixedWidth(76)
        self.suggestions_rows_box.addItem("Scroll", 0)
        for count in range(1, 7):
            self.suggestions_rows_box.addItem(str(count), count)
        self.suggestions_rows_box.setToolTip("Scroll keeps large previews in a scrolling strip. "
                                            "Choose 1–6 rows to fit all suggestions inside the panel.")
        self.suggestions_rows_box.setCurrentIndex(max(0, self.suggestions_rows_box.findData(self.suggestions_rows)))
        self.suggestions_rows_box.currentIndexChanged.connect(
            lambda _index: self._set_suggestions_rows(self.suggestions_rows_box.currentData()))
        row.addWidget(self.suggestions_rows_box)
        self.suggestions_auto_check = QCheckBox("Open on selection")
        self.suggestions_auto_check.setToolTip("Show suggestions when selecting an image. Leave unchecked to open them with a double-click.")
        self.suggestions_auto_check.toggled.connect(self._set_suggestions_auto_open)
        row.addWidget(self.suggestions_auto_check)
        self.detach_suggestions_button = QPushButton("Detach")
        self.detach_suggestions_button.clicked.connect(
            lambda: self._dock_suggestions() if self.suggestions_detached else self._detach_suggestions())
        row.addWidget(self.detach_suggestions_button)
        self.suggestions_fullscreen_button = QPushButton("Full screen")
        self.suggestions_fullscreen_button.setToolTip("Toggle full screen (F11). Escape returns to the window.")
        self.suggestions_fullscreen_button.clicked.connect(
            lambda: self.suggestions_window and self.suggestions_window.toggle_fullscreen())
        self.suggestions_fullscreen_button.hide()
        row.addWidget(self.suggestions_fullscreen_button)
        return header

    def _sync_suggestions_controls(self, shown):
        self._sync_suggestions_rows_control()
        blocked = self.suggestions_button.blockSignals(True)
        self.suggestions_button.setChecked(shown)
        self.suggestions_button.blockSignals(blocked)
        self.suggestions_button.setToolTip("Bring the suggestions window to the front" if self.suggestions_detached else
                                          "Show or hide candidate images for the selected marker")
        self.detach_suggestions_button.setText("Dock" if self.suggestions_detached else "Detach")
        self.detach_suggestions_button.setToolTip("Return suggestions below the main images" if self.suggestions_detached else
                                                  "Move suggestions to a separate window or another screen")
        self.suggestions_fullscreen_button.setVisible(self.suggestions_detached)
        blocked = self.suggestions_auto_check.blockSignals(True)
        self.suggestions_auto_check.setChecked(self.suggestions_auto_open)
        self.suggestions_auto_check.blockSignals(blocked)

    def _toggle_suggestions(self, shown):
        if self.worker is not None:
            return
        self._suggestions_open = bool(shown or self.suggestions_detached) and not self.selected_manual and self.selected_frame is not None
        self._refresh_suggestions()
        if self.suggestions_detached and self._suggestions_open:
            self.suggestions_window.raise_()
            self.suggestions_window.activateWindow()

    def _set_suggestions_auto_open(self, enabled):
        self.suggestions_auto_open = bool(enabled)
        if enabled:
            self._suggestions_open = not self.selected_manual and self.selected_frame is not None
        self._refresh_suggestions()
        self._mark_project_dirty()
        self._schedule_save()

    def _ensure_suggestions_window(self):
        if self.suggestions_window is None:
            from vispa_mp.suggestions_window import SuggestionsWindow
            self.suggestions_window = SuggestionsWindow(self)
        return self.suggestions_window

    def _move_suggestions_panel(self, detached, *, persist):
        if bool(detached) != self.suggestions_detached:
            if detached:
                self._suggestion_height = self.get_suggestions_height()
                window = self._ensure_suggestions_window()
                window.setCentralWidget(self.suggestion_panel)
                self.suggestions_detached = True
            else:
                self.suggestions_window.hide()
                panel = self.suggestions_window.takeCentralWidget()
                self.review_splitter.addWidget(panel)
                self.suggestions_detached = False
        self._refresh_suggestions()
        if not self.suggestions_detached:
            self.set_suggestions_height(self._suggestion_height)
        if persist:
            self._mark_project_dirty()
            self._schedule_save()

    def _detach_suggestions(self):
        if self.worker is not None:
            return
        self._suggestions_open = not self.selected_manual and self.selected_frame is not None
        self._move_suggestions_panel(True, persist=True)
        if self.suggestions_window.isVisible():
            self.suggestions_window.raise_()
            self.suggestions_window.activateWindow()

    def _dock_suggestions(self):
        self._move_suggestions_panel(False, persist=True)

    def _restore_suggestions_preferences(self, view):
        self.suggestions_rows = view.get("suggestions_rows", 0)
        self._sync_suggestions_rows_control()
        self.suggestions_auto_open = bool(view.get("suggestions_auto_open", False))
        self._suggestions_open = bool(self.suggestions_auto_open and self.selected_frame is not None and not self.selected_manual)
        self._move_suggestions_panel(bool(view.get("suggestions_detached", False)), persist=False)

    def _refresh_suggestion_panel(self):
        frames = self._suggestion_frames() if self._suggestions_open else []
        self._sync_suggestion_selection(frames)
        self._suggestion_cards = {}
        self._clear_layout(self.suggestion_layout)
        self._suggestion_grid_positions = None
        shown = self._suggestions_open or (self.suggestions_detached and self.suggestions_auto_open)
        self._sync_suggestions_controls(shown)
        if not shown:
            if not self.suggestions_detached and self.suggestion_panel.isVisible():
                self._suggestion_height = self.get_suggestions_height()
            self.suggestion_title.hide()
            self.suggestions_header.hide()
            self.suggestion_area.hide()
            self.suggestion_panel.hide()
            if not self.suggestions_detached:
                self.review_splitter.setSizes([max(240, self.review_splitter.height()), 0])
            if self.suggestions_window is not None:
                self.suggestions_window.hide()
            return
        opening = self.suggestion_panel.isHidden()
        self.suggestion_title.show()
        self.suggestions_header.show()
        self.suggestion_area.show()
        self.suggestion_panel.show()
        if not frames:
            text = ("A hand-placed marker has no cached suggestions." if self.selected_manual else
                    "No cached candidate for this marker." if self._suggestions_open else
                    "Select an image to view its suggestions.")
            self.suggestion_layout.addWidget(self._muted(text), 0, 0)
        settings = self.settings()
        for index, frame in enumerate(frames):
            self.suggestion_layout.addWidget(self._suggestion(frame, settings), 0, index)
        self._update_suggestion_card_states()
        if self.suggestions_detached:
            timeline = (self.analysis or {}).get("timeline_name") or ""
            selected = self.timecode_of(self.selected_frame) if self.selected_frame is not None else ""
            self.suggestions_window.set_selection_caption(" · ".join(part for part in (timeline, selected) if part))
            self.suggestions_window.show()
        elif opening:
            self.set_suggestions_height(self._suggestion_height)
            QTimer.singleShot(0, self, lambda: self.set_suggestions_height(self._suggestion_height))
        self._resize_suggestions()

"""Select and add candidates independently of the marker being reviewed."""

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QMenu

from vispa_mp.markers import CORE, EXTRA, NAMES, PAGE
from vispa_mp.review_history import review_edit
from vispa_mp.rules import _cavity


class SuggestionCard(QFrame):
    def __init__(self, owner, number):
        super().__init__()
        self.owner, self.number = owner, int(number)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.owner._select_suggestion(self.number, event.modifiers())
            event.accept()
        else:
            event.ignore()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.owner._use_suggestion(self.number)
            event.accept()
        else:
            event.ignore()


class SuggestionSelectionMixin:
    def _suggestion_context_key(self):
        return id(self.analysis), self.selected_frame, bool(self.selected_manual)

    def _sync_suggestion_selection(self, frames):
        context = self._suggestion_context_key()
        if context != self._suggestion_selection_context:
            self._selected_suggestion_frames.clear()
            self._suggestion_selection_context = context
        self._selected_suggestion_frames.intersection_update(int(frame["frame"]) for frame in frames)

    def _update_suggestion_card_states(self):
        for number, card in getattr(self, "_suggestion_cards", {}).items():
            card.setProperty("selected", "true" if number in self._selected_suggestion_frames else "false")
            card.setProperty("state", "preview" if number == self._preview else "")
            card.style().unpolish(card)
            card.style().polish(card)
            card.update()
        count = len(self._selected_suggestion_frames)
        self.suggestion_title.setText(f"Suggestions · {count} selected" if count else "Suggestions")

    def _select_suggestion(self, frame_number, modifiers=Qt.KeyboardModifier.NoModifier):
        if self.worker is not None or getattr(self, "_learning_job_busy", False):
            return
        frames = self._suggestion_frames()
        self._sync_suggestion_selection(frames)
        number = int(frame_number)
        if not any(int(frame["frame"]) == number for frame in frames):
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if number in self._selected_suggestion_frames:
                self._selected_suggestion_frames.remove(number)
            else:
                self._selected_suggestion_frames.add(number)
        else:
            self._selected_suggestion_frames = {number}
        selected = self._selected_suggestion_frames
        self._preview = next(iter(selected)) if len(selected) == 1 else None
        if self._preview == self.selected_frame:
            self._preview = None
        # Keep the pressed card alive, including for the second double-click
        # event. Refresh only the main previews, not the suggestion widgets.
        self._update_suggestion_card_states()
        self._refresh_thumbs()
        self._refresh_board()
        if self._preview is not None:
            self.status.setText(f"Preview {self.timecode_of(self._preview)}. Right-click to add; double-click or Enter to replace.")
        else:
            self.status.setText(f"{len(selected)} suggestion(s) selected. Right-click to add as Extra or Core.")

    def _make_suggestion_menu(self, frame_number, parent=None):
        frames = self._suggestion_frames()
        self._sync_suggestion_selection(frames)
        number = int(frame_number)
        known = {int(frame["frame"]) for frame in frames}
        if number not in self._selected_suggestion_frames:
            if number in known and self.worker is None and not getattr(self, "_learning_job_busy", False):
                self._select_suggestion(number)
            else:
                self._selected_suggestion_frames = {number} if number in known else set()
        self._update_suggestion_card_states()
        targets = tuple(sorted(self._selected_suggestion_frames))
        context = self._suggestion_context_key()
        menu = QMenu(parent or self.suggestion_panel.window())
        menu.setStyleSheet(self.styleSheet())
        available = [value for value in targets if value in known and not self._suggestion_occupied(value)]
        idle = self.worker is None and not getattr(self, "_learning_job_busy", False)
        for label, color in (("Add Extra marker", EXTRA), ("Add Core marker", CORE), ("Start a new page here", PAGE)):
            action = menu.addAction(label)
            action.setEnabled(idle and bool(available) and (color != PAGE or len(targets) == 1))
            action.triggered.connect(lambda _checked=False, color=color:
                                     self._add_suggestion_markers(targets, color, context=context))
        menu.addSeparator()
        replace = menu.addAction("Use as replacement")
        replace.setEnabled(idle and len(targets) == 1 and bool(available))
        replace.triggered.connect(lambda _checked=False:
                                  self._use_suggestion(targets[0]) if context == self._suggestion_context_key() else None)
        occupied = len(targets) - len(available)
        if occupied:
            menu.addSeparator()
            message = ("This image already has a marker" if len(targets) == 1 else
                       f"{occupied} selected image(s) already have markers; kept unchanged")
            menu.addAction(message).setEnabled(False)
        return menu

    @review_edit("add suggestion markers")
    def _add_suggestion_markers(self, frame_numbers, color=EXTRA, *, context=None):
        if (self.worker is not None or getattr(self, "_learning_job_busy", False) or color not in NAMES
                or context is not None and context != self._suggestion_context_key()):
            return 0
        # Snapshot all candidates before changing the review. In particular a
        # speech marker's suggestion pool must not switch halfway through a batch.
        sources = {int(frame["frame"]): frame for frame in self._suggestion_frames()}
        pool = (self._proposal(self.selected_frame) or {}).get("timeline_candidates") or []
        pooled_frames = {int(item["frame"]) for item in pool}
        requested = sorted({int(number) for number in frame_numbers})
        additions, occupied = [], 0
        for number in requested:
            source = sources.get(number)
            if source is None:
                continue
            if self._suggestion_occupied(number):
                occupied += 1
                continue
            additions.append({"frame": number, "color": color, "name": NAMES[color], "rule": "user",
                              "note": f"{NAMES[color]}, added from suggestion", "image": source.get("image") or "",
                              "mouth": round(float(source.get("open_mouth") or 0), 4),
                              "teeth": round(float(source.get("teeth") or 0), 4),
                              "sharpness": round(float(source.get("sharpness") or 0), 3),
                              "cavity": round(_cavity(source), 4), "strength": 0.0})
            if number in pooled_frames:
                additions[-1]["timeline_candidates"] = deepcopy(pool)
        if not additions:
            if occupied:
                self.status.setText("Selected images already have markers; existing markers were kept unchanged.")
            return 0
        anchor = self.selected_frame
        # An editorial page order is independent of timecode. Add adjacent to
        # the original image on its page, without reorganising existing images.
        if self._page_layout is not None and color != PAGE:
            group = next((group for group in self._page_layout if anchor in group["frames"]), None)
            if group is not None:
                before = [item["frame"] for item in additions if item["frame"] < anchor]
                after = [item["frame"] for item in additions if item["frame"] >= anchor]
                position = group["frames"].index(anchor)
                group["frames"][position:position] = before
                position = group["frames"].index(anchor) + 1
                group["frames"][position:position] = after
        self.proposals.extend(additions)
        self.proposals.sort(key=lambda item: int(item["frame"]))
        self._excluded_frames.difference_update(item["frame"] for item in additions)
        self._preview = None
        self._selected_suggestion_frames.clear()
        self._suggestions_open = True
        if ((self.view_filter == "core" and color == EXTRA)
                or (self.view_filter == "starts" and color != PAGE)):
            self.view_filter = "all"
            self.filter_buttons["all"].setChecked(True)
        self._fill()
        self._mark_project_dirty()
        self.status.setText(f"{len(additions)} {NAMES[color]} marker(s) added. The original marker is kept."
                            + (f" {occupied} existing marker(s) skipped." if occupied else ""))
        return len(additions)

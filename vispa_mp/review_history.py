"""Bounded undo for local marker choices, independent of the Resolve source."""

from copy import deepcopy
from functools import wraps

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QUndoCommand, QUndoStack


def review_edit(label):
    """Record one completed editorial operation, including nested batch calls.

    Selection and preview changes alone do not create commands or discard redo.
    Methods remain usable before the review history has been initialized.
    """
    def decorate(method):
        @wraps(method)
        def edit(self, *args, **kwargs):
            if (not hasattr(self, "undo_stack") or self._review_history_restoring
                    or self._review_edit_depth or self.analysis is None):
                return method(self, *args, **kwargs)
            before = self._capture_review_history()
            source = self.analysis
            generation = self._review_history_generation
            camera = (self._begin_review_camera_edit(allow_filter_change=method.__name__ == "_add_suggestion_markers")
                      if hasattr(self, "_begin_review_camera_edit") else None)
            self._review_edit_depth += 1
            try:
                result = method(self, *args, **kwargs)
            except Exception:
                # A failed local edit must not leave a partly modified review.
                if self.analysis is source and generation == self._review_history_generation:
                    if self._capture_review_history()["edit"] != before["edit"]:
                        self._restore_review_history(before)
                raise
            finally:
                self._review_edit_depth -= 1
                if hasattr(self, "_finish_review_camera_edit"):
                    self._finish_review_camera_edit(camera)
            if self.analysis is source and generation == self._review_history_generation:
                after = self._capture_review_history()
                if after["edit"] != before["edit"]:
                    self.undo_stack.push(_ReviewCommand(self, label, source, before, after))
            self._sync_review_history_actions()
            return result
        return edit
    return decorate


class _ReviewCommand(QUndoCommand):
    def __init__(self, owner, label, source, before, after):
        super().__init__(label)
        self.owner, self.source = owner, source
        self.before, self.after = before, after
        self._first_redo = True

    def undo(self):
        if self.owner.analysis is self.source:
            self.owner._restore_review_history(self.before)

    def redo(self):
        # QUndoStack.push calls redo although the decorated edit already ran.
        if self._first_redo:
            self._first_redo = False
        elif self.owner.analysis is self.source:
            self.owner._restore_review_history(self.after)


class ReviewHistoryMixin:
    def _init_review_history(self):
        self._review_history_restoring = False
        self._review_edit_depth = 0
        self._review_history_generation = 0
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(20)
        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Undo))
        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        for action, callback in ((self.undo_action, self._undo_review), (self.redo_action, self._redo_review)):
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(lambda _checked=False, callback=callback: callback())
            self.addAction(action)
        for signal in (self.undo_stack.canUndoChanged, self.undo_stack.canRedoChanged,
                       self.undo_stack.undoTextChanged, self.undo_stack.redoTextChanged):
            signal.connect(self._sync_review_history_actions)
        self._sync_review_history_actions()

    def _clear_review_history(self):
        if not hasattr(self, "undo_stack"):
            return
        self._review_history_generation += 1
        self.undo_stack.clear()
        self._sync_review_history_actions()

    def _review_history_idle(self):
        return (getattr(self, "worker", None) is None
                and not getattr(self, "_learning_job_busy", False)
                and not getattr(self, "_restoring_project", False))

    def _sync_review_history_actions(self, *_args):
        if not hasattr(self, "undo_stack"):
            return
        idle = self._review_history_idle() and self.analysis is not None
        self.undo_action.setEnabled(idle and self.undo_stack.canUndo())
        self.redo_action.setEnabled(idle and self.undo_stack.canRedo())
        undo, redo = self.undo_stack.undoText(), self.undo_stack.redoText()
        self.undo_action.setText("Undo " + undo if undo else "Undo")
        self.redo_action.setText("Redo " + redo if redo else "Redo")
        self.undo_action.setToolTip("Undo the last local marker edit (Ctrl+Z, up to 20 actions)")
        self.redo_action.setToolTip("Redo the last undone local marker edit (Ctrl+Y / Ctrl+Shift+Z)")

    def _undo_review(self):
        return self._step_review_history(False)

    def _redo_review(self):
        return self._step_review_history(True)

    def _step_review_history(self, redo):
        if not self._review_history_idle() or self.analysis is None:
            self._sync_review_history_actions()
            return False
        stack = self.undo_stack
        available = stack.canRedo() if redo else stack.canUndo()
        if not available:
            return False
        command = stack.command(stack.index() if redo else stack.index() - 1)
        if command.source is not self.analysis:
            self._clear_review_history()
            return False
        label = command.text()
        stack.redo() if redo else stack.undo()
        self._sync_review_history_actions()
        if hasattr(self, "status"):
            self.status.setText(f"{'Redone' if redo else 'Undone'}: {label}. Resolve markers are unchanged.")
        return True

    def _capture_review_history(self):
        return {
            "edit": {
                "proposals": deepcopy(self.proposals),
                "excluded_frames": set(self._excluded_frames),
                "page_layout": deepcopy(self._page_layout),
                "rule_warnings": deepcopy(self.rule_warnings),
            },
            "context": {
                "selected_frame": self.selected_frame,
                "selected_manual": bool(self.selected_manual),
                "selected_page_id": self.selected_page_id,
                "selected_keys": set(self._selected_keys),
                "range_anchor_key": getattr(self, "_range_anchor_key", None),
                "open_pages": set(self.open_pages),
                "playhead_frame": self.playhead_frame,
                "suggestions_open": bool(self._suggestions_open),
            },
        }

    def _restore_review_history_context(self, context):
        self.selected_frame = context["selected_frame"]
        self.selected_manual = context["selected_manual"]
        self.selected_page_id = context["selected_page_id"]
        self._selected_keys = set(context["selected_keys"])
        self._range_anchor_key = context.get("range_anchor_key")
        self.open_pages = set(context["open_pages"])
        self.playhead_frame = context["playhead_frame"]
        self._suggestions_open = context["suggestions_open"]

    def _restore_review_history(self, state):
        was_restoring = self._review_history_restoring
        camera = self._begin_review_camera_edit() if hasattr(self, "_begin_review_camera_edit") else None
        self._review_history_restoring = True
        try:
            edit, context = state["edit"], state["context"]
            self.proposals = deepcopy(edit["proposals"])
            self._excluded_frames = set(edit["excluded_frames"])
            self._page_layout = deepcopy(edit["page_layout"])
            self.rule_warnings = deepcopy(edit["rule_warnings"])
            self._preview = self._flash = None
            self._selected_suggestion_frames.clear()
            self._suggestion_selection_context = None
            self._restore_review_history_context(context)
            self._fill()
            # _fill normally selects a fallback when an image disappeared. A
            # snapshot already has its exact selection, including an empty one.
            self._restore_review_history_context(context)
            for page_id, row in self._rows.items():
                opened = page_id in self.open_pages
                row["children"].setVisible(opened)
                row["arrow"].setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
            if self.playhead_frame is not None:
                self._move_playhead(self.playhead_frame)
            else:
                self.last_seek = None
                self.playhead_label.setText("")
            self._paint_selection()
            self._refresh_center()
            self._sync_swatches()
            self._mark_project_dirty()
        finally:
            self._review_history_restoring = was_restoring
            if hasattr(self, "_finish_review_camera_edit"):
                self._finish_review_camera_edit(camera)
        self._sync_review_history_actions()

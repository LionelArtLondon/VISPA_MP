"""Add a local marker at an exact analyzed timeline frame, without rerunning AI."""

from copy import deepcopy
from math import isfinite
from pathlib import Path
from threading import Event

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMenu

from vispa_mp.markers import CORE, EXTRA, NAMES, PAGE
from vispa_mp.review_history import review_edit
from vispa_mp.timeline_capture import capture_timeline_candidates
from vispa_mp.timeline_identity import normalize_identity
from vispa_mp.timebase import parse_timecode


def _frame_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and -(2 ** 31) <= value < 2 ** 31


class TimelineReviewMixin:
    def _timeline_source_signature(self):
        source = self.snapshot or {}
        return {key: source.get(key) for key in ("timeline_identity", "fps", "timecode_fps", "start_frame",
                                                "end_frame", "start_timecode", "drop", "video_clips")}

    def _timeline_context(self):
        return {"analysis": self.analysis, "snapshot": self.snapshot,
                "generation": self._review_history_generation,
                "identity": normalize_identity((self.analysis or {}).get("timeline_identity")),
                "timebase": deepcopy((self.analysis or {}).get("timebase")),
                "source_signature": deepcopy(self._timeline_source_signature())}

    def _timeline_context_current(self, context):
        return (self.analysis is context["analysis"] and self.snapshot is context["snapshot"]
                and self._review_history_generation == context["generation"]
                and normalize_identity((self.analysis or {}).get("timeline_identity")) == context["identity"]
                and (self.analysis or {}).get("timebase") == context["timebase"]
                and self._timeline_source_signature() == context["source_signature"])

    def _timeline_add_problem(self, frame):
        if self.analysis is None:
            return "Analyze the timeline before adding a marker here."
        if not _frame_id(frame):
            return "Choose a valid timeline frame."
        identity = normalize_identity(self.analysis.get("timeline_identity"))
        snapshot = self.snapshot or {}
        if identity is None or identity != normalize_identity(snapshot.get("timeline_identity")):
            return "The read Resolve timeline does not match this analysis. Open the matching project and read its timeline first."
        base = self.analysis.get("timebase") or {}
        try:
            rate = float(base["fps"])
            if (any(isinstance(value, bool) for value in (base["fps"], self.analysis.get("fps"), snapshot.get("fps")))
                    or not isfinite(rate) or rate <= 0 or rate != self.analysis.get("fps")
                    or rate != snapshot.get("fps") or not _frame_id(base.get("start_frame"))
                    or base["start_frame"] != snapshot.get("start_frame")):
                raise ValueError()
            effective = self._timebase()
            shown = float(effective.get("timecode_fps") or rate)
            snapshot_shown = float(snapshot.get("timecode_fps") or rate)
            if not isfinite(shown) or shown <= 0 or shown != snapshot_shown:
                raise ValueError()
            origin, parsed_drop = parse_timecode(base["start_timecode"], shown)
            live_origin, live_drop = parse_timecode(snapshot.get("start_timecode"), shown)
            if (origin != live_origin or bool(base.get("drop", parsed_drop))
                    != bool(snapshot.get("drop", live_drop))):
                raise ValueError()
        except (KeyError, TypeError, ValueError, OverflowError):
            return "The analyzed timeline timecode is unavailable. Read and analyze the matching timeline first."
        span = self.analysis.get("range") or self._span()
        if not span[0] <= frame < span[1]:
            return "This frame is outside the analyzed timeline range."
        if self._suggestion_occupied(frame):
            return "This frame already has a marker. Existing markers are kept unchanged."
        return ""

    def _timeline_menu(self, frame, parent=None):
        menu = QMenu(parent or self)
        menu.setStyleSheet(self.styleSheet())
        menu.setToolTipsVisible(True)
        try:
            heading = self.timecode_of(frame)
        except (KeyError, TypeError, ValueError, OverflowError):
            heading = "Timeline frame"
        menu.addAction(heading).setEnabled(False)
        menu.addSeparator()
        context = self._timeline_context()
        idle = self.worker is None and not self._learning_job_busy
        problem = self._timeline_add_problem(frame) if idle else "Wait for the current operation."
        available = not problem
        for label, color in (("Add Core marker here", CORE), ("Add Extra marker here", EXTRA),
                             ("Add Page start marker here", PAGE)):
            action = menu.addAction(label)
            action.setEnabled(bool(available))
            action.setToolTip(problem or "Prepare the exact image and nearby suggestions in MP.")
            if color == PAGE and self._page_layout is not None:
                action.setToolTip("Manual page order is preserved.")
            action.triggered.connect(lambda _checked=False, color=color:
                                     self._add_timeline_marker(frame, color, context=context))
            if color == CORE:
                menu.setDefaultAction(action)
        menu.addSeparator()
        fit = menu.addAction("Fit timeline")
        fit.setEnabled(callable(getattr(self.ruler, "fit_view", None)))
        fit.triggered.connect(lambda _checked=False: self.ruler.fit_view())
        return menu

    def _show_timeline_menu(self, frame, position):
        problem = self._timeline_add_problem(frame)
        if problem:
            self.status.setText(problem)
        menu = self._timeline_menu(frame)
        try:
            menu.exec(position)
        finally:
            menu.deleteLater()

    def _add_timeline_marker(self, frame, color=CORE, *, context=None):
        if self.worker is not None or self._learning_job_busy or color not in NAMES:
            return False
        if context is not None and not self._timeline_context_current(context):
            self.status.setText("The timeline changed. Choose the frame again.")
            return False
        problem = self._timeline_add_problem(frame)
        if problem:
            self.status.setText(problem)
            return False
        context = self._timeline_context()
        stop = Event()
        self._timeline_request_id = getattr(self, "_timeline_request_id", 0) + 1
        context.update(request_id=self._timeline_request_id, worker=None,
                       stop=stop,
                       page_id=self.selected_page_id, filter=self.view_filter,
                       cameras=self.get_review_cameras())
        snapshot, analysis = deepcopy(self.snapshot), deepcopy(self.analysis)
        cache = self._cache_dir()
        self.status.setText(f"Preparing the image at {self.timecode_of(frame)}…")

        def work(_progress):
            try:
                return capture_timeline_candidates(snapshot, analysis, frame, cache, cancel=stop.is_set)
            except InterruptedError:
                return None

        def done(candidates):
            # Worker.done is delivered before QThread.finished. Let the usual
            # finished handler restore idle controls before recording the edit.
            QTimer.singleShot(0, lambda: self._finish_timeline_capture(frame, color, candidates, context))

        self._stop_analysis = stop
        try:
            self._start(work, done)
        finally:
            context["worker"] = self.worker
            if self.worker is None and self._stop_analysis is stop:
                self._stop_analysis = None
                self._set_analysis_button_state()
        if self.worker is not None:
            self._set_analysis_button_state(running=True)
            self.analyze_button.setAccessibleName("Cancel image capture")
            self.analyze_button.setToolTip("Cancel image capture — Keep the current marker preparation.")
            self.analyze_button.setEnabled(True)
        return True

    def _finish_timeline_capture(self, frame, color, candidates, context):
        if (not self._timeline_context_current(context)
                or context["request_id"] != getattr(self, "_timeline_request_id", None)):
            return
        if candidates is None or context["stop"].is_set():
            self.status.setText("Image capture cancelled. Your preparation was kept.")
            return
        if self.worker is not None:
            if self.worker is context["worker"]:
                QTimer.singleShot(10, lambda: self._finish_timeline_capture(frame, color, candidates, context))
            return
        self._commit_timeline_marker(frame, color, candidates, context)

    @review_edit("Add timeline marker")
    def _commit_timeline_marker(self, frame, color, candidates, context):
        if (self.worker is not None or self._learning_job_busy or not self._timeline_context_current(context)
                or self._timeline_add_problem(frame)):
            return False
        if (not isinstance(candidates, list) or not 1 <= len(candidates) <= 5
                or any(not isinstance(item, dict) or not _frame_id(item.get("frame"))
                       or not isinstance(item.get("image"), str) or not Path(item["image"]).is_file()
                       for item in candidates)
                or len({item["frame"] for item in candidates}) != len(candidates)):
            self.status.setText("The requested frame could not be prepared. Check that the source media is online.")
            return False
        source = next((item for item in candidates if item["frame"] == frame), None)
        if source is None:
            self.status.setText("The exact requested frame was unavailable. No marker was added.")
            return False
        proposal = {"frame": frame, "color": color, "name": NAMES[color], "rule": "user",
                    "note": f"{NAMES[color]}, added from timeline", "image": source["image"],
                    "sharpness": float(source.get("sharpness") or 0), "mouth": float(source.get("open_mouth") or 0),
                    "cavity": 0.0, "teeth": 0.0, "strength": 0.0,
                    "timeline_candidates": deepcopy(candidates)}
        self.proposals.append(proposal)
        self.proposals.sort(key=lambda item: int(item["frame"]))
        self._excluded_frames.discard(frame)
        self.selected_frame, self.selected_manual = frame, False
        self._select_single_frame(frame)
        self._preview = None
        self._selected_suggestion_frames.clear()
        self._suggestions_open = True
        if ((self.view_filter == "core" and color == EXTRA)
                or (self.view_filter == "starts" and color != PAGE)):
            self.view_filter = "all"
            self.filter_buttons["all"].setChecked(True)
        self._fill()
        if (self.selected_page_id == context.get("page_id")
                and self.view_filter in (context.get("filter"), "all")):
            self.set_review_cameras(context.get("cameras"))
        self._move_playhead(frame)
        self._ensure_page_visible(self.selected_page_id)
        self._mark_project_dirty()
        self.status.setText(f"{NAMES[color]} marker added at {self.timecode_of(frame)}. Resolve markers are unchanged.")
        return True

"""Save a review and reopen it only against its original Resolve project."""

from copy import deepcopy
from pathlib import Path
import re

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QComboBox, QFileDialog, QMenu, QSpinBox, QToolButton

from vispa_mp.client import open_client
from vispa_mp.preset import PREVIEW_DEFAULTS, load
from vispa_mp.project import FILE_FILTER as PROJECT_FILTER, load_project, save_project
from vispa_mp.project_location import get_project_folder, set_project_folder
from vispa_mp.resolve_link import link_running
from vispa_mp.snapshot import describe_rate, normalize
from vispa_mp.timeline_identity import normalize_identity


def _close_unclaimed_client(client, owned):
    if owned and client is not None:
        try:
            client.close()
        except Exception:
            pass


def _edit(snapshot):
    """The source edit, excluding markers, names, and the review's In/Out choice."""
    fields = ("path", "start", "end", "source_start", "source_end", "fps", "speed")
    return {
        "clock": [snapshot.get(key) for key in ("start_frame", "end_frame", "fps", "timecode_fps", "start_timecode", "drop")],
        "video": [[clip.get(key) for key in fields] for clip in snapshot.get("video_clips") or []],
        "audio": [[clip.get(key) for key in fields] for clip in snapshot.get("audio_clips") or []],
    }


def _target_instructions(project):
    snapshot = project["snapshot"]
    analysis = project["analysis"]
    name = snapshot.get("project_name") or analysis.get("project_name") or "the original Resolve project"
    timeline = snapshot.get("timeline_name") or analysis.get("timeline_name") or "the analyzed timeline"
    return (f'Open DaVinci Resolve, open project "{name}" and timeline "{timeline}", '
            "then run Workspace > Scripts > VISPA_MP and open this VISPA MP file again.")


class ProjectReviewMixin:
    def _init_project_workflow(self, message, slider_scales):
        self.project_path = None
        self._project_dirty = False
        self._restoring_project = False
        self._project_message = message
        self._project_slider_scales = slider_scales

    def _build_project_button(self):
        self.project_button = QToolButton()
        self.project_button.setText("Project")
        self.project_button.setAccessibleName("Project")
        self.project_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.project_menu = QMenu(self.project_button)
        actions = (
            ("open_project_action", "Open project…", "Ctrl+O", self._open_project),
            ("save_project_action", "Save project", "Ctrl+S", self._choose_save_project),
            ("save_project_as_action", "Save project as…", "Ctrl+Shift+S", lambda: self._choose_save_project(True)),
        )
        for name, text, shortcut, callback in actions:
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(lambda _checked=False, callback=callback: callback())
            self.addAction(action)
            self.project_menu.addAction(action)
            setattr(self, name, action)
        self.project_menu.addSeparator()
        self.project_folder_action = self.project_menu.addAction("DaVinci project folder…")
        self.project_folder_action.triggered.connect(lambda _checked=False: self._choose_project_folder())
        self.project_button.setMenu(self.project_menu)
        return self.project_button

    def _mark_project_dirty(self):
        if self._ready and self.analysis is not None and not self._restoring_project:
            self._project_dirty = True
            self._sync_project_title()

    def _set_review_busy(self, busy):
        for name in ("project_button", "read_button", "apply_button", "settings_button", "settings_dialog",
                     "pages_panel", "review_center", "review_adjust", "strip_button", "board_button"):
            getattr(self, name).setEnabled(not busy)
        for action in (self.open_project_action, self.save_project_action, self.save_project_as_action):
            action.setEnabled(not busy)
        self.analyze_button.setEnabled(not busy)

    def _sync_project_title(self):
        caption = "VISPA MP"
        if self.project_path is not None:
            caption += f" · {Path(self.project_path).name}"
        if self._project_dirty:
            caption += " *"
        self.setWindowTitle(caption)
        if hasattr(self, "titlebar"):
            self.titlebar.set_caption(caption)

    def _forget_project_file(self):
        self.project_path = None
        self._project_dirty = False
        self._sync_project_title()

    def _project_view(self):
        identity = (self.analysis or {}).get("timeline_identity")
        folder = get_project_folder(identity)
        return {
            "page_format": self.page_format, "orientation": self.orientation,
            "custom_width": self.custom_width, "custom_height": self.custom_height,
            **{key: getattr(self, key, default) for key, default in PREVIEW_DEFAULTS.items()},
            "excluded_frames": sorted(getattr(self, "_excluded_frames", set())),
            "page_layout": deepcopy(getattr(self, "_page_layout", None)),
            "mode": self.mode, "view_filter": self.view_filter,
            "suggestions_height": self.get_suggestions_height(),
            "cameras": self.get_review_cameras(),
            "selected_frame": self.selected_frame, "selected_manual": self.selected_manual,
            "selected_page_id": self.selected_page_id, "playhead_frame": self.playhead_frame,
            "open_pages": sorted(self.open_pages), "rule_warnings": list(self.rule_warnings),
            "project_folder": str(folder) if folder is not None else "",
        }

    def _choose_project_folder(self):
        if self.worker is not None:
            return None
        identity = (self.analysis or self.snapshot or {}).get("timeline_identity")
        if normalize_identity(identity) is None:
            self._project_message.tell(self, "Project folder", "Read the Resolve timeline first.")
            return None
        previous = get_project_folder(identity)
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the folder containing your DaVinci project (.drp)", str(previous or Path.home()))
        if not folder:
            return None
        try:
            set_project_folder(identity, folder)
        except (OSError, ValueError) as error:
            self._project_message.tell(self, "Project folder", "The project folder was not saved.", str(error))
            return None
        self.status.setText(f"DaVinci project folder: {folder}")
        return Path(folder)

    def _choose_save_project(self, force_new=False):
        if self.worker is not None:
            self.status.setText("Wait for the current operation before saving the project.")
            return False
        if self.analysis is None:
            self._project_message.tell(self, "Save project", "Analyze a timeline before saving its marker preparation.")
            return False
        path = self.project_path if not force_new else None
        if path is None:
            identity = self.analysis.get("timeline_identity")
            folder = get_project_folder(identity) or self._choose_project_folder()
            if folder is None:
                return False
            project_name = (self.snapshot or {}).get("project_name") or ""
            timeline_name = self.analysis.get("timeline_name") or ""
            name = " - ".join(part for part in (project_name, timeline_name) if part) or "markers"
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(". ") or "markers"
            initial = folder / (Path(self.project_path).name if self.project_path else f"{name}.vispamp")
            selected, _kind = QFileDialog.getSaveFileName(self, "Save VISPA MP project", str(initial), PROJECT_FILTER)
            if not selected:
                return False
            path = Path(selected)
            if path.suffix.lower() != ".vispamp":
                path = path.with_name(path.name + ".vispamp")
        return self.save_project_file(path)

    def save_project_file(self, path):
        """Save accepted marker choices, even when Resolve is currently closed."""
        if self.worker is not None:
            self.status.setText("Wait for the current operation before saving the project.")
            return False
        try:
            save_project(path, self.snapshot, self.analysis, self.proposals, self.settings(), self._project_view())
        except (OSError, ValueError) as error:
            self.status.setText("The project was not saved.")
            self._project_message.tell(self, "Save project", "The project was not saved.", str(error))
            return False
        self.project_path = Path(path)
        self._project_dirty = False
        self._sync_project_title()
        self.status.setText(f"Project saved: {self.project_path.name}. Markers in Resolve were not changed.")
        return True

    def _confirm_project_discard(self):
        if not self._project_dirty:
            return True
        choice = self._project_message.save_changes(self)
        if choice == "save":
            return self._choose_save_project()
        return choice == "discard"

    def _open_project(self):
        if self.worker is not None:
            return
        identity = (self.analysis or self.snapshot or {}).get("timeline_identity")
        folder = get_project_folder(identity)
        initial = self.project_path or folder or Path.home()
        path, _kind = QFileDialog.getOpenFileName(self, "Open VISPA MP project", str(initial), PROJECT_FILTER)
        if path:
            self.open_project_file(path)

    def open_project_file(self, path):
        if self.worker is not None or not self._confirm_project_discard():
            return
        self.status.setText("Opening project and checking the timeline in Resolve…")
        cache = self._cache_dir()

        def work(_progress):
            try:
                project = load_project(path, cache)
            except (OSError, ValueError) as error:
                return {"error": str(error), "heading": "This VISPA MP project cannot be opened."}
            instructions = _target_instructions(project)
            client = self.client
            if client is not None and getattr(client, "proc", None) is not None and client.proc.poll() is not None:
                client = None
            owned = client is None
            try:
                client = client if client is not None else open_client()
                if getattr(client, "mailbox", False) and not link_running():
                    raise RuntimeError("The VISPA_MP script is not connected.")
                live = normalize(client.read())
            except Exception as error:
                _close_unclaimed_client(client, owned)
                return {"error": instructions + "\n\n" + str(error),
                        "heading": "Connect the matching project in DaVinci Resolve first."}
            expected = normalize_identity(project["analysis"].get("timeline_identity"))
            if expected != normalize_identity(live.get("timeline_identity")):
                _close_unclaimed_client(client, owned)
                return {"error": instructions,
                        "heading": "The open Resolve project or timeline does not match this file."}
            if _edit(live) != _edit(project["snapshot"]):
                _close_unclaimed_client(client, owned)
                return {"error": instructions + "\n\nThe edit has changed since this preparation was saved. "
                        "Restore the matching edit before opening this file.",
                        "heading": "The timeline edit no longer matches the saved preparation."}
            return {"project": project, "client": client, "snapshot": live, "owned_client": owned}

        def done(result):
            if "error" in result:
                self.status.setText(result["heading"])
                self._project_message.tell(self, "Open project", result["heading"], result["error"])
                return
            try:
                self._validate_project_controls(result["project"])
            except ValueError as error:
                _close_unclaimed_client(result["client"], result["owned_client"])
                self.status.setText("This VISPA MP project cannot be opened.")
                self._project_message.tell(self, "Open project", "This VISPA MP project cannot be opened.", str(error))
                return
            self._restore_project(result["project"], result["snapshot"], result["client"], path)

        self._start(work, done)

    def _validate_project_controls(self, project):
        """Reject unusable settings before changing even one existing control."""
        for key, value in project["settings"].items():
            widget = self.widgets.get(key)
            if isinstance(widget, QComboBox):
                valid = widget.findData(value) >= 0
            elif hasattr(widget, "minimum") and hasattr(widget, "maximum"):
                scaled = value * self._project_slider_scales.get(key, 1)
                valid = widget.minimum() <= scaled <= widget.maximum()
                if isinstance(widget, QSpinBox):
                    valid = valid and int(value) == value
            else:
                continue
            if not valid:
                raise ValueError(f'The saved setting "{key}" is outside the supported range. Your current preparation was kept.')

    def _restore_project(self, project, snapshot, client, path):
        """Install the saved choices directly: recomputing would erase the review."""
        view = project["view"]
        self._restoring_project = True
        self._ready = False
        try:
            self._stored_settings = {**load(), **project["settings"]}
            for key, value in self._stored_settings.items():
                if key in self.widgets:
                    self.set_setting(key, value)
            self.page_format = view.get("page_format", "A5")
            self.orientation = view.get("orientation", "portrait")
            self.custom_width = int(view.get("custom_width", 148))
            self.custom_height = int(view.get("custom_height", 210))
            for key, default in PREVIEW_DEFAULTS.items():
                setattr(self, key, view.get(key, default))
            self.format_buttons[self.page_format].setChecked(True)
            self.orientation_buttons[self.orientation].setChecked(True)
            self._sync_size_fields()
            self._set_mode(view.get("mode", "strip"))
            self.view_filter = view.get("view_filter", "all")
            self.filter_buttons[self.view_filter].setChecked(True)
            self.client, self.snapshot = client, snapshot
            self.analysis = deepcopy(project["analysis"])
            self.analysis["manual_frames"] = [int(marker["frame"]) for marker in snapshot.get("markers") or []
                                              if not marker.get("automatic")]
            self.analysis["timeline_name"] = snapshot.get("timeline_name") or self.analysis.get("timeline_name") or ""
            self.proposals = deepcopy(project["proposals"])
            self._excluded_frames = set(view.get("excluded_frames") or [])
            self._page_layout = deepcopy(view.get("page_layout"))
            self.rule_warnings = list(view.get("rule_warnings") or [])
            self._preview = None
            self._suggestions_open = False
            self._flash = None
            self.open_pages = set(view.get("open_pages") or [])
            self.selected_frame = view.get("selected_frame")
            self.selected_manual = bool(view.get("selected_manual"))
            self.selected_page_id = view.get("selected_page_id")
            self._sync_preview_fields()
            self._fill()
            self.set_suggestions_height(view.get("suggestions_height", 200))
            if view.get("playhead_frame") is not None:
                self._move_playhead(view["playhead_frame"])
            self.set_review_cameras(view.get("cameras"))
            self.tracks_label.setText(f"{describe_rate(snapshot)} · Video 1 · Audio 1")
            self._sync_resolve()
            self.project_path = Path(path)
            self._project_dirty = False
            self._sync_project_title()
        finally:
            self._ready = True
            self._restoring_project = False
        self.save_settings()
        self.status.setText(f"Project loaded: {self.project_path.name}. Your marker choices are restored; nothing was placed in Resolve.")

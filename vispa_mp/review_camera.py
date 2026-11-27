"""Independent view positions, captured before a pane becomes hidden."""

from copy import deepcopy

from PySide6.QtCore import QPointF, QTimer


class ReviewCameraMixin:
    def _init_review_cameras(self, base_image_width):
        self._camera_image_width = base_image_width
        self._review_cameras = {"strip": None, "board": None}
        self._review_camera_context = None
        self._review_camera_source = None
        self._review_camera_edit = None
        self._camera_pending = {"strip": True, "board": True}
        self._applying_camera = False
        self._camera_timer = QTimer(self)
        self._camera_timer.setSingleShot(True)
        self._camera_timer.timeout.connect(lambda: self._apply_review_camera(self.mode))

    def _camera_context(self):
        return (self.view_filter, None if self.view_filter == "starts" else self.selected_page_id,
                len(self._view_items() or []))

    def _sync_review_camera_context(self):
        context = self._camera_context()
        source_changed = self.analysis is not self._review_camera_source
        if context != self._review_camera_context or source_changed:
            self._camera_timer.stop()
            self._review_camera_context = context
            self._review_camera_source = self.analysis
            if not source_changed and self._preserving_review_camera():
                return
            self._review_cameras = {"strip": None, "board": None}
            self._camera_pending = {"strip": True, "board": True}
            self._camera_timer.start(0)

    def _camera_page_key(self):
        """Identify the same editorial page across replacement of its start image."""
        if self.view_filter == "starts":
            return ("starts",)
        if self.selected_page_id is None:
            return None
        if self._page_layout is not None:
            return ("manual", self.selected_page_id)
        proposal = self._proposal(self.selected_page_id)
        origin = proposal.get("origin_frame", self.selected_page_id) if proposal else self.selected_page_id
        return ("automatic", int(origin))

    def _begin_review_camera_edit(self, *, allow_filter_change=False):
        """Keep both view cameras until a local edit has rebuilt the current page.

        A nested edit shares its outer transaction. Filters, other pages and
        another analysis keep their normal fit behavior.
        """
        if (self._review_camera_edit is not None or self.analysis is None
                or getattr(self, "worker", None) is not None
                or getattr(self, "_learning_job_busy", False) or not self._view_items()):
            return None
        self._sync_review_camera_context()
        self._remember_review_camera(self.mode)
        token = {"source": self.analysis, "filter": self.view_filter,
                 "page": self._camera_page_key(), "page_id": self.selected_page_id,
                 "cameras": deepcopy(self._review_cameras), "allow_filter_change": allow_filter_change}
        self._review_camera_edit = token
        return token

    def _preserving_review_camera(self):
        token = self._review_camera_edit
        if token is None:
            return False
        same_filter = (token["filter"] == self.view_filter
                       or token["allow_filter_change"] and token["filter"] in ("core", "starts")
                       and self.view_filter == "all")
        return bool(token is not None and token["source"] is self.analysis
                    and same_filter
                    and (token["page_id"] == self.selected_page_id
                         or token["page"] == self._camera_page_key()))

    def _finish_review_camera_edit(self, token):
        if token is None or token is not self._review_camera_edit:
            return
        preserve = self._preserving_review_camera()
        self._review_camera_edit = None
        if not preserve:
            self._sync_review_camera_context()
            return
        self._camera_timer.stop()
        self._review_camera_context = self._camera_context()
        self._review_camera_source = self.analysis
        self._review_cameras = deepcopy(token["cameras"])
        self._camera_pending = {"strip": True, "board": True}
        self._apply_review_camera(self.mode)
        if self._camera_pending[self.mode]:
            self._camera_timer.start(0)

    def _queue_review_camera(self, mode):
        if self._applying_camera:
            return
        self._camera_pending[mode] = True
        if mode == self.mode:
            self._camera_timer.start(0)

    def _capture_review_camera(self, mode):
        if mode == "strip":
            view = self.thumb_area
            if not view.isVisible() or not self._thumb_items or view._content.isEmpty():
                return None
            centre = view.mapToScene(view.viewport().rect().center())
            return {"zoom": self._thumb_zoom,
                    "center": [centre.x() / view._content.width(), centre.y() / view._content.height()],
                    "columns": self._thumb_columns or 1}
        if not self.board.isVisible() or not self.board.items:
            return None
        page = self.board._view_rect()
        centre = self.board.rect().center()
        return {"zoom": self.board.zoom,
                "center": [(centre.x() - page.x()) / max(1, page.width()),
                           (centre.y() - page.y()) / max(1, page.height())]}

    def _remember_review_camera(self, mode, dirty=False):
        if self._applying_camera:
            return
        if self._camera_pending[mode]:
            self._apply_review_camera(mode)
        state = self._capture_review_camera(mode)
        if state is not None:
            self._review_cameras[mode] = state
            if dirty:
                self._mark_project_dirty()

    def _prepare_camera_interaction(self, mode):
        self._camera_timer.stop()
        if self._camera_pending[mode]:
            self._apply_review_camera(mode)

    def _apply_review_camera(self, mode):
        if self._applying_camera or mode != self.mode or not self._view_items():
            return
        widget = self.thumb_area if mode == "strip" else self.board
        if not widget.isVisible():
            return  # Show/Resize will try again, with the actual viewport dimensions.
        self._applying_camera = True
        state = self._review_cameras[mode]
        try:
            if mode == "strip":
                if state is not None:
                    self._thumb_columns = min(state["columns"], max(1, len(self._thumb_items or [])))
                    self._thumb_grid_context = self._camera_context()
                    self._thumb_zoom = state["zoom"]
                else:
                    self._thumb_zoom = None
                    self._thumb_grid_context = None
                self._place_thumbs()
                scale = self._thumb_size(len(self._thumb_items or []))[0] / self._camera_image_width
                widget.set_scale(scale)
                if state is not None:
                    x, y = state["center"]
                    widget.centerOn(x * widget._content.width(), y * widget._content.height())
            else:
                self.board.zoom = state["zoom"] if state is not None else 1.0
                self.board.offset = QPointF(0, 0)
                if state is not None:
                    page = self.board._view_rect()
                    centre = self.board.rect().center()
                    x, y = state["center"]
                    self.board.offset = QPointF(centre.x() - page.x() - x * page.width(),
                                                centre.y() - page.y() - y * page.height())
                self.board.update()
            self._camera_pending[mode] = False
            self._review_cameras[mode] = self._capture_review_camera(mode)
        finally:
            self._applying_camera = False

    def get_review_cameras(self):
        self._sync_review_camera_context()
        self._remember_review_camera(self.mode)
        return deepcopy(self._review_cameras)

    def set_review_cameras(self, cameras):
        """Old projects omit cameras; reset both views instead of borrowing another review."""
        self._camera_timer.stop()
        self._review_cameras = {mode: deepcopy((cameras or {}).get(mode)) for mode in ("strip", "board")}
        self._review_camera_context = self._camera_context()
        self._review_camera_source = self.analysis
        self._camera_pending = {"strip": True, "board": True}
        self._camera_timer.start(0)

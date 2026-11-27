"""A shared selection for the Strip and Board review surfaces."""

from vispa_mp.markers import CORE, NAMES, PAGE
from vispa_mp.review_history import review_edit


class ReviewMultiSelectionMixin:
    def _select_single_frame(self, frame, manual=False):
        self._range_anchor_key = None if frame is None else (int(frame), bool(manual))
        self._selected_keys = set() if frame is None else {self._range_anchor_key}

    def _reconcile_frame_selection(self, previous_primary):
        known = {(int(item.get("frame") if item["manual"] else item["proposal"]["frame"]),
                  bool(item["manual"])) for page in self.pages for item in page["items"]}
        self._selected_keys.intersection_update(known)
        primary = (self.selected_frame, bool(self.selected_manual))
        if self._selected_keys and primary not in self._selected_keys:
            anchor = self.selected_frame if self.selected_frame is not None else 0
            nearest = min(self._selected_keys, key=lambda value: (abs(value[0] - anchor), value))
            self.selected_page_id, self.selected_frame, self.selected_manual = self._find(*nearest)
            self._move_playhead(self.selected_frame)
        if self.selected_frame is not None and not self._selected_keys and previous_primary not in known:
            self._selected_keys.add(primary)
        if getattr(self, "_range_anchor_key", None) not in known:
            self._range_anchor_key = ((self.selected_frame, bool(self.selected_manual))
                                      if self.selected_frame is not None else None)

    def _toggle_frame_selection(self, frame, manual):
        if self.worker is not None or getattr(self, "_learning_job_busy", False):
            return
        found = self._find(frame, manual)
        if found is None:
            return
        key = (int(frame), bool(manual))
        self._range_anchor_key = key
        if key in self._selected_keys:
            self._selected_keys.remove(key)
            if self._selected_keys:
                key = min(self._selected_keys, key=lambda value: (abs(value[0] - int(frame)), value))
                found = self._find(*key)
        else:
            self._selected_keys.add(key)
        self._refresh_frame_selection(found)

    def _range_selection_keys(self, scope="review"):
        """Source-time order, independent of editorial page or image ordering."""
        keys = set()
        for page in self.pages:
            for item in page["items"]:
                manual = bool(item["manual"])
                if scope == "review":
                    color = None if manual else item["proposal"]["color"]
                    if self.view_filter == "core" and color not in (PAGE, CORE):
                        continue
                    if self.view_filter == "starts" and color != PAGE:
                        continue
                frame = item["frame"] if manual else item["proposal"]["frame"]
                keys.add((int(frame), manual))
        return sorted(keys)

    def _select_frame_range(self, frame, manual, additive=False, scope="review"):
        if self.worker is not None or getattr(self, "_learning_job_busy", False):
            return
        found = self._find(frame, manual)
        if found is None:
            return
        target = (int(frame), bool(manual))
        keys = self._range_selection_keys(scope)
        if target not in keys:
            return
        anchor = getattr(self, "_range_anchor_key", None)
        if anchor not in keys:
            anchor = self._range_anchor_key = target
        first, last = sorted((keys.index(anchor), keys.index(target)))
        selected = set(keys[first:last + 1])
        if additive:
            self._selected_keys.update(selected)
        else:
            self._selected_keys = selected
        self._refresh_frame_selection(found)

    def _refresh_frame_selection(self, found):
        self.selected_page_id, self.selected_frame, self.selected_manual = found
        self._preview = None
        self._suggestions_open = bool(len(self._selected_keys) == 1 and self.suggestions_auto_open
                                      and not self.selected_manual)
        self._move_playhead(self.selected_frame)
        self._paint_selection()
        self._refresh_center()
        self._sync_swatches()
        self.status.setText(self.selection_count.text())

    def _selected_proposals(self):
        return [proposal for proposal in self.proposals
                if (int(proposal["frame"]), False) in self._selected_keys]

    @review_edit("change image roles")
    def _set_proposal_colors(self, frames, color):
        if self.worker is not None or getattr(self, "_learning_job_busy", False) or color not in NAMES:
            return
        numbers = {int(frame) for frame in frames}
        changed = 0
        for proposal in self.proposals:
            if int(proposal["frame"]) not in numbers or proposal["color"] == color:
                continue
            proposal["color"] = color
            proposal["name"] = NAMES[color]
            proposal["note"] = f"{NAMES[color]}, chosen manually"
            proposal["user_role"] = True
            changed += 1
        if changed:
            self._mark_project_dirty()
            self._fill()
            if len(numbers) > 1:
                self.status.setText(f"{changed} image roles changed to {NAMES[color]}.")

    def _delete_selected_marker_proposals(self):
        self._delete_marker_proposals([proposal["frame"] for proposal in self._selected_proposals()])

    @review_edit("delete marker proposals")
    def _delete_marker_proposals(self, frames):
        if self.worker is not None or getattr(self, "_learning_job_busy", False):
            return
        numbers = {int(frame) for frame in frames}
        removed = [proposal for proposal in self.proposals if int(proposal["frame"]) in numbers]
        if not removed:
            return
        numbers = {int(proposal["frame"]) for proposal in removed}
        anchor = self.selected_frame if self.selected_frame is not None else min(numbers)
        for proposal in removed:
            number = int(proposal["frame"])
            self._excluded_frames.update((number, int(proposal.get("origin_frame", number))))
        self.proposals = [proposal for proposal in self.proposals if int(proposal["frame"]) not in numbers]
        self._selected_keys.difference_update((number, False) for number in numbers)
        self._preview = self._flash = None
        if not self.proposals:
            self._suggestions_open = False
        if not self.selected_manual and self.selected_frame in numbers:
            remaining = sorted(self._selected_keys, key=lambda value: (abs(value[0] - anchor), value))
            if remaining:
                self.selected_frame, self.selected_manual = remaining[0]
            else:
                nearest = min(self.proposals,
                              key=lambda proposal: (abs(int(proposal["frame"]) - anchor), int(proposal["frame"])),
                              default=None)
                self.selected_frame = int(nearest["frame"]) if nearest else None
                self.selected_manual = False
                self._select_single_frame(self.selected_frame)
        self._fill()
        if self.selected_frame is not None:
            self._move_playhead(self.selected_frame)
        self._mark_project_dirty()
        detail = ("Resolve is updated when you place markers again." if self.proposals else
                  "No proposals remain. Existing Resolve markers are unchanged.")
        lead = (f"Marker proposal removed: {self.timecode_of(next(iter(numbers)))}."
                if len(numbers) == 1 else f"{len(numbers)} marker proposals removed.")
        self.status.setText(f"{lead} {detail}")

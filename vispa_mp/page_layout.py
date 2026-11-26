"""Reading order for the local page review, independent of source timecodes.

An absent layout (``None``) keeps automatic chronological grouping. A manual
layout contains stable page IDs and proposal frame IDs only; it never changes
marker positions, roles, or markers placed by hand in Resolve.
"""

from bisect import bisect_left

from vispa_mp.markers import CORE, PAGE


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _copy_layout(layout, allow_duplicate_frames=False):
    if not isinstance(layout, list):
        raise ValueError("The manual page layout must be a list.")
    copied, page_ids, frames = [], set(), set()
    for page in layout:
        if (not isinstance(page, dict) or not _integer(page.get("id"))
                or not isinstance(page.get("frames"), list)):
            raise ValueError("A manual page cannot be read.")
        if page["id"] in page_ids:
            raise ValueError("Manual page IDs must be unique.")
        page_ids.add(page["id"])
        values = []
        for frame in page["frames"]:
            if not _integer(frame):
                raise ValueError("A manual page contains an invalid frame.")
            if frame in frames and not allow_duplicate_frames:
                raise ValueError("An image cannot appear in two layout positions.")
            frames.add(frame)
            values.append(frame)
        copied.append({"id": page["id"], "frames": values})
    return copied


def capture_layout(pages):
    """Capture the current page order, leaving hand-placed markers outside it."""
    layout, seen = [], set()
    for page in pages:
        frames = []
        for item in page["items"]:
            if item.get("manual"):
                continue
            frame = int(item["proposal"]["frame"])
            if frame not in seen:
                frames.append(frame)
                seen.add(frame)
        if frames:
            layout.append({"id": int(page["id"]), "frames": frames})
    return _copy_layout(layout)


def _chronological_layout(proposals):
    """Build a first layout when no previous page still has an image."""
    result, current, seen = [], None, set()
    has_core = False
    for proposal in sorted(proposals, key=lambda item: int(item["frame"])):
        frame = int(proposal["frame"])
        if frame in seen:
            continue
        seen.add(frame)
        if current is None or proposal.get("color") == PAGE and has_core:
            current = {"id": frame, "frames": []}
            result.append(current)
            has_core = False
        elif proposal.get("color") == PAGE:
            # Leading Extras belong to the first Core page, rather than making
            # an otherwise empty page before its start image.
            current["id"] = frame
        current["frames"].append(frame)
        has_core = has_core or proposal.get("color") in (PAGE, CORE)
    return result


def reconcile_layout(layout, proposals):
    """Keep manual order after recalculation, removing stale/duplicate frames.

    New candidates join the page of their closest preceding source image, or
    the closest following image when there is no predecessor. They are inserted
    beside that anchor. Existing relative reading order and page IDs stay fixed;
    a newly suggested green marker does not override the user's page grouping.
    """
    if layout is None:
        return None
    proposals = list(proposals)
    allowed = {int(item["frame"]) for item in proposals}
    pages, seen = [], set()
    for page in _copy_layout(layout, allow_duplicate_frames=True):
        frames = []
        for frame in page["frames"]:
            if frame in allowed and frame not in seen:
                seen.add(frame)
                frames.append(frame)
        if frames:
            pages.append({"id": page["id"], "frames": frames})
    if not pages:
        return _chronological_layout(proposals)
    for frame in sorted(allowed - seen):
        # Include previously inserted candidates as anchors so a new sequence
        # stays in source order without disturbing images already arranged.
        ordered = sorted(seen)
        index = bisect_left(ordered, frame)
        before = index == 0
        anchor = ordered[0] if before else ordered[index - 1]
        target = next(page for page in pages if anchor in page["frames"])
        position = target["frames"].index(anchor) + (0 if before else 1)
        target["frames"].insert(position, frame)
        seen.add(frame)
    return pages


def move_frame(layout, frame, target_page_id, before_frame=None):
    """Move one proposal to a stable page ID; ``None`` appends to its end.

    The target is resolved before removing an empty source page, so moving a
    lone first-page image into a later page cannot shift the destination. Invalid
    targets raise ``ValueError`` and leave every caller-owned structure intact.
    """
    if not _integer(frame) or not _integer(target_page_id):
        raise ValueError("A page move needs integer image and page IDs.")
    if before_frame is not None and not _integer(before_frame):
        raise ValueError("The insertion image must be an integer frame ID.")
    pages = _copy_layout(layout)
    source = next((page for page in pages if frame in page["frames"]), None)
    target = next((page for page in pages if page["id"] == target_page_id), None)
    if source is None or target is None:
        raise ValueError("The image or destination page is no longer available.")
    if before_frame is not None and before_frame not in target["frames"]:
        raise ValueError("The insertion image does not belong to the destination page.")
    if before_frame == frame:
        return pages
    source["frames"].remove(frame)
    position = len(target["frames"]) if before_frame is None else target["frames"].index(before_frame)
    target["frames"].insert(position, frame)
    return [page for page in pages if page["frames"]]

"""Marker colours the Cue exporter already understands.

Green becomes a page start, blue a page image that can carry a line,
cyan an extra. Yellow and orange are already the optional page.
"""

PAGE = "Green"
CORE = "Blue"
EXTRA = "Cyan"
AUTOMATIC = "vispa-mp"

NAMES = {PAGE: "Page", CORE: "Core", EXTRA: "Extra"}


def is_automatic(custom_data):
    return str(custom_data or "").startswith(AUTOMATIC)


def plan_apply(existing, proposals, start=None, end=None):
    """Which automatic markers to replace, and which proposals a manual marker blocks.

    ``existing`` items are ``frame, automatic``. ``start`` is inclusive and ``end``
    exclusive; both None covers the whole timeline. Manual markers are never deleted.
    """
    def inside(frame):
        if start is None or end is None:
            return True
        return start <= int(frame) < end

    delete = [int(marker["frame"]) for marker in existing if marker.get("automatic") and inside(marker["frame"])]
    occupied = {int(marker["frame"]) for marker in existing if not marker.get("automatic")}
    add, skipped = [], []
    for proposal in proposals:
        frame = int(proposal["frame"])
        if not inside(frame):
            continue
        if frame in occupied:
            skipped.append(frame)
            continue
        add.append(proposal)
    return delete, add, skipped


def cue_warning(track_names):
    """Legacy helper name: MP needs Video 1, regardless of its track name."""
    if not list(track_names or []):
        return "Video 1 was not found."
    return ""

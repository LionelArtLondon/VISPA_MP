"""Marker colours the Cue exporter already understands.

Green becomes a page start, blue a page image that can carry a line,
cyan an extra. Yellow and orange are already the optional page.
"""

PAGE = "Green"
CORE = "Blue"
EXTRA = "Cyan"
AUTOMATIC = "vispa-mp"

NAMES = {PAGE: "Page", CORE: "Body", EXTRA: "Extra"}


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
    """Video 1 stays the analysed track. The exporter looks for CUE_SOURCE by name."""
    names = list(track_names or [])
    if not names:
        return "Video 1 was not found."
    cue = [index for index, name in enumerate(names, 1) if str(name or "").strip().lower() == "cue_source"]
    if not cue:
        return ("No track is named CUE_SOURCE. Analysis uses video 1. "
                "The Cue exporter looks for a track with that name.")
    if cue != [1]:
        listed = ", ".join(str(index) for index in cue)
        return (f"CUE_SOURCE is not video 1 (track {listed}). "
                "Analysis stays on video 1.")
    return ""

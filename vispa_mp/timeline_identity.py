"""Stable Resolve identities used to bind a review to its original timeline."""


def normalize_identity(value):
    """A complete pair of opaque Resolve IDs, or None when it cannot be trusted."""
    if not isinstance(value, dict):
        return None
    identity = {}
    for key in ("project_id", "timeline_id"):
        part = value.get(key)
        if not isinstance(part, str) or not part.strip():
            return None
        identity[key] = part
    return identity


def read_identity(timeline, project):
    """Read IDs from the captured API objects, without falling back to names."""
    try:
        identity = {"project_id": project.GetUniqueId(), "timeline_id": timeline.GetUniqueId()}
    except Exception:
        return None
    return normalize_identity(identity)

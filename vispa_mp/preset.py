"""Tunable thresholds. A saved JSON overrides these defaults one key at a time."""

from json import loads
from pathlib import Path

DEFAULTS = {
    "end_fraction": 0.30,
    "sharpness_floor": 0.5,
    "sharpness_ratio": 0.35,
    "motion_blur_max": 0.50,
    "hold_ratio": 1.15,
    # Gaps are in seconds, so a 50 fps timeline keeps the spacing tuned at 24 fps.
    "min_marker_seconds": 0.33,
    "expression_weight": 0.15,
    "speech_min_silence_ms": 200,
    "speech_min_duration_ms": 250,
    "speech_threshold": 0.50,
    "speech_pad_ms": 80,
    "candidates_per_line": 4,
    "max_tagged_per_shot": 16,
    "spread_tagged": 6,
    "require_open_mouth": True,
    "mouth_fallback": "sharp",
    "mouth_min": 0.20,
    "face_min": 0.15,
    "behind_min": 0.50,
    "keep_second_mouth": False,
    "second_mouth_ratio": 0.60,
    "action_max_seconds": 2.5,
    "action_motion": 12.0,
    "action_extras": 3,
    "duplicate_diff": 6.0,
    "scene_grey": 30.0,
    "scene_colour": 0.35,
    "group_min": 0.35,
    "min_green_seconds": 2.0,
    "compression": 0.35,
    # The page targets are for an episode of this length. A shorter In/Out range
    # gets its share: 4 minutes of a 24-minute episode aim at a sixth of the pages.
    # 0 applies the targets to whatever is analyzed.
    "episode_minutes": 24,
    "target_pages_min": 45,
    "target_pages_max": 60,
    "core_page_min": 2,
    "core_page_max": 6,
    "total_page_min": 3,
    "total_page_max": 8,
    "skip_marked_shots": True,
    "use_in_out": True,
}

ROOT = Path(__file__).resolve().parents[1]
PRESET_PATH = ROOT / "presets" / "default.json"


def setting(settings, key):
    if settings is not None and key in settings and settings[key] is not None:
        return settings[key]
    return DEFAULTS[key]


def load(path=None):
    data = dict(DEFAULTS)
    file = Path(path) if path else PRESET_PATH
    if file.is_file():
        stored = loads(file.read_text(encoding="utf-8"))
        if not isinstance(stored, dict):
            raise ValueError("The preset must be a JSON object.")
        data.update(stored)
    return data


# What the user changed, kept between sessions. default.json is never rewritten.
USER_PATH = ROOT / "presets" / "user.json"
VIEW_DEFAULTS = {"page_format": "A5", "orientation": "portrait", "custom_width": 148, "custom_height": 210}


def _same_kind(value, reference):
    if isinstance(reference, bool):
        return isinstance(value, bool)
    if isinstance(reference, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, type(reference))


def _read_user(path):
    try:
        stored = loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # missing or damaged: start from the shipped preset
    return stored if isinstance(stored, dict) else {}


def load_user(path=None):
    """(settings, view): the shipped preset with the user's own values on top.

    An unknown key or a value of the wrong kind is skipped, never fatal.
    """
    settings = load()
    view = dict(VIEW_DEFAULTS)
    for key, value in _read_user(path or USER_PATH).items():
        if key in DEFAULTS and _same_kind(value, DEFAULTS[key]):
            settings[key] = value
        elif key in VIEW_DEFAULTS and _same_kind(value, VIEW_DEFAULTS[key]):
            view[key] = value
    return settings, view


SAVED_DIR = ROOT / "presets" / "saved"
FILE_KIND = "vispa-mp-settings"


def export_settings(settings, path):
    """A settings file to load later: every marker setting, the page format left out."""
    import json
    values = {key: settings[key] for key in DEFAULTS if key in (settings or {})}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"kind": FILE_KIND, "version": 1, "settings": values},
                                 indent=2, sort_keys=True) + "\n", encoding="utf-8")


def import_settings(path):
    """The usable settings of a saved file. Unknown keys and wrong kinds are left out.

    Raises ValueError when the file is not a VISPA MP settings file.
    """
    try:
        stored = loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"This file cannot be read: {error}") from error
    if isinstance(stored, dict) and stored.get("kind") == FILE_KIND:
        stored = stored.get("settings")
    if not isinstance(stored, dict):
        raise ValueError("This is not a VISPA MP settings file.")
    values = {key: value for key, value in stored.items()
              if key in DEFAULTS and _same_kind(value, DEFAULTS[key])}
    if not values:
        raise ValueError("This file holds no VISPA MP setting.")
    return values


def save_user(settings, view, path=None):
    """Write only what differs from the shipped preset. Nothing left: the file goes."""
    import json
    import os
    shipped = load()
    changed = {}
    for key, value in (settings or {}).items():
        if key in DEFAULTS and value != shipped.get(key):
            changed[key] = value
    for key, value in (view or {}).items():
        if key in VIEW_DEFAULTS and value != VIEW_DEFAULTS[key]:
            changed[key] = value
    target = Path(path or USER_PATH)
    if not changed:
        try:
            target.unlink()
        except OSError:
            pass
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    partial.write_text(json.dumps(changed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(partial, target)

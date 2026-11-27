"""Tunable thresholds. A saved JSON overrides these defaults one key at a time."""

from json import loads
import math
from pathlib import Path

from vispa_mp.marker_budget import BUDGET_DEFAULTS, valid_budget_value

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
    "split_long_shots": True,
    "long_shot_seconds": 4.3,
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
    "min_extra_seconds": 0.12,
    "action_structure": 0.35,
    "duplicate_diff": 6.0,
    "scene_grey": 30.0,
    "scene_colour": 0.35,
    "group_min": 0.35,
    "min_green_seconds": 2.0,
    "compression": 0.5,
    # The page targets are for an episode of this length. A shorter In/Out range
    # gets its share: 4 minutes of a 24-minute episode aim at a sixth of the pages.
    # 0 applies the targets to whatever is analyzed.
    "episode_minutes": 24,
    "target_pages_min": 45,
    "target_pages_max": 60,
    "core_page_min": 2,
    "core_page_max": 6,
    # A soft average for Page + Core images. Zero keeps the compression slider.
    "core_page_target": 0.0,
    "total_page_min": 3,
    "total_page_max": 8,
    **BUDGET_DEFAULTS,
    "skip_marked_shots": True,
    "use_in_out": True,
    "learning_profile": "",
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
FRAME_FORMATS = ("Source", "16:9", "4:3", "3:2", "1:1", "2:3", "9:16", "Custom")
PREVIEW_QUALITIES = ("Low", "Medium", "High")
PREVIEW_DEFAULTS = {"show_board_labels": True, "frame_format": "Source",
                    "frame_custom_width": 16.0, "frame_custom_height": 9.0,
                    "preview_quality": "Medium"}
VIEW_DEFAULTS = {"page_format": "A5", "orientation": "portrait", "custom_width": 148, "custom_height": 210,
                 **PREVIEW_DEFAULTS, "suggestions_auto_open": False, "suggestions_detached": False,
                 "suggestions_rows": 0, "pages_panel_width": 280, "review_tools_width": 280}


def _valid_preview_value(key, value):
    if key in ("pages_panel_width", "review_tools_width"):
        return isinstance(value, int) and not isinstance(value, bool) and 160 <= value <= 2000
    if key == "preview_quality":
        return isinstance(value, str) and value in PREVIEW_QUALITIES
    if key == "suggestions_rows":
        return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 6
    if key in ("show_board_labels", "suggestions_auto_open", "suggestions_detached"):
        return isinstance(value, bool)
    if key == "frame_format":
        return isinstance(value, str) and value in FRAME_FORMATS
    if key in ("frame_custom_width", "frame_custom_height"):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        try:
            return math.isfinite(value) and 0.1 <= value <= 100
        except OverflowError:
            return False
    return True


def _same_kind(value, reference):
    if isinstance(reference, bool):
        return isinstance(value, bool)
    if isinstance(reference, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, type(reference))


def valid_long_shot_value(key, value):
    """Keep the decomposition switch and duration safe in portable settings."""
    if key == "split_long_shots":
        return isinstance(value, bool)
    if key == "long_shot_seconds":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        try:
            return math.isfinite(value) and 1 <= value <= 120
        except OverflowError:
            return False
    return True


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
        if (key in DEFAULTS and _same_kind(value, DEFAULTS[key])
                and valid_budget_value(key, value) and valid_long_shot_value(key, value)):
            settings[key] = value
        elif (key in VIEW_DEFAULTS and _same_kind(value, VIEW_DEFAULTS[key])
              and _valid_preview_value(key, value)):
            view[key] = value
    return settings, view


SAVED_DIR = ROOT / "presets" / "saved"
FILE_KIND = "vispa-mp-settings"


def export_settings(settings, path):
    """A settings file to load later: every marker setting, the page format left out."""
    import json
    values = {key: settings[key] for key in DEFAULTS
              if key in (settings or {}) and valid_budget_value(key, settings[key])
              and valid_long_shot_value(key, settings[key])}
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
              if key in DEFAULTS and _same_kind(value, DEFAULTS[key])
              and valid_budget_value(key, value) and valid_long_shot_value(key, value)}
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
        if (key in DEFAULTS and value != shipped.get(key) and valid_budget_value(key, value)
                and valid_long_shot_value(key, value)):
            changed[key] = value
    for key, value in (view or {}).items():
        if key in VIEW_DEFAULTS and value != VIEW_DEFAULTS[key] and _valid_preview_value(key, value):
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

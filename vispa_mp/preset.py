"""Tunable thresholds. A saved JSON overrides these defaults one key at a time."""

from json import loads
from pathlib import Path

DEFAULTS = {
    "end_fraction": 0.30,
    "sharpness_floor": 0.5,
    "sharpness_ratio": 0.35,
    "motion_blur_max": 0.50,
    "hold_ratio": 1.15,
    "min_marker_frames": 8,
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
    "min_green_frames": 48,
    "compression": 0.35,
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

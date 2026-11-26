"""An explicitly chosen working folder for each Resolve project.

Resolve does not expose the path of its last exported .drp file. A folder is
remembered only after the user chooses it; media and library paths are not used
as guesses for the project-file location.
"""

import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCATION_PATH = ROOT / "presets" / "project_locations.json"


def _project_id(identity):
    if not isinstance(identity, dict):
        return None
    project_id = identity.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        return None
    return project_id


def _locations():
    try:
        stored = json.loads(Path(LOCATION_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(stored, dict):
        return {}
    return {key: value for key, value in stored.items()
            if isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip()}


def get_project_folder(identity):
    """The chosen folder if it still exists, otherwise None. Never guesses one."""
    project_id = _project_id(identity)
    folder = _locations().get(project_id) if project_id is not None else None
    if folder is None:
        return None
    try:
        path = Path(folder)
        return path if path.is_absolute() and path.is_dir() else None
    except (OSError, ValueError):
        return None


def set_project_folder(identity, folder):
    """Remember a user-selected existing folder, scoped to the Resolve project ID."""
    project_id = _project_id(identity)
    if project_id is None:
        raise ValueError("A verified Resolve project identity is required to remember its folder.")
    try:
        directory = Path(folder).expanduser().resolve()
    except (TypeError, ValueError, OSError) as error:
        raise ValueError("Choose an existing folder for this Resolve project.") from error
    if not directory.is_dir():
        raise ValueError("Choose an existing folder for this Resolve project.")
    stored = _locations()
    stored[project_id] = str(directory)
    target = Path(LOCATION_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=target.stem + "-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump(stored, file, indent=2, sort_keys=True, ensure_ascii=False)
            file.write("\n")
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

"""Recent local review files, independent of analysis and user settings."""

import json
import os
from pathlib import Path
import tempfile

from vispa_mp import preset


_KIND = "vispa-mp-recent-projects"
_VERSION = 1
_LIMIT = 10


def _storage_path():
    # Resolve this on each call: tests and installations may relocate user.json.
    return Path(preset.USER_PATH).with_name("recent-projects.json")


def _absolute_path(value):
    text = os.fspath(value)
    if not isinstance(text, str) or not text or "\0" in text:
        raise ValueError("A recent project needs a file path.")
    return str(Path(text).expanduser().resolve(strict=False))


def _unique_paths(paths):
    result, seen = [], set()
    for path in paths:
        absolute = _absolute_path(path)
        key = os.path.normcase(absolute)
        if key not in seen:
            seen.add(key)
            result.append(absolute)
        if len(result) == _LIMIT:
            break
    return result


def load_recent():
    """Return up to ten absolute paths, newest first, including missing files."""
    try:
        stored = json.loads(_storage_path().read_text(encoding="utf-8"))
        if (not isinstance(stored, dict) or stored.get("kind") != _KIND
                or type(stored.get("version")) is not int or stored["version"] != _VERSION
                or not isinstance(stored.get("projects"), list)):
            return []
        paths = stored["projects"]
        # Relative entries cannot reliably identify a file after restarting MP.
        if any(not isinstance(path, str) or not path or "\0" in path
               or not Path(path).is_absolute() for path in paths):
            return []
        return _unique_paths(paths)
    except (OSError, ValueError, TypeError, RuntimeError):
        return []


def remember_project(path):
    """Record a successful open/save; a storage failure raises ``OSError``."""
    paths = _unique_paths([_absolute_path(path), *load_recent()])
    target = _storage_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=target.parent, prefix=f".{target.name}.",
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"kind": _KIND, "version": _VERSION, "projects": paths},
                      stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
    return paths


def clear_recent():
    """Forget the list without deleting any review files."""
    try:
        _storage_path().unlink()
    except FileNotFoundError:
        pass

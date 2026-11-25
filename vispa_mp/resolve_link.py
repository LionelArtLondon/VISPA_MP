"""File mailbox between VISPA MP and a script running inside Resolve.

The free edition refuses an outside fusionscript connection. A script started
from Workspace > Scripts can still read and write the open timeline. Both
sides exchange one JSON file at a time in cache/resolve_link.
"""

import json
import os
import threading
import time
from pathlib import Path

SCRIPT_NAME = "VISPA_MP.lua"
FREE_HINT = (
    " In Resolve, run Workspace > Scripts > VISPA_MP while this command is waiting. "
    "The free edition cannot open a script window."
)

def project_root():
    return Path(__file__).resolve().parents[1]


def mailbox_dir():
    return project_root() / "cache" / "resolve_link"


def scripts_dir():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts" / "Utility"


def launcher_source(root=None):
    """Lua, because this Resolve menu lists .lua and skips .py."""
    template = (project_root() / "resolve_scripts" / "VISPA_MP.lua").read_text(encoding="utf-8")
    if "__MAILBOX__" not in template:
        raise RuntimeError("The Resolve script template is missing __MAILBOX__.")
    base = Path(root) if root is not None else project_root()
    return template.replace("__MAILBOX__", str(base / "cache" / "resolve_link"))


def install_resolve_script(folder=None):
    """Write the Workspace > Scripts launcher. Resolve lists it after a restart."""
    destination = Path(folder) if folder is not None else scripts_dir()
    if destination is None:
        return None
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / SCRIPT_NAME
    text = launcher_source()
    if not target.is_file() or target.read_text(encoding="utf-8") != text:
        target.write_text(text, encoding="utf-8")
    for stale in ("VISPA_MP.py", "VISPA MP.py"):
        old = destination / stale
        if old.is_file():
            old.unlink()
    return target


class Link:
    """One request file, one response file, and a short heartbeat."""

    def __init__(self, folder=None):
        self.folder = Path(folder) if folder is not None else mailbox_dir()

    def running(self, max_age=5.0):
        status = self._read("status.json")
        if not status or not status.get("running"):
            return False
        try:
            age = time.time() - float(status.get("at") or 0)
        except (TypeError, ValueError):
            return False
        return age <= max_age

    def write_status(self, running, timeline=""):
        self._write("status.json", {"running": bool(running), "at": time.time(), "timeline": timeline or ""})

    def write_request(self, message):
        self._write("request.json", message)

    def take_request(self):
        return self._take("request.json")

    def write_response(self, message):
        self._write("response.json", message)

    def read_response(self):
        return self._read("response.json")

    def clear_response(self):
        self._unlink("response.json")

    def _path(self, name):
        return self.folder / name

    def _write(self, name, payload):
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self._path(name)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)

    def _read(self, name):
        path = self._path(name)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _take(self, name):
        payload = self._read(name)
        self._unlink(name)
        return payload

    def _unlink(self, name):
        path = self._path(name)
        try:
            path.unlink()
        except OSError:
            pass


def link_running():
    return Link().running()


def free_script_installed():
    folder = scripts_dir()
    return bool(folder and (folder / SCRIPT_NAME).is_file())


class MailboxClient:
    """Same calls as the Studio bridge. The Resolve script does the work."""

    mailbox = True

    def __init__(self, link=None, timeout=180):
        self.link = link or Link()
        self.timeout = timeout
        self.lock = threading.Lock()

    def request(self, cmd, **payload):
        with self.lock:
            message = {"id": str(time.time_ns()), "cmd": cmd, **payload}
            self.link.clear_response()
            self.link.write_request(message)
            deadline = time.time() + self.timeout
            while time.time() < deadline:
                answer = self.link.read_response()
                if answer and answer.get("id") == message["id"]:
                    if not answer.get("ok"):
                        raise RuntimeError(answer.get("error") or "Resolve refused the command.")
                    return answer.get("result")
                time.sleep(0.05)
            raise RuntimeError("VISPA_MP did not answer." + FREE_HINT)

    def ping(self):
        return self.request("ping")

    def read(self):
        return self.request("read")

    def seek(self, timecode):
        return self.request("seek", timecode=timecode)

    def apply(self, proposals, start=None, end=None):
        return self.request("apply", proposals=proposals, start=start, end=end)

    def close(self):
        return None

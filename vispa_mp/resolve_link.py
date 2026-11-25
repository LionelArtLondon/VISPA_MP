"""File mailbox between VISPA MP and a script running inside Resolve.

The free edition refuses an outside fusionscript connection. A script started
from Workspace > Scripts can still read and write the open timeline, but it
has no io library: it cannot write a file the ordinary way. So:

- VISPA MP writes ``request.lua`` (``return [[json]]``). The script reads it
  with ``loadfile``.
- The script stores hex-encoded JSON with ``fusion:SetData`` and saves
  Fusion's preferences to ``link.prefs`` with ``SavePrefs``. VISPA MP reads
  the ``VispaMP`` block of that file: ``Status`` (heartbeat) and ``Response``.
"""

import json
import os
import re
import threading
import time
from pathlib import Path

SCRIPT_NAME = "VISPA_MP.lua"
FREE_HINT = (
    " In Resolve, run Workspace > Scripts > VISPA_MP once. "
    "It opens no window and keeps listening until Resolve closes."
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
    # The script cannot create folders: its mailbox must exist before it runs.
    mailbox_dir().mkdir(parents=True, exist_ok=True)
    target = destination / SCRIPT_NAME
    text = launcher_source()
    if not target.is_file() or target.read_text(encoding="utf-8") != text:
        target.write_text(text, encoding="utf-8")
    for stale in ("VISPA_MP.py", "VISPA MP.py"):
        old = destination / stale
        if old.is_file():
            old.unlink()
    return target


REQUEST_FILE = "request.lua"
LINK_FILE = "link.prefs"
_BLOCK = re.compile(r"\bVispaMP\s*=\s*\{([^{}]*)\}")
_FIELD = re.compile(r'\b(\w+)\s*=\s*"([0-9a-fA-F]*)"')
_REQUEST = re.compile(r"\Areturn \[(=*)\[(.*)\]\1\]\s*\Z", re.S)


def lua_long_string(text):
    """`return [==[text]==]` with a bracket level the text does not contain."""
    level = 0
    while f"]{'=' * level}]" in text:
        level += 1
    eq = "=" * level
    return f"return [{eq}[{text}]{eq}]\n"


def parse_request(text):
    match = _REQUEST.match(text or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(2))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def parse_link(text):
    """The hex fields of the VispaMP block, decoded. Empty when unreadable."""
    match = _BLOCK.search(text or "")
    if not match:
        return {}
    fields = {}
    for name, value in _FIELD.findall(match.group(1)):
        try:
            fields[name] = json.loads(bytes.fromhex(value).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
    return fields


def render_link(fields):
    """What SavePrefs would write, reduced to the VispaMP block."""
    lines = []
    for name, payload in sorted(fields.items()):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8").hex()
        lines.append(f'\t\t\t\t{name} = "{encoded}",')
    body = "\n".join(lines)
    return "{\n\tGlobal = {\n\t\tScript = {\n\t\t\tVispaMP = {\n" + body + "\n\t\t\t},\n\t\t},\n\t},\n}\n"


class Link:
    """request.lua one way, link.prefs (status and response) the other."""

    def __init__(self, folder=None):
        self.folder = Path(folder) if folder is not None else mailbox_dir()

    def running(self, max_age=5.0):
        status = self.status()
        if not status or not status.get("running"):
            return False
        try:
            age = time.time() - float(status.get("at") or 0)
        except (TypeError, ValueError):
            return False
        return age <= max_age

    def status(self):
        return self._fields().get("Status")

    def read_response(self):
        return self._fields().get("Response")

    def write_request(self, message):
        self._write(REQUEST_FILE, lua_long_string(json.dumps(message, ensure_ascii=False)))

    def pending_request(self):
        return parse_request(self._text(REQUEST_FILE))

    def take_request(self):
        """The waiting request, then removed. A read that failed (Windows refuses
        to open a file while VISPA MP replaces it) leaves the file for the next poll."""
        payload = self.pending_request()
        if payload is not None:
            self._unlink(REQUEST_FILE)
        return payload

    def clear_request(self, message_id=None):
        """Delete request.lua, but only if it still holds this request."""
        if message_id is not None:
            waiting = self.pending_request()
            if not waiting or waiting.get("id") != message_id:
                return
        self._unlink(REQUEST_FILE)

    # The Python host (resolve_scripts/VISPA_MP.py) answers through the same file.
    def write_status(self, running, timeline="", owner=None, started=None):
        payload = {"running": bool(running), "at": time.time(), "timeline": timeline or ""}
        if owner is not None:
            payload["owner"] = owner
            payload["started"] = started
        self._update_link("Status", payload)

    def write_response(self, message):
        self._update_link("Response", message)

    def _update_link(self, name, payload):
        fields = self._fields()
        fields[name] = payload
        self._write(LINK_FILE, render_link(fields))

    def _fields(self):
        return parse_link(self._text(LINK_FILE))

    def _path(self, name):
        return self.folder / name

    def _text(self, name):
        try:
            return self._path(name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _write(self, name, text):
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self._path(name)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        # Windows refuses to replace a file the other side is reading right now.
        for attempt in range(40):
            try:
                os.replace(temporary, target)
                return
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.01)

    def _unlink(self, name):
        try:
            self._path(name).unlink()
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
            self.link.write_request(message)
            deadline = time.time() + self.timeout
            while time.time() < deadline:
                answer = self.link.read_response()
                if answer and answer.get("id") == message["id"]:
                    self.link.clear_request(message["id"])
                    if not answer.get("ok"):
                        raise RuntimeError(answer.get("error") or "Resolve refused the command.")
                    return answer.get("result")
                time.sleep(0.05)
            # A script started later must not run a command the user gave up on.
            self.link.clear_request(message["id"])
            raise RuntimeError("VISPA_MP did not answer." + FREE_HINT)

    def ping(self):
        return self.request("ping")

    def stop(self):
        return self.request("stop")

    def read(self):
        return self.request("read")

    def seek(self, timecode):
        return self.request("seek", timecode=timecode)

    def apply(self, proposals, start=None, end=None):
        return self.request("apply", proposals=proposals, start=start, end=end)

    def close(self):
        return None


def stop_link(link=None, timeout=10):
    """Ask the listening Resolve script to end. False when none is listening."""
    link = link or Link()
    if not link.running():
        return False
    MailboxClient(link, timeout=timeout).stop()
    return True


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["stop"]:
        print("Stopped." if stop_link() else "The VISPA_MP script is not listening.")
    else:
        print("Usage: python -m vispa_mp.resolve_link stop")

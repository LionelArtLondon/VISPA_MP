"""Serves VISPA MP from inside DaVinci Resolve.

Workspace > Scripts starts this with the global ``resolve`` already defined.
It opens no window, because a script window (UIManager) is a Studio feature
and the free edition stops on it. It keeps answering the mailbox until
Resolve closes, VISPA MP sends ``stop``, or the script is started again.
"""

import random
import time

from vispa_mp.resolve_bridge import dispatch
from vispa_mp.resolve_link import Link

POLL_SECONDS = 0.25
STALE_SECONDS = 300


def is_stale(request, now=None):
    """VISPA MP ids are nanosecond timestamps. Old leftovers must not run."""
    try:
        sent = int(request.get("id"))
    except (TypeError, ValueError):
        return False
    if sent < 10 ** 15:
        return False
    now = time.time() if now is None else now
    return now - sent / 1e9 > STALE_SECONDS


def handle_once(resolve, link):
    """Answer the waiting request, if there is one. Safe to call often.

    Returns (handled, stopping).
    """
    request = link.take_request()
    if not request or is_stale(request):
        return False, False
    command = request.get("cmd")
    try:
        if command == "stop":
            result = {"ok": True, "stopping": True}
        else:
            timeline = project = None
            if command not in ("ping", "learning_library", "learning_open"):
                timeline, project = _target(resolve)
            result = dispatch(request, timeline, project, resolve=resolve)
        link.write_response({"id": request.get("id"), "ok": True, "result": result})
    except Exception as error:
        link.write_response({"id": request.get("id"), "ok": False, "error": str(error)})
        return True, False
    return True, command == "stop"


def replaced_by_newer(status, owner, started):
    """True when another copy of the script started later and owns the mailbox."""
    if not isinstance(status, dict) or status.get("running") is not True:
        return False
    other = str(status.get("owner") or "")
    if not other or other == owner:
        return False
    try:
        other_started = int(status.get("started") or 0)
    except (TypeError, ValueError):
        other_started = 0
    if other_started != started:
        return other_started > started
    return other > owner


def _target(resolve):
    if resolve is None:
        raise RuntimeError("This script must be started from Workspace > Scripts inside Resolve.")
    manager = resolve.GetProjectManager()
    project = manager.GetCurrentProject() if manager is not None else None
    if not project:
        raise RuntimeError("No project is open.")
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("No timeline is open.")
    return timeline, project


def _timeline(resolve):
    return _target(resolve)[0]


def _timeline_name(resolve):
    try:
        return _timeline(resolve).GetName() or ""
    except Exception:
        return ""


def serve(resolve, bmd=None, fusion=None, link=None, sleep=time.sleep, max_ticks=None):
    """Listen until stopped. ``bmd`` and ``fusion`` stay unused on purpose."""
    if resolve is None:
        raise RuntimeError("This script must be started from Workspace > Scripts inside Resolve.")
    link = link or Link()
    started = int(time.time())
    owner = f"{started}-{random.randrange(1_000_000):06d}"
    link.write_status(True, _timeline_name(resolve), owner, started)
    print("VISPA MP: listening. Keep working in Resolve; VISPA MP can read the timeline "
          "and place markers until Resolve closes.")
    beat = int(time.time())
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        ticks += 1
        if replaced_by_newer(link.status(), owner, started):
            print("VISPA MP: stopped (a newer VISPA_MP took over).")
            return "replaced"
        try:
            handled, stopping = handle_once(resolve, link)
        except Exception as error:
            print(f"VISPA MP: {error}")
            handled, stopping = False, False
        if stopping:
            link.write_status(False, "", owner, started)
            print("VISPA MP: stopped (VISPA MP asked it to stop).")
            return "stopped"
        now = int(time.time())
        if handled or now != beat:
            link.write_status(True, _timeline_name(resolve), owner, started)
            beat = now
        sleep(POLL_SECONDS)
    return "ticks"

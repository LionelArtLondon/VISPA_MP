"""Serves VISPA MP from inside DaVinci Resolve.

Workspace > Scripts starts this with the globals ``resolve``, ``bmd`` and
``fusion`` already defined. A small window stays open and answers the mailbox
without holding the Edit page frozen between commands.
"""

from vispa_mp.resolve_bridge import dispatch
from vispa_mp.resolve_link import Link

WINDOW_ID = "com.animecomics.vispa_mp"
TIMER_ID = "VispaTimer"


def handle_once(resolve, link):
    """Answer the waiting request, if there is one. Safe to call often."""
    request = link.take_request()
    if not request:
        return False
    try:
        timeline = None
        if request.get("cmd") != "ping":
            timeline = _timeline(resolve)
        result = dispatch(request, timeline)
        link.write_response({"id": request.get("id"), "ok": True, "result": result})
    except Exception as error:
        link.write_response({"id": request.get("id"), "ok": False, "error": str(error)})
    return True


def _timeline(resolve):
    if resolve is None:
        raise RuntimeError("This script must be started from Workspace > Scripts inside Resolve.")
    manager = resolve.GetProjectManager()
    project = manager.GetCurrentProject() if manager is not None else None
    if not project:
        raise RuntimeError("No project is open.")
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("No timeline is open.")
    return timeline


def _timeline_name(resolve):
    try:
        return _timeline(resolve).GetName() or ""
    except Exception:
        return ""


def serve(resolve, bmd=None, fusion=None):
    """Stay up until the window closes. Falls back to one pass if there is no window."""
    if resolve is None:
        raise RuntimeError("This script must be started from Workspace > Scripts inside Resolve.")
    link = Link()
    ui = getattr(fusion, "UIManager", None) if fusion is not None else None
    dispatcher_type = getattr(bmd, "UIDispatcher", None) if bmd is not None else None
    if ui is None or dispatcher_type is None:
        link.write_status(True, _timeline_name(resolve))
        handle_once(resolve, link)
        link.write_status(False, "")
        return
    _serve_window(resolve, link, ui, dispatcher_type(ui))


def _serve_window(resolve, link, ui, dispatcher):
    existing = ui.FindWindow(WINDOW_ID) if hasattr(ui, "FindWindow") else None
    if existing is not None and link.running():
        existing.Show()
        raise_ = getattr(existing, "Raise", None)
        if raise_ is not None:
            raise_()
        return
    if existing is not None:
        hide = getattr(existing, "Hide", None)
        if hide is not None:
            hide()

    window = dispatcher.AddWindow(
        {
            "ID": WINDOW_ID,
            "WindowTitle": "VISPA MP",
            "Geometry": [80, 80, 440, 150],
            "Spacing": 8,
        },
        ui.VGroup({"Spacing": 8}, [
            ui.Label({
                "ID": "Status",
                "Text": "Waiting for VISPA MP. Leave this window open.",
                "WordWrap": True,
            }),
            ui.Button({"ID": "Stop", "Text": "Stop"}),
        ]),
    )

    def say(text):
        try:
            label = window.Find("Status")
            if label is not None:
                label.Text = text
        except Exception:
            pass

    def stop(*_args):
        try:
            timer.Stop()
        except Exception:
            pass
        link.write_status(False, "")
        dispatcher.ExitLoop()

    def on_timeout(*_args):
        try:
            name = _timeline_name(resolve)
            if handle_once(resolve, link):
                say(f"Answered VISPA MP. Timeline: {name or '—'}.")
            link.write_status(True, name)
        except Exception as error:
            say(str(error))
            link.write_status(True, "")

    window.On[WINDOW_ID].Close = stop
    window.On["Stop"].Clicked = stop
    timer = ui.Timer({"ID": TIMER_ID, "Interval": 400, "SingleShot": False})
    dispatcher.On["Timeout"] = on_timeout
    window.Show()
    link.write_status(True, _timeline_name(resolve))
    timer.Start()
    dispatcher.RunLoop()
    link.write_status(False, "")
    window.Hide()

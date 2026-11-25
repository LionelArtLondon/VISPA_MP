"""The Resolve script stays up after one launch, without a Studio-only window."""

import subprocess
import threading
import time
from pathlib import Path

import pytest

from tests.test_bridge import Timeline
from tests.test_link import _Resolve
from vispa_mp.resolve_host import handle_once, is_stale, replaced_by_newer, serve
from vispa_mp.resolve_link import Link, MailboxClient, launcher_source, stop_link

FUSCRIPT = Path(r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fuscript.exe")


def _serve_in_background(link, **kwargs):
    outcome = []
    thread = threading.Thread(
        target=lambda: outcome.append(
            serve(_Resolve(Timeline()), link=link, sleep=lambda _s: time.sleep(0.01), **kwargs)),
        daemon=True,
    )
    thread.start()
    return thread, outcome


def test_one_launch_answers_many_commands_then_stops(tmp_path):
    link = Link(tmp_path)
    thread, outcome = _serve_in_background(link)
    client = MailboxClient(link, timeout=3)
    assert client.ping() == {"ok": True}
    assert client.read()["timeline_name"] == "Episode"
    assert client.ping() == {"ok": True}
    assert link.running()
    assert stop_link(link) is True
    thread.join(timeout=3)
    assert outcome == ["stopped"]
    assert not link.running()
    assert stop_link(link) is False


def test_running_the_script_again_replaces_the_old_copy(tmp_path):
    link = Link(tmp_path)
    first, first_outcome = _serve_in_background(link)
    deadline = time.time() + 3
    while not link.running() and time.time() < deadline:
        time.sleep(0.01)
    time.sleep(1.1)  # a later start second, as when the user runs the menu again
    second, second_outcome = _serve_in_background(link)
    first.join(timeout=3)
    assert first_outcome == ["replaced"]
    assert MailboxClient(link, timeout=3).ping() == {"ok": True}
    stop_link(link)
    second.join(timeout=3)
    assert second_outcome == ["stopped"]


def test_newer_copy_rules():
    assert replaced_by_newer(None, "10-1", 10) is False
    assert replaced_by_newer({"running": True, "owner": "10-1", "started": 10}, "10-1", 10) is False
    assert replaced_by_newer({"running": True, "owner": "11-1", "started": 11}, "10-1", 10) is True
    assert replaced_by_newer({"running": True, "owner": "9-1", "started": 9}, "10-1", 10) is False
    assert replaced_by_newer({"running": False, "owner": "11-1", "started": 11}, "10-1", 10) is False
    assert replaced_by_newer({"running": True}, "10-1", 10) is False


def test_a_leftover_request_does_not_run_later(tmp_path):
    link = Link(tmp_path)
    old = str((int(time.time()) - 3600) * 10 ** 9)
    link.write_request({"id": old, "cmd": "apply", "proposals": [{"frame": 86410, "color": "Green"}]})
    timeline = Timeline()
    assert handle_once(_Resolve(timeline), link) == (False, False)
    assert timeline.added == []
    assert link.read_response() is None
    assert is_stale({"id": "abc"}) is False


def test_a_request_nobody_answered_is_withdrawn(tmp_path):
    link = Link(tmp_path)
    with pytest.raises(RuntimeError):
        MailboxClient(link, timeout=0.2).apply([{"frame": 1, "color": "Green"}])
    assert link._read("request.json") is None


@pytest.mark.skipif(not FUSCRIPT.is_file(), reason="DaVinci Resolve is not installed")
def test_the_lua_script_listens_until_told_to_stop(tmp_path):
    """Runs the real menu script in Resolve's own Lua, with a fake timeline."""
    fake = r'''
local marks = {}
local timeline = {
  GetName = function() return "Episode" end,
  GetStartFrame = function() return 0 end,
  GetEndFrame = function() return 100 end,
  GetStartTimecode = function() return "00:00:00:00" end,
  GetSetting = function(_, key) if key == "timelineFrameRate" then return "24" end return "0" end,
  GetTrackCount = function() return 1 end,
  GetTrackName = function() return "CUE_SOURCE" end,
  GetItemListInTrack = function() return {} end,
  GetMarkInOut = function() return {} end,
  GetMarkers = function() return marks end,
  AddMarker = function(_, frame, color, name, note, duration, custom)
    marks[frame] = { color = color, name = name, note = note, duration = duration, customData = custom }
    return true
  end,
  DeleteMarkerAtFrame = function(_, frame) marks[frame] = nil return true end,
}
local project = { GetCurrentTimeline = function() return timeline end }
local manager = { GetCurrentProject = function() return project end }
resolve = { GetProjectManager = function() return manager end }
'''
    script = tmp_path / "harness.lua"
    script.write_text(fake + launcher_source(root=tmp_path), encoding="utf-8")
    link = Link(tmp_path / "cache" / "resolve_link")
    process = subprocess.Popen(
        [str(FUSCRIPT), "-l", "lua", str(script)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        client = MailboxClient(link, timeout=15)
        assert client.ping() == {"ok": True}
        assert client.read()["timeline_name"] == "Episode"
        placed = client.apply([{"frame": 12, "color": "Green"}], 0, 100)
        assert placed["placed"] == [12]
        assert [m["frame"] for m in client.read()["markers"]] == [12]
        assert link.running()
        assert client.stop()["stopping"] is True
        output, _ = process.communicate(timeout=15)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == 0, output
    assert "listening" in output
    assert "VISPA MP asked it to stop" in output
    assert not link.running()

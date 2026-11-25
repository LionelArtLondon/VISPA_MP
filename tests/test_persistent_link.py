"""The Resolve script stays up after one launch, without a Studio-only window."""

import subprocess
import threading
import time
from pathlib import Path

import pytest

from tests.test_bridge import Timeline
from tests.test_link import _Resolve
from vispa_mp.resolve_host import handle_once, is_stale, replaced_by_newer, serve
from vispa_mp.resolve_link import Link, MailboxClient, launcher_source, parse_link, stop_link

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
    # Generous waits: on a busy machine (a virus scan after an install) 3 s was not enough.
    first.join(timeout=15)
    assert first_outcome == ["replaced"]
    assert MailboxClient(link, timeout=15).ping() == {"ok": True}
    stop_link(link, timeout=15)
    second.join(timeout=15)
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
    assert link.pending_request() is None


def test_request_and_link_files_round_trip(tmp_path):
    link = Link(tmp_path)
    message = {"id": "1", "cmd": "apply", "note": "a ]] b ]=] c", "name": "Épisode"}
    link.write_request(message)
    text = (tmp_path / "request.lua").read_text(encoding="utf-8")
    assert text.startswith("return [")
    assert link.pending_request() == message
    link.write_status(True, "Episode")
    link.write_response({"id": "1", "ok": True})
    assert link.running()
    assert link.read_response() == {"id": "1", "ok": True}
    assert parse_link("garbage") == {}
    assert parse_link('VispaMP = { Status = "7b2' + '" }') == {}


def test_the_reader_finds_the_block_in_a_full_fusion_prefs_file():
    prefs = (
        '{\n\tGlobal = {\n\t\tPaths = {\n\t\t\tMap = { ["Comps:"] = "x" },\n\t\t},\n'
        '\t\tScript = {\n\t\t\tVISPA_CAPTURE_UI = {\n\t\t\t\tPayloadHex = "7b7d"\n\t\t\t},\n'
        '\t\t\tVispaMP = {\n\t\t\t\tStatus = "' + '{"running":true,"at":1}'.encode().hex() + '",\n'
        '\t\t\t\tOwner = "31302d31"\n\t\t\t}\n\t\t},\n\t},\n}\n'
    )
    assert parse_link(prefs)["Status"] == {"running": True, "at": 1}


# Fusion's data store, as the script uses it: SetData, GetData, SavePrefs.
# The saved file mimics what Resolve writes, reduced to the VispaMP block.
FAKE_FUSION = r'''
local real_io = io
local store = {}
local function render()
  local parts = { "{\n\tGlobal = {\n\t\tScript = {\n\t\t\tVispaMP = {\n" }
  for key, value in pairs(store) do
    parts[#parts + 1] = "\t\t\t\t" .. key .. ' = "' .. tostring(value) .. '",\n'
  end
  parts[#parts + 1] = "\t\t\t},\n\t\t},\n\t},\n}\n"
  return table.concat(parts)
end
fake_fusion = {
  SetData = function(_, key, value)
    if key == "VispaMP" then store = {} return end
    store[key:match("^VispaMP%.(.+)$")] = value
  end,
  GetData = function(_, key) return store[key:match("^VispaMP%.(.+)$")] end,
  SavePrefs = function(_, path)
    local file = real_io.open(path, "wb")
    file:write(render())
    file:close()
  end,
}
fusion = fake_fusion
'''

# What Workspace > Scripts really offers in Resolve 21 free: no io, no ffi,
# no require, no os.remove. fuscript has everything, so the sandboxed cases
# strip it. fuscript gives the script its own environment that falls back to
# _G, so clearing a name means clearing it in both places.
RESOLVE_SANDBOX = r'''
os.remove = nil
os.rename = nil
for _, name in ipairs({ "io", "ffi", "require", "package" }) do
  _G[name] = nil
  getfenv(1)[name] = nil
end
assert(io == nil and ffi == nil and require == nil)
'''

FAKE_TIMELINE = r'''
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

# Workspace > Scripts hands the script `app` (Fusion) and no `resolve`.
MENU = r'''
local handed = resolve
resolve = nil
fusion = nil
app = fake_fusion
app.GetResolve = function() return handed end
'''


@pytest.mark.skipif(not FUSCRIPT.is_file(), reason="DaVinci Resolve is not installed")
@pytest.mark.parametrize(
    "sandbox, menu",
    [(False, False), (True, False), (True, True)],
    ids=["plain-lua", "resolve-console", "resolve-menu"],
)
def test_the_lua_script_listens_until_told_to_stop(tmp_path, sandbox, menu):
    """Runs the real menu script in Resolve's own Lua, with fake Fusion and timeline."""
    harness = FAKE_FUSION + (RESOLVE_SANDBOX if sandbox else "") + FAKE_TIMELINE + (MENU if menu else "")
    script = tmp_path / "harness.lua"
    script.write_text(harness + launcher_source(root=tmp_path), encoding="utf-8")
    link = Link(tmp_path / "cache" / "resolve_link")
    link.folder.mkdir(parents=True)
    process = subprocess.Popen(
        [str(FUSCRIPT), "-l", "lua", str(script)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        client = MailboxClient(link, timeout=15)
        assert client.ping() == {"ok": True}
        assert link.pending_request() is None
        first = client.read()
        assert first["timeline_name"] == "Episode"
        assert first["script_version"] == 2 and first["interlaced"] is False
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


def test_an_unreadable_request_is_not_thrown_away(tmp_path, monkeypatch):
    link = Link(tmp_path)
    link.write_request({"id": "1", "cmd": "ping"})
    real_text = Link._text
    monkeypatch.setattr(Link, "_text", lambda self, name: "" if name == "request.lua" else real_text(self, name))
    assert link.take_request() is None
    monkeypatch.setattr(Link, "_text", real_text)
    assert link.take_request() == {"id": "1", "cmd": "ping"}
    assert link.pending_request() is None

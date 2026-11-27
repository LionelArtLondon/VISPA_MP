"""The actual Resolve-menu Lua bridge also supports project-library batches."""

import subprocess

import pytest

from tests.test_persistent_link import FAKE_FUSION, FAKE_TIMELINE, FUSCRIPT, MENU, RESOLVE_SANDBOX
from vispa_mp.resolve_link import Link, MailboxClient, launcher_source


LIBRARY = r'''
local function learning_project(name, names)
  local timelines = {}
  for index, title in ipairs(names) do
    local item = new_timeline(name .. "-" .. index, { [25] = { color = "Blue", name = "Manual", note = "approved", duration = 1 } })
    item.name = title
    item.GetMarkInOut = function() return { video = { ["in"] = 10, ["out"] = 90 } } end
    timelines[#timelines + 1] = item
  end
  local active = timelines[1]
  return {
    GetUniqueId = function() return name end,
    GetName = function() return name end,
    GetTimelineCount = function() return #timelines end,
    GetTimelineByIndex = function(_, index) return timelines[index] end,
    SetCurrentTimeline = function(_, item) active = item; return true end,
    GetCurrentTimeline = function() return active end,
  }
end
local projects = {
  First = learning_project("First", { "Edit", "Personal Learning" }),
  Second = learning_project("Second", { "Personal Learning" }),
  Missing = learning_project("Missing", { "Edit" }),
  Ambiguous = learning_project("Ambiguous", { "Personal Learning", "Personal Learning" }),
}
local folder = "Season"
local current = nil
manager.GetCurrentDatabase = function() return { DbType = "Disk", DbName = "Local" } end
manager.GetCurrentFolder = function() return folder == "" and "Projects" or folder end
manager.GotoRootFolder = function() folder = ""; return true end
manager.GotoParentFolder = function() if folder == "" then return false end; folder = ""; return true end
manager.OpenFolder = function(_, name) if folder ~= "" or name ~= "Season" then return false end; folder = name; return true end
manager.GetProjectListInCurrentFolder = function() return folder == "" and { "First" } or { "Second", "Missing", "Ambiguous" } end
manager.GetFolderListInCurrentFolder = function() return folder == "" and { "Season" } or {} end
manager.GetCurrentProject = function() return current end
manager.LoadProject = function(_, name) current = projects[name]; return current end
manager.SaveProject = function() error("Learning must not save a Resolve project") end
manager.CloseProject = function() error("Learning must not close a Resolve project") end
'''


@pytest.mark.skipif(not FUSCRIPT.is_file(), reason="DaVinci Resolve is not installed")
@pytest.mark.parametrize("with_flags", [False, True], ids=["plain-lists", "resolve-list-flags"])
def test_lua_batch_library_navigation_works_without_io_or_active_project(tmp_path, with_flags):
    flagged = r'''
for _, method in ipairs({ "GetProjectListInCurrentFolder", "GetFolderListInCurrentFolder" }) do
  local original_list = manager[method]
  manager[method] = function(self)
    local values = original_list(self)
    values.__flags = 4194304
    return values
  end
end
''' if with_flags else ""
    script = tmp_path / "library.lua"
    script.write_text(FAKE_FUSION + RESOLVE_SANDBOX + FAKE_TIMELINE + LIBRARY + flagged + MENU + launcher_source(root=tmp_path), encoding="utf-8")
    link = Link(tmp_path / "cache" / "resolve_link")
    link.folder.mkdir(parents=True)
    process = subprocess.Popen([str(FUSCRIPT), "-l", "lua", str(script)], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        client = MailboxClient(link, timeout=15)
        listing = client.request("learning_library")
        entries = {entry["name"]: entry for entry in listing["projects"]}
        assert len(entries) == 4 and entries["Second"]["folder"] == ["Season"]
        assert entries["First"]["folder"] == []
        first = client.request("learning_open", entry=entries["First"], timeline_name="Personal Learning")
        assert first["timeline_identity"] == {"project_id": "First", "timeline_id": "First-2"}
        assert first["mark_in"] == 10 and first["mark_out"] == 90
        assert first["markers"][0]["name"] == "Manual" and not first["markers"][0]["automatic"]
        for name in ("Missing", "Ambiguous"):
            with pytest.raises(RuntimeError, match="^Learning import:.*exactly one"):
                client.request("learning_open", entry=entries[name], timeline_name="Personal Learning")
        second = client.request("learning_open", entry=entries["Second"], timeline_name="Personal Learning")
        assert second["project_name"] == "Second" and second["timeline_identity"]["timeline_id"] == "Second-1"
        assert second["markers"] == first["markers"]
        changed = dict(entries["First"], database=dict(entries["First"]["database"], DbName="Other"))
        with pytest.raises(RuntimeError, match="library changed"):
            client.request("learning_open", entry=changed, timeline_name="Personal Learning")
        assert client.read()["project_name"] == "Second"
        assert client.stop()["stopping"]
        output, _ = process.communicate(timeout=15)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == 0, output

"""Batch navigation selects explicit projects and timelines without editing them."""

from types import SimpleNamespace

import pytest

from vispa_mp.resolve_library import list_learning_projects, open_learning_timeline


class Timeline:
    def __init__(self, name, identity):
        self.name, self.identity = name, identity

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.identity


class Project:
    def __init__(self, name, timelines):
        self.name, self.timelines = name, timelines
        self.identity = name + "-id"
        self.current = timelines[0] if timelines else None

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.identity

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, index):
        return self.timelines[index - 1]

    def SetCurrentTimeline(self, timeline):
        self.current = timeline
        return True

    def GetCurrentTimeline(self):
        return self.current


class Manager:
    def __init__(self):
        self.database = dict(DbType="Disk", DbName="Local", IpAddress="")
        self.path = ("Season",)
        self.projects = {(): {"Chapter 1": Project("Chapter 1", [Timeline("Edit", "edit-1"), Timeline("Personal Learning", "learn-1")])},
                         ("Season",): {"Chapter 2": Project("Chapter 2", [Timeline("Personal Learning", "learn-2")])}}
        self.current = None
        self.loaded = []

    def GetCurrentDatabase(self):
        return self.database

    def GetCurrentFolder(self):
        return self.path[-1] if self.path else "Projects"

    def GotoRootFolder(self):
        self.path = ()
        return True

    def GotoParentFolder(self):
        if not self.path:
            return False
        self.path = self.path[:-1]
        return True

    def OpenFolder(self, name):
        if self.path + (name,) not in self.projects:
            return False
        self.path += (name,)
        return True

    def GetProjectListInCurrentFolder(self):
        return list(self.projects[self.path])

    def GetFolderListInCurrentFolder(self):
        return [path[-1] for path in self.projects if len(path) == len(self.path) + 1 and path[:-1] == self.path]

    def LoadProject(self, name):
        self.loaded.append((self.path, name))
        self.current = self.projects[self.path].get(name)
        return self.current

    def GetCurrentProject(self):
        return self.current


def setup_library():
    manager = Manager()
    resolve = SimpleNamespace(GetProjectManager=lambda: manager)
    return manager, resolve


def test_scan_restores_folder_and_never_loads_a_project():
    manager, resolve = setup_library()
    result = list_learning_projects(resolve)
    assert [(entry["name"], entry["folder"]) for entry in result["projects"]] == [("Chapter 1", []), ("Chapter 2", ["Season"])]
    assert manager.path == ("Season",) and manager.loaded == []
    assert all(entry["database"] == manager.database for entry in result["projects"])


def test_flagged_resolve_lists_include_names_and_allow_empty_folders():
    manager, resolve = setup_library()
    projects, folders = manager.GetProjectListInCurrentFolder, manager.GetFolderListInCurrentFolder
    manager.GetProjectListInCurrentFolder = lambda: dict(enumerate(projects(), 1), __flags=4194304)
    manager.GetFolderListInCurrentFolder = lambda: dict(enumerate(folders(), 1), __flags=4194304)
    result = list_learning_projects(resolve)
    assert len(result["projects"]) == 2 and manager.path == ("Season",)
    timeline, project = open_learning_timeline(resolve, result["projects"][0], "Personal Learning")
    assert timeline.GetUniqueId() == "learn-1" and project.GetName() == "Chapter 1"


def test_genuine_invalid_library_name_is_still_reported_and_folder_restored():
    manager, resolve = setup_library()
    manager.GetProjectListInCurrentFolder = lambda: {1: "Valid", 2: 123, "__flags": 4194304}
    with pytest.raises(RuntimeError, match="library names"):
        list_learning_projects(resolve)
    assert manager.path == ("Season",) and manager.loaded == []


def test_open_selects_named_timeline_even_when_other_timelines_exist():
    manager, resolve = setup_library()
    entry = list_learning_projects(resolve)["projects"][0]
    timeline, project = open_learning_timeline(resolve, entry, "Personal Learning")
    assert timeline.GetUniqueId() == "learn-1" and project.GetCurrentTimeline() is timeline
    assert manager.loaded == [((), "Chapter 1")]


@pytest.mark.parametrize("names", [["Edit"], ["Personal Learning", "Personal Learning"]])
def test_missing_or_ambiguous_name_is_refused(names):
    manager, resolve = setup_library()
    entry = list_learning_projects(resolve)["projects"][0]
    manager.projects[()]["Chapter 1"] = Project("Chapter 1", [Timeline(name, str(index)) for index, name in enumerate(names)])
    with pytest.raises(RuntimeError, match="exactly one"):
        open_learning_timeline(resolve, entry, "Personal Learning")


def test_empty_name_is_only_allowed_for_single_timeline():
    _manager, resolve = setup_library()
    entries = list_learning_projects(resolve)["projects"]
    with pytest.raises(RuntimeError, match="single timeline"):
        open_learning_timeline(resolve, entries[0], "")
    assert open_learning_timeline(resolve, entries[1], "")[0].GetUniqueId() == "learn-2"


def test_changed_database_is_refused_before_opening_anything():
    manager, resolve = setup_library()
    entry = list_learning_projects(resolve)["projects"][0]
    manager.database = dict(manager.database, DbName="Other")
    with pytest.raises(RuntimeError, match="library changed"):
        open_learning_timeline(resolve, entry, "Personal Learning")
    assert manager.loaded == []


def test_load_refusal_never_force_closes_or_saves():
    manager, resolve = setup_library()
    entry = list_learning_projects(resolve)["projects"][0]
    manager.LoadProject = lambda _name: None
    with pytest.raises(RuntimeError, match="did not open"):
        open_learning_timeline(resolve, entry, "Personal Learning")
    assert manager.current is None


def test_unverifiable_identity_refuses_the_snapshot():
    manager, resolve = setup_library()
    entry = list_learning_projects(resolve)["projects"][0]
    manager.projects[()]["Chapter 1"].timelines[1].identity = None
    with pytest.raises(RuntimeError, match="identity"):
        open_learning_timeline(resolve, entry, "Personal Learning")


def test_same_project_name_in_different_folders_opens_exact_entry():
    manager, resolve = setup_library()
    manager.projects[("Season",)]["Chapter 1"] = Project("Chapter 1", [Timeline("Personal Learning", "different-id")])
    entry = next(entry for entry in list_learning_projects(resolve)["projects"] if entry["name"] == "Chapter 1" and entry["folder"])
    assert open_learning_timeline(resolve, entry, "Personal Learning")[0].GetUniqueId() == "different-id"
    assert manager.loaded == [(("Season",), "Chapter 1")]

"""Browse Resolve's existing library and open an exact learning timeline.

Only navigation methods are used: no project save, close, creation, deletion,
import, timeline edit or marker write. Resolve remains responsible for opening
a project normally, including any native refusal or unsaved-work interaction.
"""

from vispa_mp.timeline_identity import read_identity


def _error(text):
    raise RuntimeError("Learning import: " + text)


def _names(values):
    # Lua-shaped dictionaries can retain Resolve's bookkeeping key. Only this
    # known metadata is ignored; malformed actual project names still fail.
    values = [value for key, value in values.items() if key != "__flags"] if isinstance(values, dict) else values
    if not isinstance(values, (list, tuple)) or any(not isinstance(name, str) or not name or len(name) > 512 for name in values):
        _error("the Resolve library names could not be read.")
    return sorted(set(values), key=str.casefold)


def _database(manager):
    value = manager.GetCurrentDatabase()
    if not isinstance(value, dict) or not value.get("DbName"):
        _error("the connected Resolve project library could not be identified.")
    return {key: str(value.get(key) or "") for key in ("DbType", "DbName", "IpAddress")}


def _goto(manager, path):
    if not manager.GotoRootFolder():
        _error("the root of the Resolve library could not be opened.")
    for folder in path:
        if not manager.OpenFolder(folder):
            _error(f'the library folder "{folder}" could not be opened.')


def _current_path(manager):
    path = []
    for _ in range(32):
        name = manager.GetCurrentFolder()
        if not manager.GotoParentFolder():
            path.reverse()
            _goto(manager, path)
            return path
        if not isinstance(name, str) or not name:
            _error("the current library folder could not be identified.")
        path.append(name)
    _error("the project library has too many nested folders.")


def list_learning_projects(resolve):
    manager = resolve.GetProjectManager()
    if manager is None:
        _error("the Resolve project manager is unavailable.")
    database = _database(manager)
    origin = _current_path(manager)
    projects, visited = [], 0

    def visit(path):
        nonlocal visited
        visited += 1
        if len(path) > 12 or visited > 1000:
            _error("the library is too large for one scan. Use a smaller library for this batch.")
        for name in _names(manager.GetProjectListInCurrentFolder()):
            projects.append({"name": name, "folder": list(path), "database": database})
            if len(projects) > 2000:
                _error("the library has more than 2000 projects; use a smaller library for this batch.")
        for folder in _names(manager.GetFolderListInCurrentFolder()):
            if not manager.OpenFolder(folder):
                _error(f'the library folder "{folder}" could not be opened.')
            visit(path + [folder])
            if not manager.GotoParentFolder():
                _error("the library folder could not be restored after scanning.")

    try:
        _goto(manager, [])
        visit([])
    finally:
        _goto(manager, origin)
    return {"database": database, "projects": projects}


def open_learning_timeline(resolve, entry, timeline_name):
    if (not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"]
            or len(entry["name"]) > 512 or not isinstance(entry.get("folder"), list)
            or len(entry["folder"]) > 12 or any(not isinstance(part, str) or not part or len(part) > 512 for part in entry["folder"])
            or not isinstance(timeline_name, str) or len(timeline_name) > 512):
        _error("the selected project or timeline name is invalid.")
    manager = resolve.GetProjectManager()
    if _database(manager) != entry.get("database"):
        _error("the active Resolve library changed. Refresh the batch project list.")
    _goto(manager, entry["folder"])
    if entry["name"] not in _names(manager.GetProjectListInCurrentFolder()):
        _error(f'the project "{entry["name"]}" is no longer in its selected folder.')
    project = manager.LoadProject(entry["name"])
    if project is None:
        _error(f'Resolve did not open "{entry["name"]}". Save any current Resolve work and retry; no project is force-closed.')
    current = manager.GetCurrentProject()
    if current is None or current.GetUniqueId() != project.GetUniqueId() or project.GetName() != entry["name"]:
        _error("Resolve did not confirm the requested project as current.")
    count = int(project.GetTimelineCount())
    timelines = [project.GetTimelineByIndex(index) for index in range(1, count + 1)]
    matches = [timeline for timeline in timelines if timeline is not None and timeline.GetName() == timeline_name]
    if not timeline_name:
        matches = timelines if len(timelines) == 1 and timelines[0] is not None else []
    if len(matches) != 1:
        expected = f'timeline "{timeline_name}"' if timeline_name else "a single timeline"
        _error(f'project "{entry["name"]}" must contain exactly one {expected}; found {len(matches)} matching timeline(s).')
    timeline = matches[0]
    if not project.SetCurrentTimeline(timeline):
        _error(f'Resolve could not activate timeline "{timeline.GetName()}".')
    actual = project.GetCurrentTimeline()
    identity = read_identity(timeline, project)
    if identity is None or read_identity(actual, current) != identity:
        _error("Resolve did not confirm the requested timeline identity.")
    return timeline, project

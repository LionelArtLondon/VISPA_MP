import json

import pytest

from vispa_mp import project_location


@pytest.fixture(autouse=True)
def location_store(tmp_path, monkeypatch):
    path = tmp_path / "presets" / "project_locations.json"
    monkeypatch.setattr(project_location, "LOCATION_PATH", path)
    return path


def test_a_chosen_folder_is_remembered_for_the_project_not_the_timeline(tmp_path, location_store):
    identity = {"project_id": "project-a", "timeline_id": "timeline-a"}
    assert project_location.get_project_folder(identity) is None
    project_location.set_project_folder(identity, tmp_path)
    assert project_location.get_project_folder(identity) == tmp_path.resolve()
    assert project_location.get_project_folder(dict(identity, timeline_id="timeline-b")) == tmp_path.resolve()
    assert project_location.get_project_folder(dict(identity, project_id="project-b")) is None
    assert json.loads(location_store.read_text(encoding="utf-8")) == {"project-a": str(tmp_path.resolve())}


def test_storing_another_project_keeps_the_first_choice(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    project_location.set_project_folder({"project_id": "project-a"}, first)
    project_location.set_project_folder({"project_id": "project-b"}, second)
    assert project_location.get_project_folder({"project_id": "project-a"}) == first
    assert project_location.get_project_folder({"project_id": "project-b"}) == second


@pytest.mark.parametrize("content", ["{broken", "[]", '{"project-a": 42}', '{"project-a": "relative"}'])
def test_a_damaged_or_invalid_location_file_has_no_default(location_store, content):
    location_store.parent.mkdir()
    location_store.write_text(content, encoding="utf-8")
    assert project_location.get_project_folder({"project_id": "project-a"}) is None


@pytest.mark.parametrize("identity", [None, {}, {"project_id": " "}, {"project_id": 12}])
def test_a_missing_identity_cannot_remember_a_folder(tmp_path, location_store, identity):
    assert project_location.get_project_folder(identity) is None
    with pytest.raises(ValueError, match="identity"):
        project_location.set_project_folder(identity, tmp_path)
    assert not location_store.exists()


def test_a_disappeared_folder_is_not_offered(tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    project_location.set_project_folder({"project_id": "project-a"}, folder)
    folder.rmdir()
    assert project_location.get_project_folder({"project_id": "project-a"}) is None
    with pytest.raises(ValueError, match="existing folder"):
        project_location.set_project_folder({"project_id": "project-a"}, folder)


def test_a_failed_write_preserves_the_existing_locations(tmp_path, monkeypatch, location_store):
    identity = {"project_id": "project-a"}
    project_location.set_project_folder(identity, tmp_path)
    original = location_store.read_bytes()
    other = tmp_path / "other"
    other.mkdir()

    def fail_replace(*_args):
        raise OSError("Disk unavailable")

    monkeypatch.setattr(project_location.os, "replace", fail_replace)
    with pytest.raises(OSError, match="Disk unavailable"):
        project_location.set_project_folder(identity, other)
    assert location_store.read_bytes() == original
    assert not list(location_store.parent.glob("*.tmp"))

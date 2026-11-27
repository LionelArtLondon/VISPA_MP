"""The recent-project list is bounded, portable between launches and atomic."""

import json
import os
from pathlib import Path

import pytest

from vispa_mp import preset
from vispa_mp.recent_projects import clear_recent, load_recent, remember_project


def _storage():
    return preset.USER_PATH.with_name("recent-projects.json")


def _document(projects, **changes):
    return {"kind": "vispa-mp-recent-projects", "version": 1, "projects": projects, **changes}


def test_missing_storage_returns_empty_and_clear_is_idempotent(user_settings):
    assert load_recent() == []
    clear_recent()
    clear_recent()
    assert not _storage().exists()


def test_roundtrip_keeps_unicode_spaces_ampersands_and_missing_projects(tmp_path, user_settings):
    path = tmp_path / "Projet été & sélections" / "Chapitre 04.vispamp"
    absolute = str(path.resolve())
    assert remember_project(path) == [absolute]
    assert load_recent() == [absolute]
    assert not path.exists()
    assert "été & sélections" in _storage().read_text(encoding="utf-8")


def test_remember_promotes_existing_path_without_duplicates(tmp_path):
    first, second, third = [tmp_path / f"{name}.vispamp" for name in ("first", "second", "third")]
    for path in (first, second, third):
        remember_project(path)
    assert remember_project(second) == [str(second.resolve()), str(third.resolve()), str(first.resolve())]
    assert load_recent() == [str(second.resolve()), str(third.resolve()), str(first.resolve())]


def test_aliases_with_dot_components_and_relative_paths_are_normalized(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    absolute = str((tmp_path / "chapter.vispamp").resolve())
    assert remember_project("chapter.vispamp") == [absolute]
    assert remember_project(tmp_path / "subfolder" / ".." / "chapter.vispamp") == [absolute]
    assert Path(load_recent()[0]).is_absolute()


@pytest.mark.skipif(os.name != "nt", reason="Windows file names are case insensitive")
def test_windows_case_and_slash_variants_identify_the_same_project(tmp_path):
    path = tmp_path / "Chapter.vispamp"
    remember_project(path)
    variant = str(path).upper().replace("\\", "/")
    result = remember_project(variant)
    assert len(result) == 1
    assert os.path.normcase(result[0]) == os.path.normcase(str(path.resolve()))


def test_only_ten_most_recent_files_are_kept_and_a_promoted_file_does_not_evict_another(tmp_path):
    files = [tmp_path / f"chapter-{index}.vispamp" for index in range(13)]
    for path in files:
        remember_project(path)
    assert load_recent() == [str(path.resolve()) for path in reversed(files[3:])]
    assert remember_project(files[6]) == [str(files[6].resolve()), *[
        str(path.resolve()) for path in reversed(files[3:]) if path != files[6]]]
    assert len(load_recent()) == 10


@pytest.mark.parametrize("raw", [
    b"not JSON", b"\xff", b"[]", b"null", b"true", b"{}",
    json.dumps(_document([], kind="other-document")).encode(),
    json.dumps(_document([], version=2)).encode(),
    json.dumps(_document([], version=True)).encode(),
    json.dumps(_document([], version=1.0)).encode(),
    json.dumps(_document("chapter.vispamp")).encode(),
    json.dumps(_document([None])).encode(),
    json.dumps(_document([True])).encode(),
    json.dumps(_document([123])).encode(),
    json.dumps(_document([""])).encode(),
    json.dumps(_document(["chapter.vispamp"])).encode(),
    json.dumps(_document(["\0"])).encode(),
])
def test_malformed_or_unsupported_storage_is_ignored(raw):
    _storage().write_bytes(raw)
    assert load_recent() == []


def test_load_sanitizes_duplicates_and_oversized_lists_without_rewriting(tmp_path):
    files = [str((tmp_path / f"chapter-{index}.vispamp").resolve()) for index in range(15)]
    raw = json.dumps(_document([files[0], files[0], *files[1:]]))
    _storage().write_text(raw, encoding="utf-8")
    assert load_recent() == files[:10]
    assert _storage().read_text(encoding="utf-8") == raw


def test_valid_remember_replaces_a_corrupt_list(tmp_path):
    _storage().write_text("broken", encoding="utf-8")
    path = tmp_path / "recovered.vispamp"
    assert remember_project(path) == [str(path.resolve())]
    assert load_recent() == [str(path.resolve())]


def test_storage_path_follows_user_path_dynamically_and_creates_parent_directories(tmp_path, monkeypatch):
    first = tmp_path / "first.vispamp"
    remember_project(first)
    old_storage = _storage()
    relocated = tmp_path / "other installation" / "presets" / "user.json"
    monkeypatch.setattr(preset, "USER_PATH", relocated)
    assert load_recent() == []
    second = tmp_path / "second.vispamp"
    assert remember_project(second) == [str(second.resolve())]
    assert old_storage.exists()
    assert json.loads(old_storage.read_text(encoding="utf-8"))["projects"] == [str(first.resolve())]
    assert _storage() == relocated.with_name("recent-projects.json")
    assert not relocated.exists()


def test_remember_does_not_change_settings_or_a_review_file(tmp_path, user_settings):
    user_settings.write_text('{"compression": 0.75}', encoding="utf-8")
    project = tmp_path / "chapter.vispamp"
    project.write_bytes(b"existing review")
    remember_project(project)
    assert user_settings.read_text(encoding="utf-8") == '{"compression": 0.75}'
    assert project.read_bytes() == b"existing review"


def test_replace_failure_keeps_the_previous_list_and_removes_temporary_files(tmp_path, monkeypatch):
    first, second = tmp_path / "first.vispamp", tmp_path / "second.vispamp"
    remember_project(first)
    previous = _storage().read_bytes()
    observed = []

    def fail_replace(source, target):
        source, target = Path(source), Path(target)
        assert source.parent == target.parent == _storage().parent
        assert source != target
        assert json.loads(source.read_text(encoding="utf-8"))["projects"] == [
            str(second.resolve()), str(first.resolve())]
        assert target.read_bytes() == previous
        observed.append(source)
        raise OSError("storage busy")

    monkeypatch.setattr("vispa_mp.recent_projects.os.replace", fail_replace)
    with pytest.raises(OSError, match="storage busy"):
        remember_project(second)
    assert _storage().read_bytes() == previous
    assert observed and not observed[0].exists()
    assert load_recent() == [str(first.resolve())]


def test_read_permission_failure_is_an_empty_list(monkeypatch):
    def unreadable(_path, **_kwargs):
        raise PermissionError("storage denied")

    monkeypatch.setattr(Path, "read_text", unreadable)
    assert load_recent() == []


def test_write_permission_failure_is_reported_to_the_caller(tmp_path, monkeypatch):
    def denied(*_args, **_kwargs):
        raise PermissionError("storage denied")

    monkeypatch.setattr("vispa_mp.recent_projects.tempfile.NamedTemporaryFile", denied)
    with pytest.raises(PermissionError, match="storage denied"):
        remember_project(tmp_path / "chapter.vispamp")
    assert not _storage().exists()


def test_clear_removes_only_the_recent_list_and_keeps_project_and_settings(tmp_path, user_settings):
    project = tmp_path / "chapter.vispamp"
    project.write_bytes(b"review")
    user_settings.write_text("{}", encoding="utf-8")
    remember_project(project)
    clear_recent()
    assert load_recent() == []
    assert not _storage().exists()
    assert project.read_bytes() == b"review"
    assert user_settings.read_text(encoding="utf-8") == "{}"

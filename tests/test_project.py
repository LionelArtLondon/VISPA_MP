from copy import deepcopy
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image
import pytest

from vispa_mp.project import load_project, save_project


def _review(tmp_path):
    first, second = tmp_path / "first.jpg", tmp_path / "second.jpg"
    Image.new("RGB", (32, 18), "red").save(first)
    Image.new("RGB", (32, 18), "blue").save(second)
    identity = {"project_id": "project-1", "timeline_id": "timeline-1"}
    snapshot = {"project_name": "Tome 5", "timeline_name": "Episode 12", "timeline_identity": identity,
                "fps": 24, "start_frame": 86400,
                "video_clips": [{"path": "missing-original-video.mp4"}], "audio_clips": [], "markers": []}
    analysis = {"timeline_name": "Episode 12", "timeline_identity": dict(identity), "fps": 24,
                "timebase": {"fps": 24, "start_frame": 86400, "start_timecode": "01:00:00:00", "drop": False},
                "shots": [{"start": 86400, "end": 86424, "frames": [
                    {"frame": 86402, "image": str(first), "sharpness": 1},
                    {"frame": 86412, "image": str(second), "sharpness": 2}]}],
                "utterances": [], "speech_tracks": [], "manual_frames": [86403]}
    proposals = [{"frame": 86412, "color": "Cyan", "image": str(second), "note": "User kept this pose"}]
    settings = {"compression": 0.7, "mouth_min": 0.3}
    view = {"mode": "board", "page_format": "Custom", "orientation": "landscape", "custom_width": 150,
            "custom_height": 220, "selected_frame": 86412, "selected_page_id": 86412, "selected_manual": False,
            "playhead_frame": 86412, "open_pages": [86412], "view_filter": "all"}
    return dict(snapshot=snapshot, analysis=analysis, proposals=proposals, settings=settings, view=view)


def _rewrite(path, edit=None, extra=None, remove=None):
    with ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    metadata = json.loads(contents["project.json"])
    if edit:
        edit(metadata)
    contents["project.json"] = json.dumps(metadata).encode()
    if remove:
        for name in list(contents):
            if remove(name):
                del contents[name]
    if extra:
        contents.update(extra)
    with ZipFile(path, "w") as archive:
        for name, value in contents.items():
            archive.writestr(name, value)


def test_a_project_restores_exact_edits_settings_and_all_candidates_without_source_cache(tmp_path):
    review = _review(tmp_path)
    original = deepcopy(review)
    path = tmp_path / "Episode 12.vispamp"
    save_project(path, **review)
    assert review == original  # saving must not replace live image paths
    expected_images = {frame["frame"]: Path(frame["image"]).read_bytes()
                       for frame in review["analysis"]["shots"][0]["frames"]}
    for frame in review["analysis"]["shots"][0]["frames"]:
        Path(frame["image"]).unlink()
    restored = load_project(path, tmp_path / "new-cache")
    assert restored["snapshot"] == review["snapshot"]
    assert restored["settings"] == review["settings"]
    assert restored["view"] == review["view"]
    assert restored["proposals"][0]["color"] == "Cyan"
    assert restored["proposals"][0]["frame"] == 86412
    assert restored["proposals"][0]["note"] == review["proposals"][0]["note"]
    assert restored["analysis"]["timeline_identity"] == review["analysis"]["timeline_identity"]
    for frame in restored["analysis"]["shots"][0]["frames"]:
        assert Path(frame["image"]).read_bytes() == expected_images[frame["frame"]]
        assert Path(frame["image"]).is_relative_to(tmp_path / "new-cache" / "projects")
    assert restored["proposals"][0]["image"] == restored["analysis"]["shots"][0]["frames"][1]["image"]
    assert load_project(path, tmp_path / "new-cache") == restored
    with ZipFile(path) as archive:
        assert len(archive.namelist()) == 3
        assert all(name == "project.json" or name.startswith("images/") for name in archive.namelist())


def test_failed_atomic_replace_leaves_the_previous_project_intact(tmp_path, monkeypatch):
    review = _review(tmp_path)
    path = tmp_path / "Episode.vispamp"
    save_project(path, **review)
    previous = path.read_bytes()
    review["proposals"][0]["color"] = "Green"
    def fail_replace(*_args):
        raise PermissionError("The project file is busy")
    monkeypatch.setattr("vispa_mp.project.os.replace", fail_replace)
    with pytest.raises(PermissionError):
        save_project(path, **review)
    assert path.read_bytes() == previous
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("height", [120, 360, 4000])
def test_suggestions_panel_height_is_kept_in_the_project(tmp_path, height):
    review = _review(tmp_path)
    review["view"]["suggestions_height"] = height
    path = tmp_path / "prepared.vispamp"
    save_project(path, **review)
    assert load_project(path, tmp_path / "cache")["view"]["suggestions_height"] == height


@pytest.mark.parametrize("cameras", [
    {"strip": {"zoom": 420.5, "center": [0.2, 0.7], "columns": 3},
     "board": {"zoom": 2.3, "center": [-0.2, 1.3]}},
    {"strip": {"zoom": None, "center": [0.5, 0.5], "columns": 1}, "board": None},
    {"strip": None, "board": {"zoom": 8, "center": [-1e6, 1e6]}},
    {},
])
def test_each_views_zoom_position_and_strip_arrangement_survive_project_roundtrip(tmp_path, cameras):
    review = _review(tmp_path)
    review["view"]["cameras"] = cameras
    path = tmp_path / "prepared.vispamp"
    save_project(path, **review)
    assert load_project(path, tmp_path / "cache")["view"]["cameras"] == cameras


@pytest.mark.parametrize("cameras", [
    None, [], "zoom",
    {"strip": []}, {"board": True},
    {"strip": {"zoom": True, "center": [0.5, 0.5], "columns": 1}},
    {"strip": {"zoom": 0, "center": [0.5, 0.5], "columns": 1}},
    {"strip": {"zoom": 721, "center": [0.5, 0.5], "columns": 1}},
    {"strip": {"center": [0.5, 0.5], "columns": 1}},
    {"strip": {"zoom": None, "center": [0.5, 0.5], "columns": True}},
    {"strip": {"zoom": None, "center": [0.5, 0.5], "columns": 1.5}},
    {"strip": {"zoom": None, "center": [0.5, 0.5], "columns": 4097}},
    {"strip": {"zoom": None, "center": [0.5, 0.5], "columns": 0}},
    {"board": {"zoom": None, "center": [0.5, 0.5]}},
    {"board": {"zoom": 8.1, "center": [0.5, 0.5]}},
    {"board": {"zoom": 10 ** 500, "center": [0.5, 0.5]}},
    {"board": {"zoom": 2, "center": [0.5]}},
    {"board": {"zoom": 2, "center": [0.5, True]}},
    {"board": {"zoom": 2, "center": [0.5, 1e6 + 1]}},
])
def test_invalid_saved_cameras_are_rejected_before_returning_a_project(tmp_path, cameras):
    path = tmp_path / "prepared.vispamp"
    save_project(path, **_review(tmp_path))
    _rewrite(path, edit=lambda item: item["view"].update(cameras=cameras))
    with pytest.raises(ValueError):
        load_project(path, tmp_path / "cache")


def test_missing_review_image_does_not_overwrite_the_last_save(tmp_path):
    review = _review(tmp_path)
    path = tmp_path / "Episode.vispamp"
    save_project(path, **review)
    previous = path.read_bytes()
    Path(review["proposals"][0]["image"]).unlink()
    with pytest.raises(ValueError, match="missing or cannot be read"):
        save_project(path, **review)
    assert path.read_bytes() == previous


@pytest.mark.parametrize("edit", [
    lambda item: item.update(kind="vispa-mp-settings"),
    lambda item: item.update(version=999),
    lambda item: item["snapshot"]["timeline_identity"].update(timeline_id="other"),
    lambda item: item["analysis"].pop("timeline_identity"),
    lambda item: item["analysis"].update(shots="broken"),
    lambda item: item["analysis"].update(warnings=[{"invalid": "caption"}]),
    lambda item: item["analysis"].update(utterances=[{"start": "unknown", "end": 10}]),
    lambda item: item["analysis"]["timebase"].update(start_timecode="unreadable"),
    lambda item: item["proposals"][0].update(color="Orange"),
    lambda item: item["proposals"][0].update(mouth="unreadable"),
    lambda item: item["proposals"][0].update(frame=2 ** 80),
    lambda item: item["analysis"]["shots"][0]["frames"][0].update(image="../../outside.jpg"),
    lambda item: item["analysis"]["shots"][0]["frames"][0].update(signature=["broken"]),
    lambda item: item["snapshot"].update(start_frame=0),
    lambda item: item["view"].update(open_pages="broken"),
    lambda item: item["view"].update(rule_warnings=[{"broken": "warning"}]),
    lambda item: item["view"].update(suggestions_height=True),
    lambda item: item["view"].update(suggestions_height=119),
    lambda item: item["view"].update(suggestions_height=4001),
    lambda item: item["view"].update(suggestions_height=200.5),
])
def test_invalid_projects_are_rejected_without_returning_a_review(tmp_path, edit):
    path = tmp_path / "Episode.vispamp"
    save_project(path, **_review(tmp_path))
    _rewrite(path, edit=edit)
    with pytest.raises(ValueError):
        load_project(path, tmp_path / "cache")


def test_zip_paths_cannot_escape_the_project_cache(tmp_path):
    path = tmp_path / "Episode.vispamp"
    save_project(path, **_review(tmp_path))
    _rewrite(path, extra={"../../outside.jpg": b"unexpected"})
    with pytest.raises(ValueError, match="unsupported entries"):
        load_project(path, tmp_path / "cache")
    assert not (tmp_path / "outside.jpg").exists()
    assert not (tmp_path / "cache").exists()


def test_missing_or_modified_image_aborts_loading_and_cleans_temporary_cache(tmp_path):
    path = tmp_path / "Episode.vispamp"
    save_project(path, **_review(tmp_path))
    with ZipFile(path) as archive:
        image = next(name for name in archive.namelist() if name.startswith("images/"))
    _rewrite(path, extra={image: b"not the saved picture"})
    with pytest.raises(ValueError, match="integrity check"):
        load_project(path, tmp_path / "cache")
    assert list((tmp_path / "cache" / "projects").iterdir()) == []
    _rewrite(path, remove=lambda name: name == image)
    with pytest.raises(ValueError, match="saved image is missing"):
        load_project(path, tmp_path / "cache")


def test_a_non_project_file_has_a_readable_error(tmp_path):
    path = tmp_path / "wrong.vispamp"
    path.write_text("not a zip file", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be read"):
        load_project(path, tmp_path / "cache")


def test_reloading_repairs_a_corrupt_materialized_image_without_touching_the_project(tmp_path):
    path = tmp_path / "Episode.vispamp"
    save_project(path, **_review(tmp_path))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    loaded = load_project(path, tmp_path / "cache")
    image = Path(loaded["proposals"][0]["image"])
    image.write_bytes(b"broken cache")
    restored = load_project(path, tmp_path / "cache")
    replacement = Path(restored["proposals"][0]["image"])
    assert replacement != image
    with Image.open(replacement) as picture:
        assert picture.size == (32, 18)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before

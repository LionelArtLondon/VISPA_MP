"""Reference import measures the expert's exact images without touching Resolve."""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from tests.test_project import _review
from vispa_mp.learning_data import (
    MAX_PREVIEW_PATH, corpus_summary, import_timeline_reference, list_references, load_reference, reference_from_project,
    save_imported_reference, save_reference, update_reference, validate_reference,
)
from vispa_mp.learning_model import FEATURE_NAMES
from vispa_mp.markers import CORE, EXTRA, PAGE
from vispa_mp.preset import DEFAULTS


class Sources:
    def __init__(self, count=40):
        self.strip = np.stack([np.full((36, 64, 3), index % 8, dtype=np.uint8) for index in range(count)])
        self.filmstrip_calls = 0
        self.scored = []

    def filmstrip(self, _clip):
        self.filmstrip_calls += 1
        return self.strip

    def score_many(self, frames):
        self.scored.extend(deepcopy(frames))
        for frame in frames:
            frame.update(open_mouth=0.6, closed_mouth=0.1, face=0.8, motion_blur=0.0,
                         group=0.1, solo=0.8, from_behind=0.0, expression=0.4, teeth=0.2)


def snapshot(tmp_path, start=100, fps=25, interlaced=False):
    media = tmp_path / "chapter.mp4"
    media.write_bytes(b"a source media identity")
    rate = fps / 2 if interlaced else fps
    return {"project_name": "Tome", "timeline_name": "Chapter 04", "start_frame": start,
            "end_frame": start + int(40 * fps / rate), "fps": fps,
            "timecode_fps": rate, "interlaced": interlaced, "start_timecode": "01:00:00:00",
            "timeline_identity": {"project_id": "project-1", "timeline_id": "timeline-1"},
            "video_clips": [{"path": str(media), "start": start,
                             "end": start + int(40 * fps / rate), "source_start": 50,
                             "source_end": 90, "fps": rate, "speed": 1}],
            "audio_clips": [], "markers": [
                {"frame": start + 3, "color": PAGE, "automatic": False},
                {"frame": start + 17, "color": CORE, "automatic": False},
                {"frame": start + 25, "color": EXTRA, "automatic": False},
                {"frame": start + 29, "color": EXTRA, "automatic": True, "custom_data": "vispa-mp"},
                {"frame": start + 30, "color": "Yellow", "automatic": False}],
            "mark_in": start + 28, "mark_out": start + 30}


def imported(tmp_path, **changes):
    data = snapshot(tmp_path)
    data.update(changes)
    source = Sources()
    reference = import_timeline_reference(data, dict(DEFAULTS, max_tagged_per_shot=1), tmp_path / "cache",
                                          sources=source)
    return reference, source, data


def test_import_forces_exact_expert_images_beyond_the_candidate_cap(tmp_path):
    reference, source, _data = imported(tmp_path)
    selected = {sample["frame"]: sample for sample in reference["samples"] if sample["roles"]}
    assert set(selected) == {103, 117, 125}
    assert selected[103]["roles"] == ["core", "page"]
    assert selected[117]["roles"] == ["core"]
    assert selected[125]["roles"] == ["extra"]
    assert selected[117]["source_frame"] == 67
    assert {115, 116, 118, 119} <= {sample["frame"] for sample in reference["samples"]}
    assert all(len(sample["features"]) == len(FEATURE_NAMES) for sample in reference["samples"])
    assert reference["summary"] == {"markers": 3, "samples": len(reference["samples"]),
                                    "unlabelled": len(reference["samples"]) - 3,
                                    "core": 2, "extra": 1, "page": 1,
                                    "ignored_automatic": 1, "ignored_other_colors": 1}
    assert len(source.scored) > 1  # The expert's choices are never truncated to cap=1.


def test_import_ignores_review_in_out_and_skip_marked_without_mutating_inputs(tmp_path):
    data = snapshot(tmp_path)
    options = dict(DEFAULTS, max_tagged_per_shot=1, skip_marked_shots=True, use_in_out=True)
    before, settings_before = deepcopy(data), deepcopy(options)
    result = import_timeline_reference(data, options, tmp_path / "cache", sources=Sources())
    assert result["summary"]["markers"] == 3
    assert data == before and options == settings_before


def test_automatic_predictions_are_only_accepted_by_explicit_import_choice(tmp_path):
    data = snapshot(tmp_path)
    data["markers"] = [dict(data["markers"][3], automatic=False)]  # Signature alone is authoritative too.
    source = Sources()
    with pytest.raises(ValueError, match="No validated"):
        import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=source)
    assert source.filmstrip_calls == 0
    reference = import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=source,
                                          include_automatic=True)
    assert reference["summary"]["markers"] == 1


def test_interlaced_odd_field_uses_the_corresponding_source_picture(tmp_path):
    data = snapshot(tmp_path, start=180000, fps=50, interlaced=True)
    data["markers"] = [{"frame": 180001, "color": CORE, "automatic": False}]
    result = import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=Sources())
    selected = next(sample for sample in result["samples"] if sample["roles"])
    assert selected["frame"] == 180001  # No second addition of start_frame.
    assert selected["source_frame"] == 50
    assert selected["shot"] == 180000


@pytest.mark.parametrize("change, message", [
    ("retime", "Retimed"), ("rate", "frame rates differ"),
    ("gap", "gap"), ("overlap", "overlapping"), ("short", "exact source image"),
])
def test_unverifiable_source_alignment_is_rejected_without_partial_reference(tmp_path, change, message):
    data = snapshot(tmp_path)
    source = Sources()
    if change == "retime":
        data["video_clips"][0]["speed"] = 200
    elif change == "rate":
        data["video_clips"][0]["fps"] = 24
    elif change == "gap":
        data["markers"][0]["frame"] = 99
    elif change == "overlap":
        data["video_clips"].append(dict(data["video_clips"][0]))
    else:
        source = Sources(count=5)
    with pytest.raises(ValueError, match=message):
        import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=source)
    assert not list((tmp_path / "cache").glob("**/*.json"))


@pytest.mark.parametrize("start,end", [(None, 90), (True, 90), (50, None), (-1, 39), (50, 80)])
def test_missing_or_inconsistent_source_in_out_is_never_guessed(tmp_path, start, end):
    data = snapshot(tmp_path)
    data["video_clips"][0].update(source_start=start, source_end=end)
    with pytest.raises(ValueError, match="source"):
        import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=Sources())


def test_cancellation_and_progress_are_supported_before_any_reference_is_saved(tmp_path):
    data = snapshot(tmp_path)
    source, progress = Sources(), []
    with pytest.raises(InterruptedError, match="cancelled"):
        import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=source,
                                  progress=progress.append, cancel=lambda: True)
    assert source.filmstrip_calls == 0
    reference = import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=source,
                                          progress=progress.append)
    assert reference["summary"]["markers"] == 3
    assert progress and isinstance(progress[-1], str) and "Reference ready" in progress[-1]


def test_audio_context_is_measured_consistently_with_personal_profile_features(tmp_path):
    data = snapshot(tmp_path)
    data["audio_clips"] = [dict(start=100, end=140, path="speech.wav", speed=1)]

    class SpeechSources(Sources):
        def waveform(self, clip, fps):
            assert clip["start"] == 100 and fps == 25
            return np.zeros(25600, dtype=np.float32)

        def probabilities(self, audio):
            return [1.0] * (len(audio) // 512)

    reference = import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=SpeechSources())
    speech = FEATURE_NAMES.index("speech")
    assert reference["source"]["speech_analyzed"] is True
    assert all(sample["features"][speech] == 1.0 for sample in reference["samples"])


def test_audio_context_cannot_silently_disappear_from_reference_features(tmp_path):
    data = snapshot(tmp_path)
    data["audio_clips"] = [dict(start=100, end=140, path="speech.wav", speed=1)]
    with pytest.raises(ValueError, match="incomplete speech features"):
        import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=Sources())


def test_review_reference_needs_no_resolve_source_video_or_models(tmp_path):
    review = _review(tmp_path)
    for frame in review["analysis"]["shots"][0]["frames"]:
        Path(frame["image"]).unlink()
    reference = reference_from_project(review)
    assert reference["source"]["type"] == "VISPA MP"
    assert reference["summary"]["extra"] == 1
    assert reference["summary"]["markers"] == 1
    assert reference["samples"][-1]["roles"] == ["extra"]


def test_review_reference_refuses_unmeasured_selected_frame_instead_of_guessing(tmp_path):
    review = _review(tmp_path)
    review["proposals"][0]["frame"] = 86420
    with pytest.raises(ValueError, match="could not be measured exactly"):
        reference_from_project(review)


def test_source_group_is_shared_by_edits_and_stays_stable_when_media_goes_offline(tmp_path):
    reference, _source, data = imported(tmp_path)
    revised = deepcopy(data)
    revised["timeline_identity"]["project_id"] = "another-project"
    revised["timeline_name"] = "Different cut of Chapter 04"
    again = import_timeline_reference(revised, DEFAULTS, tmp_path / "cache", sources=Sources())
    assert again["id"] != reference["id"]
    assert again["group_id"] == reference["group_id"]
    review = {"snapshot": revised, "analysis": {"fps": 25, "shots": [
        {"start": 100, "end": 140, "frames": [{"frame": 117, "sharpness": 50}]}]},
              "proposals": [{"frame": 117, "color": CORE}]}
    Path(data["video_clips"][0]["path"]).unlink()
    assert reference_from_project(review)["group_id"] == reference["group_id"]
    assert reference_from_project(review, group_id="Chapter 04")["group_id"] == "Chapter 04"


def test_reimporting_the_same_timeline_replaces_one_reference_atomically(tmp_path):
    reference, _source, data = imported(tmp_path)
    folder = tmp_path / "references"
    path = save_reference(reference, folder)
    data["markers"] = [{"frame": 118, "color": EXTRA, "automatic": False}]
    revised = import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=Sources(), name="Revised")
    assert revised["id"] == reference["id"]
    assert save_reference(revised, folder) == path
    assert len(list_references(folder)) == 1
    assert load_reference(path) == revised


def test_failed_atomic_replace_keeps_the_existing_reference(tmp_path, monkeypatch):
    reference, _source, _data = imported(tmp_path)
    folder = tmp_path / "references"
    path = save_reference(reference, folder)
    before = path.read_bytes()
    reference["name"] = "Updated"

    def denied(*_args):
        raise PermissionError("File busy")

    monkeypatch.setattr("vispa_mp.learning_data.os.replace", denied)
    with pytest.raises(PermissionError):
        save_reference(reference, folder)
    assert path.read_bytes() == before
    assert not list(folder.glob("*.part"))


@pytest.mark.parametrize("corruption", ["version", "features", "nan", "bounds", "huge", "frame", "duplicate", "roles", "feature_names", "summary"])
def test_corrupt_reference_is_never_used_for_learning(tmp_path, corruption):
    reference, _source, _data = imported(tmp_path)
    damaged = deepcopy(reference)
    if corruption == "version":
        damaged["version"] = True
    elif corruption == "features":
        damaged["samples"][0]["features"] = []
    elif corruption == "nan":
        damaged["samples"][0]["features"][0] = float("nan")
    elif corruption == "bounds":
        damaged["samples"][0]["features"][0] = 1.5
    elif corruption == "huge":
        damaged["samples"][0]["features"][0] = 10 ** 1000
    elif corruption == "frame":
        damaged["samples"][0]["frame"] = True
    elif corruption == "duplicate":
        damaged["samples"].append(deepcopy(damaged["samples"][0]))
    elif corruption == "roles":
        damaged["samples"][0]["roles"] = ["page"]
    elif corruption == "feature_names":
        damaged["feature_names"] = ["old-version"]
    else:
        damaged["summary"]["markers"] += 1
    with pytest.raises(ValueError):
        validate_reference(damaged)


def test_path_like_reference_id_cannot_write_outside_reference_folder(tmp_path):
    reference, _source, _data = imported(tmp_path)
    reference["id"] = "../../outside.json"
    folder = tmp_path / "references"
    path = save_reference(reference, folder)
    assert path.parent == folder
    assert not (tmp_path / "outside.json").exists()


def test_malformed_json_reference_and_corrupt_library_are_reported(tmp_path):
    folder = tmp_path / "references"
    folder.mkdir()
    path = folder / "bad.json"
    path.write_text('{"features":NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="cannot be read"):
        load_reference(path)
    with pytest.raises(ValueError):
        list_references(folder)


def corpus_reference(identity, roles_by_frame, group="chapter-a", media=None, enabled=True):
    """Small measured corpus with explicit chronology and no model dependency."""
    samples = [{"frame": frame, "shot": 0, "features": [0.0] * len(FEATURE_NAMES), "roles": roles}
               for frame, roles in roles_by_frame]
    labelled = sum(bool(sample["roles"]) for sample in samples)
    return {"kind": "vispa-mp-reference", "version": 1, "id": identity, "name": identity,
            "group_id": group, "enabled": enabled, "feature_names": list(FEATURE_NAMES),
            "samples": samples, "source": {"media": media or []},
            "summary": {"markers": labelled, "samples": len(samples), "unlabelled": len(samples) - labelled,
                        **{role: sum(role in sample["roles"] for sample in samples)
                           for role in ("core", "extra", "page")}}}


def test_missing_enabled_defaults_to_true_and_is_saved_without_mutating_input(tmp_path):
    reference = corpus_reference("legacy", [(10, ["core", "page"])])
    del reference["enabled"]
    validated = validate_reference(reference)
    assert validated["enabled"] is True
    assert "enabled" not in reference
    path = save_reference(reference, tmp_path / "references")
    assert json.loads(path.read_text(encoding="utf-8"))["enabled"] is True
    assert corpus_summary([reference])["active_references"] == 1


@pytest.mark.parametrize("enabled", [0, 1, "true", None, [], {}])
def test_corpus_inclusion_is_a_strict_boolean(enabled):
    reference = corpus_reference("invalid", [(10, ["core"])], enabled=enabled)
    with pytest.raises(ValueError, match="true or false"):
        validate_reference(reference)


def test_updating_corpus_metadata_preserves_all_measured_data(tmp_path):
    reference = corpus_reference("chapter", [(10, ["core", "page"]), (11, ["extra"])],
                                 media=[{"path": str(tmp_path / "film.mp4"), "size": 100}])
    reference["editorial"] = {"layout": ["retained"]}
    original = deepcopy(reference)
    folder = tmp_path / "references"
    path = save_reference(reference, folder)
    updated = update_reference(reference["id"], enabled=False, group_id="  Chapter 04  ", folder=folder)
    expected = dict(original, enabled=False, group_id="Chapter 04")
    assert updated == expected
    assert load_reference(path) == expected
    assert reference == original
    assert update_reference(reference["id"], enabled=True, folder=folder) == dict(expected, enabled=True)


@pytest.mark.parametrize("changes", [{"enabled": 1}, {"enabled": "false"}, {"group_id": " "},
                                      {"group_id": True}, {"group_id": "a" * 2049}])
def test_invalid_metadata_update_leaves_reference_unchanged(tmp_path, changes):
    reference = corpus_reference("chapter", [(10, ["core"])])
    folder = tmp_path / "references"
    path = save_reference(reference, folder)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        update_reference(reference["id"], folder=folder, **changes)
    assert path.read_bytes() == before


def test_missing_reference_update_has_a_clear_message_and_creates_nothing(tmp_path):
    folder = tmp_path / "absent"
    with pytest.raises(ValueError, match="no longer exists"):
        update_reference("../../missing", enabled=False, folder=folder)
    assert not folder.exists()


def test_failed_metadata_update_keeps_existing_atomic_file(tmp_path, monkeypatch):
    reference = corpus_reference("chapter", [(10, ["core"])])
    folder = tmp_path / "references"
    path = save_reference(reference, folder)
    before = path.read_bytes()

    def denied(*_args):
        raise PermissionError("File busy")

    monkeypatch.setattr("vispa_mp.learning_data.os.replace", denied)
    with pytest.raises(PermissionError):
        update_reference(reference["id"], enabled=False, folder=folder)
    assert path.read_bytes() == before
    assert not list(folder.glob("*.part"))


def test_reimport_refreshes_examples_and_preserves_user_corpus_choices(tmp_path):
    reference = corpus_reference("timeline", [(10, ["core", "page"])])
    folder = tmp_path / "references"
    path = save_imported_reference(reference, folder)
    update_reference(reference["id"], enabled=False, group_id="My chapter", folder=folder)
    revised = corpus_reference("timeline", [(30, ["core", "page"]), (40, ["extra"])], group="new-auto-group")
    revised["name"] = "Updated edit"
    original = deepcopy(revised)
    assert save_imported_reference(revised, folder) == path
    stored = load_reference(path)
    assert stored == dict(revised, enabled=False, group_id="My chapter")
    assert revised == original
    assert len(list_references(folder)) == 1
    save_imported_reference(revised, folder, group_id="  Explicit group  ")
    assert load_reference(path) == dict(revised, enabled=False, group_id="Explicit group")


def test_new_import_accepts_explicit_group_and_regular_save_keeps_overwrite_semantics(tmp_path):
    reference = corpus_reference("timeline", [(10, ["core"])])
    folder = tmp_path / "references"
    path = save_imported_reference(reference, folder, group_id="Manual group")
    assert load_reference(path) == dict(reference, group_id="Manual group")
    update_reference(reference["id"], enabled=False, folder=folder)
    save_reference(reference, folder)
    assert load_reference(path) == reference


def test_corpus_summary_counts_chronological_observed_pages_without_assigning_prefix():
    first = corpus_reference("first", [(35, ["extra"]), (7, ["extra"]), (20, ["core"]),
                                        (10, ["core", "page"]), (5, ["core"]),
                                        (30, ["core", "page"]), (25, ["extra"]), (27, [])])
    second = corpus_reference("second", [(50, ["core", "page"]), (60, ["core"]), (61, ["extra"])],
                              group="chapter-b")
    original = deepcopy([first, second])
    summary = corpus_summary([first, second])
    assert (summary["references"], summary["active_references"], summary["excluded_references"], summary["groups"]) == (2, 2, 0, 2)
    assert (summary["samples"], summary["page"], summary["core"], summary["extra"]) == (11, 3, 6, 4)
    assert summary["extra_core_ratio"] == pytest.approx(4 / 6)
    assert summary["observed_pages"] == 3
    assert summary["core_per_page"] == {"count": 3, "mean": 5 / 3, "median": 2, "min": 1, "max": 2}
    assert summary["extra_per_page"] == {"count": 3, "mean": 1, "median": 1, "min": 1, "max": 1}
    assert summary["before_first_start"] == {"core": 1, "extra": 1}
    assert any("partial" in note for note in summary["notes"])
    assert [first, second] == original


def test_summary_ignores_excluded_chapters_and_deduplicates_active_identity(tmp_path):
    path = str(tmp_path / "film.mp4")
    included = corpus_reference("first", [(10, ["core", "page"]), (12, ["extra"])], media=[path])
    excluded = corpus_reference("excluded", [(10, ["core", "page"])], group="other", media=[path], enabled=False)
    summary = corpus_summary([included, deepcopy(included), excluded])
    assert (summary["references"], summary["active_references"], summary["excluded_references"],
            summary["duplicate_references"], summary["groups"], summary["samples"]) == (3, 1, 1, 1, 1, 2)
    assert summary["conflicting_media"] == []
    assert any("Duplicate" in warning for warning in summary["warnings"])


def test_no_page_starts_leave_all_markers_unassigned_and_warn_for_missing_role():
    reference = corpus_reference("chapter", [(10, ["core"]), (20, ["extra"])])
    summary = corpus_summary([reference])
    assert summary["observed_pages"] == 0
    assert summary["core_per_page"] == {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    assert summary["extra_per_page"] == summary["core_per_page"]
    assert summary["before_first_start"] == {"core": 1, "extra": 1}
    assert any("no approved Page start" in warning for warning in summary["warnings"])
    assert any("one source chapter group" in warning for warning in summary["warnings"])


def test_empty_or_excluded_corpus_reports_no_active_training_examples():
    for references in ([], [corpus_reference("excluded", [(10, ["extra"])], enabled=False)]):
        summary = corpus_summary(references)
        assert summary["active_references"] == summary["groups"] == summary["samples"] == 0
        assert summary["extra_core_ratio"] is None
        assert any("No reference chapters" in warning for warning in summary["warnings"])
    extra_only = corpus_summary([corpus_reference("extra-only", [(10, ["extra"])])])
    assert extra_only["extra_core_ratio"] is None
    assert any("no approved Core" in warning for warning in extra_only["warnings"])


def test_summary_warns_about_shared_media_in_different_active_groups(tmp_path):
    path = str(tmp_path / "FILM.mp4")
    first = corpus_reference("first", [(10, ["core", "page"])], group="a", media=[{"path": path, "size": 10}])
    second = corpus_reference("second", [(20, ["extra"])], group="b", media=[path.lower()])
    summary = corpus_summary([first, second])
    assert summary["conflicting_media"] == [{"name": "film.mp4", "groups": ["a", "b"]}]
    assert any("different chapter groups" in warning for warning in summary["warnings"])
    assert any("Copies or renamed" in note for note in summary["notes"])
    assert corpus_summary([dict(first, group_id="b"), second])["conflicting_media"] == []


def test_review_references_keep_exact_extracted_preview_paths_without_copying_files(tmp_path):
    review = _review(tmp_path)
    before = deepcopy(review)
    existing = set(tmp_path.rglob("*"))
    reference = reference_from_project(review)
    expected = {frame["frame"]: frame["image"] for shot in review["analysis"]["shots"] for frame in shot["frames"]}
    assert {sample["frame"]: sample["image"] for sample in reference["samples"]} == expected
    without_previews = deepcopy(review)
    for shot in without_previews["analysis"]["shots"]:
        for frame in shot["frames"]:
            del frame["image"]
    reference_without_previews = reference_from_project(without_previews)
    expected_without_paths = deepcopy(reference)
    for sample in expected_without_paths["samples"]:
        del sample["image"]
    assert reference_without_previews == expected_without_paths
    assert set(tmp_path.rglob("*")) == existing
    assert review == before


def test_resolve_import_preview_uses_exact_source_picture_for_odd_interlaced_marker(tmp_path):
    from PIL import Image
    from vispa_mp.timebase import format_timecode

    class ImageSources(Sources):
        def score_many(self, frames):
            super().score_many(frames)
            for frame in frames:
                image = tmp_path / f"source-{frame['source_frame']}.jpg"
                if not image.exists():
                    Image.new("RGB", (32, 18), "red").save(image)
                frame["image"] = str(image)

    data = snapshot(tmp_path, start=180000, fps=50, interlaced=True)
    data["drop"] = False
    data["markers"] = [{"frame": 180001, "color": CORE, "automatic": False}]
    reference = import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=ImageSources())
    selected = next(sample for sample in reference["samples"] if sample["roles"])
    assert selected["frame"] == 180001
    assert selected["source_frame"] == 50
    assert selected["image"] == str(tmp_path / "source-50.jpg")
    assert Path(selected["image"]).is_file()
    assert reference["timebase"]["timecode_fps"] == 25
    assert reference["timebase"]["drop"] is False
    assert format_timecode(selected["frame"], reference["timebase"]) == "01:00:00:00"


def test_portable_project_reference_preserves_complete_display_timebase(tmp_path):
    from vispa_mp.timebase import format_timecode

    review = _review(tmp_path)
    review["snapshot"].update(fps=59.94)
    review["analysis"].update(fps=59.94)
    base = review["analysis"]["timebase"]
    base.update(fps=59.94, timecode_fps=29.97, start_timecode="01:00:00;00", drop=True)
    reference = reference_from_project(review)
    assert reference["timebase"] == base
    assert format_timecode(86412, reference["timebase"]) == "01:00:00;06"
    # Explicit normalized snapshot fields take precedence over a redundant base.
    review["snapshot"].update(timecode_fps=59.94, start_timecode="00:00:00:00", drop=False)
    assert reference_from_project(review)["timebase"]["timecode_fps"] == 59.94
    assert reference_from_project(review)["timebase"]["drop"] is False


def test_missing_preview_and_legacy_references_remain_usable_without_file_access(tmp_path, monkeypatch):
    review = _review(tmp_path)
    reference = reference_from_project(review)
    for sample in reference["samples"]:
        Path(sample["image"]).unlink()
    path = save_reference(reference, tmp_path / "references")
    assert load_reference(path) == reference

    def no_probe(*_args, **_kwargs):
        raise AssertionError("Reference validation must not open or probe preview files")

    monkeypatch.setattr(Path, "is_file", no_probe)
    monkeypatch.setattr(Path, "stat", no_probe)
    assert validate_reference(reference) == reference
    legacy = deepcopy(reference)
    for sample in legacy["samples"]:
        del sample["image"]
    assert validate_reference(legacy) == legacy
    assert corpus_summary([reference]) == corpus_summary([legacy])


@pytest.mark.parametrize("image", [None, False, 42, [], {}, "", "relative.jpg", "C:relative.jpg",
                                    "file:///C:/cache/image.jpg", "https://example.com/image.jpg",
                                    "\\\\server\\share\\image.jpg", "//server/share/image.jpg", "/\\server/share/image.jpg",
                                    "C:/cache/image.svg", "C:/cache/image.jpg\x00", "C:/cache/im\nage.jpg",
                                    " C:/cache/image.jpg", "C:/" + "x" * MAX_PREVIEW_PATH + ".jpg"])
def test_preview_metadata_rejects_invalid_nonlocal_or_unsupported_paths(image):
    reference = corpus_reference("chapter", [(10, ["core"])])
    reference["samples"][0]["image"] = image
    with pytest.raises(ValueError, match="absolute local JPEG or PNG"):
        validate_reference(reference)


@pytest.mark.parametrize("image", ["C:/cache/still.jpg", "C:\\cache\\still.JPEG", "/cache/still.png"])
def test_preview_metadata_supports_local_bitmap_paths_without_requiring_available_cache(image):
    reference = corpus_reference("chapter", [(10, ["core"])])
    reference["samples"][0]["image"] = image
    assert validate_reference(reference)["samples"][0]["image"] == image


def test_preview_metadata_does_not_change_features_roles_or_training_results(tmp_path):
    from vispa_mp.learning_model import train_profile

    original = corpus_reference("chapter", [(0, ["core", "page"]), (12, []), (24, ["extra"]), (36, [])])
    original["timebase"] = {"fps": 24}
    for sample, feature in zip(original["samples"], ("open_mouth", "sharpness", "motion", "closed_mouth")):
        sample["features"][FEATURE_NAMES.index(feature)] = 1.0
    with_previews = deepcopy(original)
    for index, sample in enumerate(with_previews["samples"]):
        sample["image"] = str(tmp_path / f"missing-{index}.jpg")
    validated = validate_reference(with_previews)
    assert [sample["features"] for sample in validated["samples"]] == [sample["features"] for sample in original["samples"]]
    assert train_profile([validated]) == train_profile([original])


@pytest.mark.parametrize("image", ["", "relative/still.jpg", "C:/cache/still.svg", "\\\\server\\share\\still.jpg", None])
def test_legacy_measured_project_preview_cannot_block_reference_import(tmp_path, monkeypatch, image):
    review = _review(tmp_path)
    baseline = reference_from_project(review)
    for sample in baseline["samples"]:
        del sample["image"]
    for shot in review["analysis"]["shots"]:
        for frame in shot["frames"]:
            frame["image"] = image
    original = deepcopy(review)

    def no_probe(*_args, **_kwargs):
        raise AssertionError("Import must not open or probe optional preview paths")

    # Media identity has its own legitimate stat; isolate preview handling here.
    with monkeypatch.context() as patch:
        patch.setattr("vispa_mp.learning_data._source_media", lambda _snapshot: deepcopy(baseline["source"]["media"]))
        patch.setattr(Path, "stat", no_probe)
        patch.setattr(Path, "is_file", no_probe)
        patch.setattr(Path, "open", no_probe)
        assert reference_from_project(review) == baseline
    assert review == original


@pytest.mark.parametrize("image", ["", "cache/stills/still.jpg", "C:/cache/still.svg", "\\\\server\\share\\still.jpg"])
def test_measured_resolve_import_omits_unsupported_optional_previews(tmp_path, monkeypatch, image):
    data = snapshot(tmp_path)
    baseline = import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=Sources())

    class OptionalImageSources(Sources):
        def score_many(self, frames):
            super().score_many(frames)
            for frame in frames:
                frame["image"] = image

    def no_probe(*_args, **_kwargs):
        raise AssertionError("Measured import must not inspect optional preview paths")

    with monkeypatch.context() as patch:
        patch.setattr("vispa_mp.learning_data._source_media", lambda _snapshot: deepcopy(baseline["source"]["media"]))
        patch.setattr(Path, "stat", no_probe)
        patch.setattr(Path, "is_file", no_probe)
        patch.setattr(Path, "open", no_probe)
        reference = import_timeline_reference(data, DEFAULTS, "relative-cache", sources=OptionalImageSources())
    assert reference == baseline

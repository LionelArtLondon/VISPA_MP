import io
import json

import pytest

from vispa_mp.markers import cue_warning, plan_apply
from vispa_mp.resolve_bridge import dispatch, read_timeline, serve
from vispa_mp.timeline_identity import normalize_identity, read_identity


class Timeline:
    def __init__(self, unique_id="timeline-1", name="Episode"):
        self.added = []
        self.deleted = []
        self.timecode = "01:00:00:00"
        self.unique_id = unique_id
        self.name = name
        self.markers = {
            10: {"color": "Blue", "name": "main", "note": "", "duration": 1, "customData": ""},
            100: {"color": "Cyan", "name": "auto", "note": "old", "duration": 1, "customData": "vispa-mp"},
        }

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name

    def GetStartFrame(self):
        return 86400

    def GetEndFrame(self):
        return 90000

    def GetStartTimecode(self):
        return "01:00:00:00"

    def GetSetting(self, key):
        return {"timelineFrameRate": "24", "timelineDropFrameTimecode": "0"}.get(key, "")

    def GetTrackCount(self, track_type):
        return 5 if track_type == "video" else 2

    def GetTrackName(self, track_type, index):
        if track_type == "video" and index == 1:
            return "V1"
        if track_type == "video":
            return f"Grade {index}"
        return "A1"

    def GetItemListInTrack(self, track_type, index):
        if track_type == "video" and index == 1:
            return [Clip("episode.mp4")]
        if track_type == "audio" and index == 1:
            return [Clip("episode.mp4")]
        return []

    def GetMarkInOut(self):
        return {"video": {"in": 100, "out": 400}}

    def GetMarkers(self):
        return self.markers

    def GetMarkerCustomData(self, frame):
        return self.markers.get(int(frame), {}).get("customData", "")

    def DeleteMarkerAtFrame(self, frame):
        self.deleted.append(int(frame))
        return self.markers.pop(int(frame), None) is not None

    def AddMarker(self, frame, color, name, note, duration, custom):
        self.added.append((int(frame), color, name, note, custom))
        if not name or not 0 <= int(frame) <= self.GetEndFrame() - self.GetStartFrame() or int(frame) in self.markers:
            return False
        self.markers[int(frame)] = {"color": color, "name": name, "note": note,
                                    "duration": duration, "customData": custom}
        return True

    def SetCurrentTimecode(self, timecode):
        self.timecode = timecode
        return True


class Clip:
    def __init__(self, path):
        self.path = path

    def GetName(self):
        return "Episode"

    def GetStart(self):
        return 86400

    def GetEnd(self):
        return 90000

    def GetSourceStartFrame(self):
        return 0

    def GetSourceEndFrame(self):
        return 3600

    def GetMediaPoolItem(self):
        return self

    def GetClipProperty(self):
        return {"File Path": self.path, "FPS": 23.976}

    def GetSpeed(self):
        return {"speed": 1.0}


class Project:
    def __init__(self, timeline=None, unique_id="project-1"):
        self.timeline = timeline or Timeline()
        self.unique_id = unique_id

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return "Comic project"

    def GetCurrentTimeline(self):
        return self.timeline


IDENTITY = {"project_id": "project-1", "timeline_id": "timeline-1"}


def test_only_video_1_and_audio_1_are_read_and_hand_markers_stay():
    snapshot = read_timeline(Timeline(), Project())
    assert snapshot["timeline_identity"] == IDENTITY
    assert snapshot["project_name"] == "Comic project"
    assert snapshot["script_version"] == 5
    assert snapshot["video_track_name"] == "V1"
    assert len(snapshot["video_clips"]) == 1
    assert snapshot["video_clips"][0]["path"] == "episode.mp4"
    assert len(snapshot["audio_clips"]) == 1
    assert snapshot["mark_in"] == 86500
    assert snapshot["markers"][0]["automatic"] is False
    assert snapshot["markers"][1]["automatic"] is True
    assert "CUE_SOURCE" in snapshot["warnings"][0]
    assert cue_warning(["CUE_SOURCE"]) == ""


def test_read_without_project_name_keeps_the_timeline_readable():
    assert read_timeline(Timeline())["project_name"] == ""
    project = Project()
    project.GetName = lambda: None
    assert read_timeline(Timeline(), project)["project_name"] == ""
    project.GetName = None
    assert read_timeline(Timeline(), project)["project_name"] == ""


def test_apply_deletes_only_automatic_markers_and_skips_a_hand_placed_frame():
    timeline = Timeline()
    result = dispatch({
        "cmd": "apply_checked",
        "expected_timeline": IDENTITY,
        "proposals": [
            {"frame": 10, "color": "Blue", "name": "Corps", "note": "occupé"},
            {"frame": 200, "color": "Green", "name": "Page", "note": "Début de page"},
        ],
    }, timeline, Project(timeline))
    assert timeline.deleted == [100]
    assert [item[0] for item in timeline.added] == [200]
    assert timeline.added[0][1:] == ("Green", "marqueur-001", "", "vispa-mp")
    assert 10 in result["skipped"]
    assert result["verified"] is True
    assert result["placed"] == [200]
    assert result["failed"] == []
    assert result["requested"] == 2 and result["attempted"] == 1
    delete, add, skipped = plan_apply(
        [{"frame": 1, "automatic": False}, {"frame": 2, "automatic": True}],
        [{"frame": 1, "color": "Blue"}, {"frame": 3, "color": "Cyan"}],
        0, 10,
    )
    assert delete == [2]
    assert [item["frame"] for item in add] == [3]
    assert skipped == [1]


def test_seek_sets_the_playhead():
    timeline = Timeline()
    assert dispatch({"cmd": "seek", "timecode": "01:02:03:04"}, timeline)["ok"] is True
    assert timeline.timecode == "01:02:03:04"


@pytest.mark.parametrize("timeline_id,project_id", [("timeline-2", "project-1"), ("timeline-1", "project-2")])
def test_placement_refuses_another_timeline_or_project_with_the_same_name(timeline_id, project_id):
    timeline = Timeline(timeline_id)
    project = Project(timeline, project_id)
    # The identity check must run before even reading or planning any marker edits.
    timeline.GetMarkers = lambda: pytest.fail("The wrong timeline's markers must not be read")
    with pytest.raises(RuntimeError, match="not the analyzed timeline"):
        dispatch({"cmd": "apply_checked", "expected_timeline": IDENTITY,
                  "proposals": [{"frame": 200, "color": "Green"}]}, timeline, project)
    assert timeline.added == [] and timeline.deleted == []


@pytest.mark.parametrize("expected", [None, {}, {"timeline_id": "timeline-1"},
                                      {"project_id": "project-1", "timeline_id": ""},
                                      {"project_id": "project-1", "timeline_id": 1}, "timeline-1"])
def test_placement_requires_a_complete_analysis_identity(expected):
    timeline = Timeline()
    with pytest.raises(RuntimeError, match="no verified timeline identity"):
        dispatch({"cmd": "apply_checked", "expected_timeline": expected,
                  "proposals": [{"frame": 200, "color": "Green"}]}, timeline, Project(timeline))
    assert timeline.added == [] and timeline.deleted == []


@pytest.mark.parametrize("timeline_id,project_id", [(None, "project-1"), ("", "project-1"),
                                                   ("timeline-1", None), ("timeline-1", "")])
def test_placement_refuses_when_resolve_cannot_provide_ids(timeline_id, project_id):
    timeline = Timeline(timeline_id)
    with pytest.raises(RuntimeError, match="could not verify"):
        dispatch({"cmd": "apply_checked", "expected_timeline": IDENTITY,
                  "proposals": [{"frame": 200, "color": "Green"}]}, timeline, Project(timeline, project_id))
    assert timeline.added == [] and timeline.deleted == []


def test_renaming_the_original_timeline_keeps_placement_allowed():
    timeline = Timeline(name="Renamed after analysis")
    result = dispatch({"cmd": "apply_checked", "expected_timeline": IDENTITY,
                       "proposals": [{"frame": 200, "color": "Green"}]}, timeline, Project(timeline))
    assert result["placed"] == [200]


def test_legacy_unchecked_placement_is_refused_even_with_an_identity():
    timeline = Timeline()
    with pytest.raises(RuntimeError, match="Unchecked marker placement"):
        dispatch({"cmd": "apply", "expected_timeline": IDENTITY,
                  "proposals": [{"frame": 200, "color": "Green"}]}, timeline, Project(timeline))
    assert timeline.added == [] and timeline.deleted == []


def test_missing_or_failing_id_api_does_not_fall_back_to_the_name():
    timeline = Timeline()
    timeline.GetUniqueId = None
    assert read_identity(timeline, Project(timeline)) is None
    assert read_timeline(timeline, Project(timeline))["timeline_identity"] is None
    assert normalize_identity({"project_id": True, "timeline_id": "timeline-1"}) is None


def test_direct_bridge_checks_the_current_project_and_timeline_at_apply(monkeypatch):
    original = Timeline()
    other = Timeline("timeline-2")
    project = Project(original)

    class Resolve:
        def GetProjectManager(self):
            return self

        def GetCurrentProject(self):
            # The timeline changed after the preceding read request.
            return project

    class Requests:
        def __iter__(self):
            yield json.dumps({"id": 1, "cmd": "read"})
            project.timeline = other
            yield json.dumps({"id": 2, "cmd": "apply_checked", "expected_timeline": IDENTITY,
                              "proposals": [{"frame": 200, "color": "Green"}]})

    output = io.StringIO()
    monkeypatch.setattr("vispa_mp.resolve_bridge.sys.stdin", Requests())
    monkeypatch.setattr("vispa_mp.resolve_bridge.sys.stdout", output)
    serve(Resolve())
    read, denied = [json.loads(line) for line in output.getvalue().splitlines()]
    assert read["result"]["timeline_identity"] == IDENTITY
    assert denied["ok"] is False and "not the analyzed timeline" in denied["error"]
    assert original.added == other.added == original.deleted == other.deleted == []


def _apply(timeline, proposals, start=None, end=None):
    return dispatch({"cmd": "apply_checked", "expected_timeline": IDENTITY,
                     "proposals": proposals, "start": start, "end": end}, timeline, Project(timeline))


def test_resolve_requires_a_nonempty_name_and_the_bridge_supplies_it():
    timeline = Timeline()
    before = dict(timeline.GetMarkers())
    assert timeline.AddMarker(200, "Green", "", "", 1, "vispa-mp") is False
    assert timeline.GetMarkers() == before
    timeline.added.clear()
    result = _apply(timeline, [{"frame": 200, "color": "Green"}])
    assert result["placed"] == [200] and result["failed"] == []
    assert result["verified"] is True
    assert timeline.GetMarkers()[200] == {
        "color": "Green", "name": "marqueur-001", "note": "", "duration": 1, "customData": "vispa-mp"}
    assert timeline.GetMarkers()[10] == before[10]
    assert 100 not in timeline.GetMarkers()
    # GetMarkers/AddMarker use offsets, although the timeline starts at 01:00.
    assert timeline.GetStartFrame() == 86400
    assert timeline.AddMarker(86600, "Green", "Page", "", 1, "vispa-mp") is False


@pytest.mark.parametrize("api_return", [True, False, None, 1])
def test_no_success_is_claimed_without_a_recorded_marker(api_return):
    timeline = Timeline()

    def no_write(frame, color, name, note, duration, custom):
        timeline.added.append((frame, color, name, note, custom))
        return api_return

    timeline.AddMarker = no_write
    result = _apply(timeline, [{"frame": 200, "color": "Green"}, {"frame": 300, "color": "Blue"}])
    assert result["placed"] == []
    assert result["failed"] == result["skipped"] == [200, 300]
    assert result["verified"] is True
    assert result["requested"] == result["attempted"] == 2


def test_readback_not_the_api_boolean_proves_success():
    timeline = Timeline()
    add = timeline.AddMarker

    def false_after_write(*args):
        assert add(*args)
        return False

    timeline.AddMarker = false_after_write
    result = _apply(timeline, [{"frame": 200, "color": "Green"}])
    assert result["placed"] == [200]
    assert result["failed"] == []


@pytest.mark.parametrize("field,value", [("color", "Cyan"), ("name", ""), ("name", "Wrong"),
                                          ("customData", ""), ("customData", "vispa-mp-other")])
def test_recorded_marker_must_match_the_requested_data(field, value):
    timeline = Timeline()
    add = timeline.AddMarker

    def wrong_write(*args):
        assert add(*args)
        timeline.markers[200][field] = value
        return True

    timeline.AddMarker = wrong_write
    result = _apply(timeline, [{"frame": 200, "color": "Green"}])
    assert result["placed"] == []
    assert result["failed"] == [200]


def test_partial_placement_distinguishes_failures_manual_conflicts_and_outside_range():
    timeline = Timeline()
    manual = dict(timeline.markers[10])
    add = timeline.AddMarker

    def refuse_one(frame, *args):
        if frame == 300:
            timeline.added.append((frame, *args))
            return False
        return add(frame, *args)

    timeline.AddMarker = refuse_one
    result = _apply(timeline, [{"frame": frame, "color": "Blue"} for frame in (10, 200, 300, 400)], 0, 350)
    assert result["requested"] == 4 and result["attempted"] == 2
    assert result["placed"] == [200]
    assert result["failed"] == [300]
    assert result["outside"] == [400]
    assert result["skipped"] == [10, 300]
    assert timeline.markers[10] == manual


@pytest.mark.parametrize("proposals,start,end,outside", [
    ([], None, None, []),
    ([{"frame": 100, "color": "Green"}, {"frame": 350, "color": "Blue"}], 200, 300, [100, 350]),
])
def test_no_eligible_proposal_never_deletes_existing_markers(proposals, start, end, outside):
    timeline = Timeline()
    before = dict(timeline.markers)
    timeline.GetMarkers = lambda: pytest.fail("There is no marker write to plan or verify")
    result = _apply(timeline, proposals, start, end)
    assert result["outside"] == outside
    assert result["placed"] == result["deleted"] == result["failed"] == result["skipped"] == []
    assert result["requested"] == len(proposals) and result["attempted"] == 0
    assert timeline.added == timeline.deleted == []
    assert timeline.markers == before


def test_invalid_marker_color_is_rejected_before_existing_markers_are_deleted():
    timeline = Timeline()
    before = dict(timeline.markers)
    with pytest.raises(RuntimeError, match="unsupported marker color"):
        _apply(timeline, [{"frame": 200, "color": "Red"}])
    assert timeline.added == timeline.deleted == []
    assert timeline.markers == before


def test_readback_error_never_claims_the_write_was_verified():
    timeline = Timeline()
    reads = []

    def read_markers():
        reads.append(True)
        if len(reads) > 1:
            raise RuntimeError("Readback unavailable")
        return timeline.markers

    timeline.GetMarkers = read_markers
    with pytest.raises(RuntimeError, match="could not be verified"):
        _apply(timeline, [{"frame": 200, "color": "Green"}])
    assert 200 in timeline.markers  # The error must not imply that no edit happened.


def test_marker_numbers_follow_time_across_colors_and_repeat_without_duplicates():
    timeline = Timeline()
    proposals = [{"frame": 300, "color": "Cyan"}, {"frame": 10, "color": "Blue"},
                 {"frame": 200, "color": "Blue"}, {"frame": 400, "color": "Green"},
                 {"frame": 150, "color": "Green"}]
    result = _apply(timeline, proposals, 0, 400)
    assert result["placed"] == [150, 200, 300]
    assert result["outside"] == [400] and result["skipped"] == [10]
    assert [(frame, timeline.markers[frame]["name"]) for frame in result["placed"]] == [
        (150, "marqueur-001"), (200, "marqueur-002"), (300, "marqueur-003")]
    before = {frame: dict(marker) for frame, marker in timeline.markers.items()}
    assert _apply(timeline, proposals, 0, 400)["placed"] == [150, 200, 300]
    assert timeline.markers == before


def test_marker_numbers_skip_names_on_manual_and_outside_markers():
    timeline = Timeline()
    timeline.markers[10]["name"] = "marqueur-001"
    timeline.markers[100]["name"] = "Marqueur-003"
    before = {frame: dict(marker) for frame, marker in timeline.markers.items()}
    result = _apply(timeline, [{"frame": 300, "color": "Cyan"}, {"frame": 200, "color": "Green"}], 150, 400)
    assert result["placed"] == [200, 300]
    assert timeline.markers[200]["name"] == "marqueur-002"
    assert timeline.markers[300]["name"] == "marqueur-004"
    assert all(timeline.markers[frame] == marker for frame, marker in before.items())
    assert _apply(timeline, [{"frame": 200, "color": "Green"}, {"frame": 300, "color": "Cyan"}], 150, 400)["placed"] == [200, 300]
    assert timeline.markers[200]["name"] == "marqueur-002"
    assert timeline.markers[300]["name"] == "marqueur-004"


def test_marker_numbers_do_not_truncate_after_999():
    timeline = Timeline()
    timeline.markers = {frame: {"color": "Blue", "name": f"marqueur-{frame:03d}", "note": "",
                                "duration": 1, "customData": ""} for frame in range(1, 1000)}
    assert _apply(timeline, [{"frame": 1500, "color": "Cyan"}])["placed"] == [1500]
    assert timeline.markers[1500]["name"] == "marqueur-1000"

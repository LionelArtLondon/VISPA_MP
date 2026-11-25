from vispa_mp.markers import cue_warning, plan_apply
from vispa_mp.resolve_bridge import dispatch, read_timeline


class Timeline:
    def __init__(self):
        self.added = []
        self.deleted = []
        self.timecode = "01:00:00:00"

    def GetName(self):
        return "Episode"

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
        return {
            86410: {"color": "Blue", "name": "main", "note": "", "duration": 1, "customData": ""},
            86500: {"color": "Cyan", "name": "auto", "note": "old", "duration": 1, "customData": "vispa-mp"},
        }

    def GetMarkerCustomData(self, frame):
        return "vispa-mp" if int(frame) == 86500 else ""

    def DeleteMarkerAtFrame(self, frame):
        self.deleted.append(int(frame))
        return True

    def AddMarker(self, frame, color, name, note, duration, custom):
        self.added.append((int(frame), color, name, note, custom))
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


def test_only_video_1_and_audio_1_are_read_and_hand_markers_stay():
    snapshot = read_timeline(Timeline())
    assert snapshot["video_track_name"] == "V1"
    assert len(snapshot["video_clips"]) == 1
    assert snapshot["video_clips"][0]["path"] == "episode.mp4"
    assert len(snapshot["audio_clips"]) == 1
    assert snapshot["mark_in"] == 86500
    assert snapshot["markers"][0]["automatic"] is False
    assert snapshot["markers"][1]["automatic"] is True
    assert "CUE_SOURCE" in snapshot["warnings"][0]
    assert cue_warning(["CUE_SOURCE"]) == ""


def test_apply_deletes_only_automatic_markers_and_skips_a_hand_placed_frame():
    timeline = Timeline()
    result = dispatch({
        "cmd": "apply",
        "proposals": [
            {"frame": 86410, "color": "Blue", "name": "Corps", "note": "occupé"},
            {"frame": 86600, "color": "Green", "name": "Page", "note": "Début de page"},
        ],
    }, timeline)
    assert timeline.deleted == [86500]
    assert [item[0] for item in timeline.added] == [86600]
    assert timeline.added[0][1:] == ("Green", "", "", "vispa-mp")
    assert 86410 in result["skipped"]
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

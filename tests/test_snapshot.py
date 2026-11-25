"""An interlaced timeline: fields through the API, pictures in the timecode and the file."""

from vispa_mp.snapshot import OLD_SCRIPT, describe_rate, normalize, source_in_file_frames
from vispa_mp.timebase import format_timecode

# What Resolve 21 sent for the 25i test timeline (XDCAM 1080i50 file, 25 pictures a second).
INTERLACED = {
    "fps": 50, "interlaced": True, "playback_fps": 25, "script_version": 2,
    "start_frame": 180000, "start_timecode": "01:00:00:00", "warnings": [],
    "video_clips": [{"name": "episode.mov", "fps": 25, "start": 180000, "end": 259314,
                     "source_start": 0, "source_end": 79313}],
    "audio_clips": [],
}


def test_an_interlaced_timeline_shows_the_timecode_resolve_shows():
    snapshot = normalize(INTERLACED)
    assert snapshot["timecode_fps"] == 25
    base = {"fps": 50, "timecode_fps": 25, "start_frame": 180000, "start_timecode": "01:00:00:00"}
    # 8694 fields after the start: 4347 pictures, 173 s and 22 pictures.
    assert format_timecode(188694, base) == "01:02:53:22"
    assert format_timecode(188695, base) == "01:02:53:22"  # the second field of the same picture
    assert format_timecode(180049, base) == "01:00:00:24"
    assert format_timecode(180050, base) == "01:00:01:00"
    # The old reading counted 50 a second: frames up to 49, which Resolve never shows.
    assert format_timecode(188694, {"fps": 50, "start_frame": 180000, "start_timecode": "01:00:00:00"}) == "01:02:53:44"


def test_source_positions_given_in_fields_become_file_frames():
    snapshot = normalize(INTERLACED)
    clip = snapshot["video_clips"][0]
    assert (clip["source_start"], clip["source_end"]) == (0, 39657)
    assert not any("runs at" in line for line in snapshot["warnings"])
    trimmed = dict(INTERLACED["video_clips"][0], source_start=2000, source_end=81313)
    assert source_in_file_frames(trimmed, 50)["source_start"] == 1000
    same_rate = {"fps": 25, "start": 0, "end": 100, "source_start": 40, "source_end": 140}
    assert source_in_file_frames(same_rate, 25) == same_rate
    already_file_frames = {"fps": 25, "start": 0, "end": 100, "source_start": 40, "source_end": 90}
    assert source_in_file_frames(already_file_frames, 50) == already_file_frames
    assert describe_rate(snapshot) == "25i (50 fields) · video 25 fps"


def test_a_real_mismatch_and_an_old_script_are_told():
    progressive = dict(INTERLACED, fps=24, interlaced=False, playback_fps=24,
                       video_clips=[{"fps": 25, "start": 0, "end": 240, "source_start": 0, "source_end": 250}])
    warnings = normalize(progressive)["warnings"]
    assert any("Video 1 runs at 25 fps and the timeline at 24" in line for line in warnings)
    old = dict(INTERLACED)
    del old["script_version"], old["interlaced"], old["playback_fps"]
    assert OLD_SCRIPT in normalize(old)["warnings"]
    assert not any("runs at" in line for line in normalize(old)["warnings"])
    assert normalize(old)["timecode_fps"] == 50


def test_markers_come_back_in_timeline_frames_and_go_out_as_offsets(qapp):
    # Resolve counts a marker from the timeline's first frame: 8822 after a start at 180000.
    snapshot = normalize(dict(INTERLACED, markers=[{"frame": 8822, "automatic": False}]))
    assert snapshot["markers"][0]["frame"] == 188822
    from vispa_mp.ui import MainWindow
    window = MainWindow(client=None)
    window.snapshot = snapshot
    window.proposals = [{"frame": 188900, "color": "Green"}]
    window.analysis = {"range": [188822, 199480]}
    window.set_setting("use_in_out", True)
    payload = window.resolve_payload()
    assert payload["proposals"] == [{"frame": 8900, "color": "Green"}]
    assert (payload["start"], payload["end"]) == (8822, 19480)

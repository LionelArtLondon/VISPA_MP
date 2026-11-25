import numpy as np

from vispa_mp.shots import build_shots, find_cuts, grey_diff


def test_hard_cut_and_a_flash_too_short_to_count():
    black = np.zeros((36, 64, 3), dtype=np.uint8)
    white = np.full((36, 64, 3), 255, dtype=np.uint8)
    frames = [(index * 40_000, black if index < 5 else white) for index in range(10)]
    assert find_cuts(frames) == [200_000]

    flash = [(index * 40_000, black if index != 5 else white) for index in range(10)]
    assert find_cuts(flash) == [200_000]


def test_a_slow_change_is_not_a_cut():
    frames = []
    for index in range(8):
        picture = np.full((36, 64, 3), index, dtype=np.uint8)
        frames.append((index * 40_000, picture))
    assert find_cuts(frames) == []
    assert grey_diff(frames[0][1], frames[1][1]) < 12


def test_build_shots_splits_a_long_clip_and_keeps_timeline_frames():
    black = np.zeros((36, 64, 3), dtype=np.uint8)
    white = np.full((36, 64, 3), 255, dtype=np.uint8)
    strip = np.stack([black] * 5 + [white] * 5)
    clip = {"name": "episode", "start": 100, "end": 110, "source_start": 0, "source_end": 10,
            "path": "episode.mp4", "fps": 24}
    shots = build_shots([clip], [strip], 24)
    assert [shot["start"] for shot in shots] == [100, 105]
    assert shots[0]["opening"] is True
    assert shots[1]["opening"] is False
    assert shots[1]["cut_grey"] > 30
    assert shots[0]["frames"][0]["frame"] == 100
    assert shots[1]["frames"][-1]["source_frame"] == 9

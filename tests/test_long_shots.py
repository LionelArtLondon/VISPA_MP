"""Long shots need distinct, lasting compositions, rather than timed quotas."""

from copy import deepcopy

import numpy as np
import pytest

from vispa_mp.long_shots import decompose_shot
from vispa_mp.shots import build_shots


def pan_strip(count=240):
    x, y = np.arange(64)[None, :], np.arange(36)[:, None]
    pictures = []
    for number in range(count):
        shift = max(0, min(24, (number - count / 8) * 32 / count))
        grey = 120 + 60 * np.sin((x - shift) / 7) + 35 * np.cos((y + shift / 2) / 5)
        pictures.append(np.clip(grey, 0, 255).astype(np.uint8)[..., None].repeat(3, axis=2))
    return np.stack(pictures)


def build(strip, **changes):
    options = dict(split_long_shots=True, long_shot_seconds=4.3)
    options.update(changes)
    clip = dict(start=100, end=100 + len(strip), source_start=20, fps=24, path="episode.mp4")
    return build_shots([clip], [strip], 24, settings=options)


def measured(signatures, fps=24):
    return dict(start=0, end=len(signatures), opening=True, cut_grey=80, cut_colour=0.6,
                frames=[dict(frame=i, signature=list(signature), neighbor=0.2)
                        for i, signature in enumerate(signatures)])


def test_pan_without_a_hard_cut_has_several_contiguous_parts():
    strip = pan_strip()
    assert len(build(strip, split_long_shots=False)) == 1
    parts = build(strip)
    assert len(parts) > 1
    assert parts[0]["start"] == 100 and parts[-1]["end"] == 340
    assert all(left["end"] == right["start"] for left, right in zip(parts, parts[1:]))
    assert [frame["frame"] for part in parts for frame in part["frames"]] == list(range(100, 340))
    assert [frame["source_frame"] for part in parts for frame in part["frames"]] == list(range(20, 260))


@pytest.mark.parametrize("count", [48, 96, 240, 480])
def test_a_static_shot_never_gets_extra_parts_just_because_it_is_long(count):
    picture = pan_strip(24)[0]
    assert len(build(np.stack([picture] * count))) == 1


@pytest.mark.parametrize("threshold", [4.0, 4.3, 8.0])
def test_shots_at_or_below_the_threshold_are_left_intact(threshold):
    # 4 s at 25 fps, including a clear composition change.
    shot = measured([[60.0] * 64] * 50 + [[160.0] * 64] * 50)
    assert decompose_shot(shot, 25, dict(split_long_shots=True, long_shot_seconds=threshold)) == [shot]


def test_a_sustained_brightness_change_can_reveal_another_part():
    signatures = [[60 + min(80, max(0, i - 60))] * 64 for i in range(240)]
    shot = measured(signatures)
    original = deepcopy(shot)
    parts = decompose_shot(shot, 24, dict(split_long_shots=True, long_shot_seconds=4.3))
    assert len(parts) > 1
    assert shot == original
    assert parts[0]["opening"] and parts[0]["cut_grey"] == 80
    for part in parts[1:]:
        assert part["reframed"] and not part["opening"]
        assert part["cut_grey"] == part["cut_colour"] == part["cut_shape"] == 0
    assert all(part["parent_start"] == 0 and part["parent_end"] == 240 for part in parts)


def test_a_short_flash_does_not_create_a_persistent_composition():
    signatures = [[100.0] * 64 for _ in range(240)]
    for i in range(120, 123):
        signatures[i] = [220.0] * 64
    shot = measured(signatures)
    assert decompose_shot(shot, 24, dict(split_long_shots=True, long_shot_seconds=4.3)) == [shot]


def test_small_local_animation_does_not_create_another_camera_framing():
    signatures = []
    for i in range(240):
        signature = [80.0, 150.0] * 32
        signature[29:33] = [220.0 if (i // 16) % 2 else 30.0] * 4
        signatures.append(signature)
    shot = measured(signatures)
    assert decompose_shot(shot, 24, dict(split_long_shots=True, long_shot_seconds=4.3)) == [shot]


def test_decomposition_can_be_cancelled():
    shot = measured([[float(i)] * 64 for i in range(240)])
    with pytest.raises(InterruptedError, match="stopped"):
        decompose_shot(shot, 24, dict(split_long_shots=True, long_shot_seconds=4.3), cancel=lambda: True)

"""Editorial page order must not move video frames or rewrite marker roles."""

from copy import deepcopy

import pytest

from vispa_mp.markers import CORE, EXTRA, PAGE
from vispa_mp.page_layout import capture_layout, move_frame, move_frames, reconcile_layout


def proposal(frame, color=CORE):
    return {"frame": frame, "color": color, "image": f"source-{frame}.jpg", "note": "Kept pose"}


def automatic(item):
    return {"manual": False, "proposal": item}


def test_capture_keeps_page_ids_and_reading_order_while_excluding_manual_markers():
    pages = [
        {"id": 10, "items": [automatic(proposal(20)), {"manual": True, "frame": 15}, automatic(proposal(10, PAGE))]},
        {"id": 30, "items": [{"manual": True, "frame": 30}]},
        {"id": 40, "items": [automatic(proposal(40, EXTRA))]},
    ]
    before = deepcopy(pages)
    assert capture_layout(pages) == [{"id": 10, "frames": [20, 10]}, {"id": 40, "frames": [40]}]
    assert pages == before


def test_closed_page_drop_appends_a_page_start_without_changing_its_source_or_role():
    proposals = [proposal(10, PAGE), proposal(20), proposal(30, PAGE), proposal(40, EXTRA)]
    before = deepcopy(proposals)
    layout = [{"id": 10, "frames": [10, 20]}, {"id": 30, "frames": [30, 40]}]
    moved = move_frame(layout, 30, 10)
    assert moved == [{"id": 10, "frames": [10, 20, 30]}, {"id": 30, "frames": [40]}]
    assert layout == [{"id": 10, "frames": [10, 20]}, {"id": 30, "frames": [30, 40]}]
    assert proposals == before


def test_expanded_page_drop_inserts_between_two_images():
    layout = [{"id": 10, "frames": [10, 20, 30]}, {"id": 40, "frames": [40, 50]}]
    assert move_frame(layout, 50, 10, before_frame=20) == [
        {"id": 10, "frames": [10, 50, 20, 30]}, {"id": 40, "frames": [40]},
    ]


def test_reordering_inside_a_page_keeps_every_image_once():
    layout = [{"id": 10, "frames": [10, 20, 30, 40]}]
    assert move_frame(layout, 40, 10, 20) == [{"id": 10, "frames": [10, 40, 20, 30]}]
    assert move_frame(layout, 20, 10) == [{"id": 10, "frames": [10, 30, 40, 20]}]
    assert move_frame(layout, 20, 10, 20) == layout


def test_empty_source_page_disappears_without_changing_destination_id():
    layout = [{"id": 10, "frames": [10]}, {"id": 20, "frames": [20, 30]}]
    assert move_frame(layout, 10, 20, 30) == [{"id": 20, "frames": [20, 10, 30]}]


@pytest.mark.parametrize("frame,target,before", [(999, 10, None), (20, 999, None), (20, 10, 40),
                                                  (True, 10, None), (20, False, None), (20, 10, "10")])
def test_invalid_or_stale_drop_never_mutates_the_original(frame, target, before):
    layout = [{"id": 10, "frames": [10, 20]}, {"id": 40, "frames": [40]}]
    original = deepcopy(layout)
    with pytest.raises(ValueError):
        move_frame(layout, frame, target, before)
    assert layout == original


def test_reconcile_removes_deleted_frames_and_duplicates_without_resetting_manual_order():
    layout = [{"id": 10, "frames": [30, 10, 20]}, {"id": 40, "frames": [20, 40]}, {"id": 50, "frames": [50]}]
    proposals = [proposal(10), proposal(20), proposal(30), proposal(40)]
    original = deepcopy(layout)
    assert reconcile_layout(layout, proposals) == [
        {"id": 10, "frames": [30, 10, 20]}, {"id": 40, "frames": [40]},
    ]
    assert layout == original


def test_new_candidates_follow_source_neighbours_without_sorting_existing_reading_order():
    layout = [{"id": 10, "frames": [30, 10]}, {"id": 40, "frames": [40]}]
    proposals = [proposal(frame, PAGE if frame == 15 else CORE) for frame in (5, 10, 15, 20, 30, 35, 40, 50)]
    before = deepcopy(proposals)
    assert reconcile_layout(layout, proposals) == [
        {"id": 10, "frames": [30, 35, 5, 10, 15, 20]},
        {"id": 40, "frames": [40, 50]},
    ]
    assert proposals == before


def test_page_ids_survive_removing_their_original_start_image():
    assert reconcile_layout([{"id": 10, "frames": [10, 20]}], [proposal(20)]) == [{"id": 10, "frames": [20]}]


def test_new_layout_uses_chronological_pages_and_keeps_leading_extras_with_first_page():
    proposals = [proposal(50), proposal(40, PAGE), proposal(20, PAGE), proposal(10, EXTRA), proposal(30)]
    assert reconcile_layout([], proposals) == [
        {"id": 20, "frames": [10, 20, 30]}, {"id": 40, "frames": [40, 50]},
    ]


def test_empty_or_absent_layout_stays_distinct_from_an_empty_manual_review():
    assert reconcile_layout(None, [proposal(10)]) is None
    assert reconcile_layout([], []) == []
    assert reconcile_layout([{"id": 10, "frames": [10]}], []) == []


def test_reconcile_is_idempotent_and_moves_preserve_the_exact_proposal_set():
    layout = [{"id": 10, "frames": [10, 20]}, {"id": 30, "frames": [30, 40]}]
    proposals = [proposal(frame) for frame in (5, 10, 20, 30, 35, 40, 50)]
    reconciled = reconcile_layout(layout, proposals)
    assert reconcile_layout(reconciled, proposals) == reconciled
    for frame in (5, 10, 20, 30, 35, 40, 50):
        for page in reconciled:
            moved = move_frame(reconciled, frame, page["id"])
            assert sorted(frame for group in moved for frame in group["frames"]) == [5, 10, 20, 30, 35, 40, 50]


def test_reconcile_rejects_duplicate_page_ids_because_drop_targets_must_be_unambiguous():
    with pytest.raises(ValueError, match="page IDs"):
        reconcile_layout([{"id": 1, "frames": [10]}, {"id": 1, "frames": [20]}], [proposal(10), proposal(20)])


def test_batch_move_follows_existing_editorial_order_and_keeps_the_destination_id():
    layout = [{"id": 10, "frames": [30, 10]}, {"id": 20, "frames": [50, 20, 40]},
              {"id": 60, "frames": [60]}]
    original = deepcopy(layout)
    assert move_frames(layout, [60, 10, 30, 50], 20, 40) == [
        {"id": 20, "frames": [20, 30, 10, 50, 60, 40]},
    ]
    assert layout == original


@pytest.mark.parametrize("anchor,expected", [
    (20, [10, 20, 40, 30, 50]),
    (40, [10, 30, 20, 40, 50]),
    (None, [10, 30, 50, 20, 40]),
])
def test_batch_insertion_anchor_inside_selection_uses_next_remaining_image(anchor, expected):
    layout = [{"id": 10, "frames": [10, 20, 30, 40, 50]}]
    assert move_frames(layout, [40, 20], 10, anchor) == [{"id": 10, "frames": expected}]


@pytest.mark.parametrize("anchor", [20, 30, 40])
def test_contiguous_selection_dropped_on_itself_or_successor_is_a_noop(anchor):
    layout = [{"id": 10, "frames": [10, 20, 30, 40]}]
    result = move_frames(layout, [30, 20], 10, anchor)
    assert result == layout
    assert result is not layout
    assert result[0]["frames"] is not layout[0]["frames"]


def test_batch_can_move_every_image_into_one_of_its_source_pages():
    layout = [{"id": 10, "frames": [10, 20]}, {"id": 30, "frames": [30, 40]}]
    assert move_frames(layout, [40, 30, 20, 10], 30, 30) == [
        {"id": 30, "frames": [10, 20, 30, 40]},
    ]


@pytest.mark.parametrize("frames,target,anchor", [
    ([], 10, None), ([20, 20], 10, None), ([20, 999], 10, None),
    ([20], 999, None), ([20], 10, 40), ([True], 10, None),
    ([20, 10.0], 10, None), ([20, "10"], 10, None),
    ("20", 10, None), (20, 10, None), (None, 10, None),
    ([20], True, None), ([20], 10, False),
])
def test_batch_invalid_or_stale_member_rejects_the_whole_move(frames, target, anchor):
    layout = [{"id": 10, "frames": [10, 20]}, {"id": 40, "frames": [40]}]
    original = deepcopy(layout)
    with pytest.raises(ValueError):
        move_frames(layout, frames, target, anchor)
    assert layout == original

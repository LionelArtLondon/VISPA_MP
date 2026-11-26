"""The review's reading order travels without moving its source frames."""

from copy import deepcopy

import pytest

from tests.test_project import _review, _rewrite
from vispa_mp.project import load_project, save_project


@pytest.mark.parametrize("layout", [
    None,
    [],
    [{"id": 86412, "frames": [86412]}],
    [{"id": -(2 ** 40), "frames": [86412, 86402]}],
])
def test_page_layout_roundtrips_without_mutating_marker_frames(tmp_path, layout):
    review = _review(tmp_path)
    review["view"]["page_layout"] = deepcopy(layout)
    original = deepcopy(review)
    path = tmp_path / "reading-order.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "restored-cache")
    assert review == original
    assert restored["view"]["page_layout"] == layout
    assert [(item["frame"], item["color"]) for item in restored["proposals"]] == [
        (item["frame"], item["color"]) for item in original["proposals"]]


@pytest.mark.parametrize("layout", [
    {}, "pages", [None], [{}],
    [{"id": True, "frames": [86412]}],
    [{"id": 1.5, "frames": [86412]}],
    [{"id": "1", "frames": [86412]}],
    [{"id": 2 ** 63, "frames": [86412]}],
    [{"id": -(2 ** 63) - 1, "frames": [86412]}],
    [{"id": 1, "frames": []}],
    [{"id": 1, "frames": None}],
    [{"id": 1, "frames": [True]}],
    [{"id": 1, "frames": [86412.0]}],
    [{"id": 1, "frames": ["86412"]}],
    [{"id": 1, "frames": [2 ** 31]}],
    [{"id": 1, "frames": [86412, 86412]}],
    [{"id": 1, "frames": [86412]}, {"id": 1, "frames": [86402]}],
    [{"id": 1, "frames": [86412]}, {"id": 2, "frames": [86412]}],
])
def test_invalid_page_layout_is_rejected_before_restore(tmp_path, layout):
    path = tmp_path / "invalid-reading-order.vispamp"
    save_project(path, **_review(tmp_path))
    _rewrite(path, edit=lambda project: project["view"].update(page_layout=layout))
    with pytest.raises(ValueError, match="page arrangement"):
        load_project(path, tmp_path / "cache")


def test_stable_page_ids_support_selection_and_open_state_independent_of_frames(tmp_path):
    review = _review(tmp_path)
    page_id = -(2 ** 40)
    review["view"].update(page_layout=[{"id": page_id, "frames": [86412]}],
                          selected_page_id=page_id, open_pages=[page_id])
    path = tmp_path / "stable-page-id.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "cache")
    assert restored["view"]["selected_page_id"] == page_id
    assert restored["view"]["open_pages"] == [page_id]


def test_manual_page_order_is_saved_and_restored_without_reanalysis(qapp, tmp_path, monkeypatch):
    from tests.test_project_ui import _review as ui_review
    from vispa_mp.ui import MainWindow, item_frame

    original = ui_review(qapp, tmp_path)
    original._add_suggestion_marker(2)
    page_id = -(2 ** 40)
    original._page_layout = [{"id": page_id, "frames": [12, 2]}]
    original._fill()
    expected = [(item["frame"], item["color"]) for item in original.proposals]
    path = tmp_path / "manual-pages.vispamp"
    assert original.save_project_file(path)
    project = load_project(path, tmp_path / "restored-cache")
    assert project["view"]["page_layout"] == original._page_layout

    restored = MainWindow(client=None)
    monkeypatch.setattr(restored, "recompute", lambda: pytest.fail("Opening must keep the review"))
    restored._restore_project(project, deepcopy(original.snapshot), None, path)
    assert restored._page_layout == [{"id": page_id, "frames": [12, 2]}]
    assert len(restored.pages) == 1
    assert restored.pages[0]["id"] == page_id
    assert [item_frame(item) for item in restored.pages[0]["items"]] == [12, 2]
    assert [(item["frame"], item["color"]) for item in restored.proposals] == expected
    assert restored._project_dirty is False


def test_older_projects_reset_a_previous_sessions_manual_page_order(qapp, tmp_path):
    from tests.test_project_ui import _review as ui_review
    from vispa_mp.ui import MainWindow

    original = ui_review(qapp, tmp_path)
    path = tmp_path / "old-pages.vispamp"
    assert original.save_project_file(path)
    _rewrite(path, edit=lambda project: project["view"].pop("page_layout", None))
    project = load_project(path, tmp_path / "cache")
    restored = MainWindow(client=None)
    restored._page_layout = [{"id": -1, "frames": [2]}]
    restored._restore_project(project, deepcopy(original.snapshot), None, path)
    assert restored._page_layout is None
    assert [item["frame"] for item in restored.proposals] == [12]

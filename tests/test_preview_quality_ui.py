"""Display quality changes every review surface without rebuilding its review."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QComboBox
from shiboken6 import isValid

from tests.test_project import _rewrite
from tests.test_project_ui import _review, _semantic_proposals
from vispa_mp.comparison_ui import ComparisonWindow
from vispa_mp.project import load_project
from vispa_mp.strip_canvas import CanvasImage
from vispa_mp.ui import MainWindow


def settle(qapp):
    for _ in range(5):
        qapp.processEvents()


@pytest.fixture
def make_window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("vispa_mp.project_location.LOCATION_PATH", tmp_path / "locations.json")
    windows = []

    def create(mode="strip", detached=False, prepared=True):
        folder = tmp_path / f"review-{len(windows)}"
        folder.mkdir()
        window = _review(qapp, folder) if prepared else MainWindow(client=None)
        windows.append(window)
        window.resize(1600, 1000)
        window.show()
        window._set_mode(mode)
        if prepared:
            window._open_suggestions(12, False)
            if detached:
                window._detach_suggestions()
        settle(qapp)
        window._save_timer.stop()
        window._project_dirty = False
        return window

    yield create
    for window in reversed(windows):
        if not isValid(window):
            continue
        window.worker = None
        window._learning_job_busy = False
        window._ready = True
        window._project_dirty = False
        window._resolve_timer.stop()
        window._save_timer.stop()
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def _strip_cards(window):
    return tuple(window.thumb_layout.itemAt(index).widget() for index in range(window.thumb_layout.count()))


def _pictures(window):
    return (tuple(window.thumb_area.widget().findChildren(CanvasImage))
            + tuple(card._suggestion_picture for card in window._suggestion_cards.values()))


def _assert_quality(window, quality):
    assert window.preview_quality == quality
    assert window.preview_quality_box.currentText() == quality
    assert window.board.preview_quality == quality
    assert window.thumb_area.preview_quality == quality
    assert all(picture.preview_quality == quality for picture in _pictures(window))


def test_fresh_review_exposes_one_shared_medium_quality_control(make_window):
    window = make_window()
    assert isinstance(window.preview_quality_box, QComboBox)
    assert [window.preview_quality_box.itemText(index) for index in range(window.preview_quality_box.count())] == [
        "Low", "Medium", "High"]
    assert window.preview_quality_box.isVisible()
    assert window.preview_quality_box.parentWidget() is window.suggestions_button.parentWidget()
    assert _pictures(window)
    _assert_quality(window, "Medium")
    assert "preview_quality" not in window.settings()


@pytest.mark.parametrize("mode", ["strip", "board"])
@pytest.mark.parametrize("detached", [False, True])
def test_quality_changes_preserve_cards_cameras_sources_and_review_without_analysis(
        qapp, make_window, monkeypatch, mode, detached):
    window = make_window(mode, detached)
    window.set_review_cameras({"strip": {"zoom": 310.0, "center": [0.3, 0.7], "columns": 1},
                               "board": {"zoom": 2.2, "center": [0.4, 0.6]}})
    settle(qapp)
    cameras = deepcopy(window.get_review_cameras())
    strip_cards = _strip_cards(window)
    suggestions = dict(window._suggestion_cards)
    pictures = _pictures(window)
    pixmaps = [picture.picture.cacheKey() for picture in pictures]
    proposals, analysis = deepcopy(window.proposals), deepcopy(window.analysis)
    payload = deepcopy(window.resolve_payload())
    selection = (window.selected_frame, set(window._selected_keys), window.selected_page_id)
    originals = {frame["image"]: Path(frame["image"]).read_bytes()
                 for shot in window.analysis["shots"] for frame in shot["frames"]}
    undo_count = window.undo_stack.count()

    def forbidden(*_args, **_kwargs):
        pytest.fail("Changing preview quality must only redraw existing cached review images")

    for name in ("_fill", "recompute", "run_analysis", "_refresh_center", "_thumb", "_suggestion"):
        monkeypatch.setattr(window, name, forbidden)
    monkeypatch.setattr("vispa_mp.ui.analyze", forbidden)

    for quality in ("Low", "High", "Medium"):
        window.preview_quality_box.setCurrentText(quality)
        settle(qapp)
        _assert_quality(window, quality)
        assert _strip_cards(window) == strip_cards
        assert window._suggestion_cards == suggestions
        assert _pictures(window) == pictures
        assert [picture.picture.cacheKey() for picture in pictures] == pixmaps
        assert window.get_review_cameras() == cameras
        assert window.proposals == proposals and window.analysis == analysis
        assert window.resolve_payload() == payload
        assert (window.selected_frame, window._selected_keys, window.selected_page_id) == selection
        assert {path: Path(path).read_bytes() for path in originals} == originals
        assert window.undo_stack.count() == undo_count
    assert window._project_dirty


@pytest.mark.parametrize("busy", ["worker", "learning", "initializing"])
def test_busy_or_initializing_review_refuses_quality_changes_and_restores_the_combo(
        qapp, make_window, busy):
    window = make_window()
    before = deepcopy(window.proposals)
    if busy == "worker":
        window.worker = object()
    elif busy == "learning":
        window._learning_job_busy = True
    else:
        window._ready = False
    window.preview_quality_box.setCurrentText("High")
    settle(qapp)
    _assert_quality(window, "Medium")
    assert window.proposals == before
    assert not window._project_dirty


def test_quality_preference_is_used_by_the_next_window(make_window, user_settings):
    original = make_window()
    original.preview_quality_box.setCurrentText("Low")
    original.save_settings()
    assert json.loads(user_settings.read_text(encoding="utf-8"))["preview_quality"] == "Low"
    restored = make_window(prepared=False)
    _assert_quality(restored, "Low")
    assert "preview_quality" not in restored.settings()


@pytest.mark.parametrize("legacy", [False, True])
def test_project_restore_syncs_quality_without_reselecting_markers(
        qapp, make_window, tmp_path, monkeypatch, legacy):
    original = make_window("board")
    original.preview_quality_box.setCurrentText("High")
    semantic = _semantic_proposals(original.proposals)
    path = tmp_path / "quality-review.vispamp"
    assert original.save_project_file(path)
    if legacy:
        _rewrite(path, edit=lambda project: project["view"].pop("preview_quality"))
    project = load_project(path, tmp_path / "restored-cache")
    restored = make_window(prepared=False)
    restored.preview_quality_box.setCurrentText("Low")
    monkeypatch.setattr(restored, "recompute", lambda: pytest.fail("Loading must preserve reviewed marker choices"))
    monkeypatch.setattr("vispa_mp.ui.analyze", lambda *_args, **_kwargs:
                        pytest.fail("Loading preview quality must not run image analysis"))
    restored._restore_project(project, deepcopy(original.snapshot), None, path)
    restored._open_suggestions(12, False)
    settle(qapp)
    _assert_quality(restored, "Medium" if legacy else "High")
    assert _semantic_proposals(restored.proposals) == semantic
    assert not restored._project_dirty


def test_comparison_uses_the_captured_quality_for_both_views_and_keeps_it_independent(
        qapp, make_window):
    owner = make_window()
    owner.preview_quality_box.setCurrentText("High")
    variant = {"name": "MP standard rules", "proposals": deepcopy(owner.proposals), "warnings": [], "profile": None}
    view = owner._project_view()
    comparison = ComparisonWindow(owner, variant, owner.analysis, view)
    try:
        comparison.show()
        settle(qapp)
        assert comparison.view["preview_quality"] == "High"
        assert comparison.board.preview_quality == "High"
        assert comparison.strip.preview_quality == "High"
        assert comparison.strip_canvas.findChildren(CanvasImage)
        assert all(picture.preview_quality == "High"
                   for picture in comparison.strip_canvas.findChildren(CanvasImage))
        for mode in ("board", "strip"):
            comparison.set_mode(mode)
            settle(qapp)
            assert comparison.board.preview_quality == comparison.strip.preview_quality == "High"
        owner.preview_quality_box.setCurrentText("Low")
        assert comparison.view["preview_quality"] == "High"
        assert comparison.board.preview_quality == comparison.strip.preview_quality == "High"
    finally:
        comparison.close()
        if isValid(comparison):
            comparison.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

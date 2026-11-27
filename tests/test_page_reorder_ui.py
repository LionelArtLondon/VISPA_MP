"""Manual page order changes reading order while video marker positions stay put."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from vispa_mp.markers import CORE, EXTRA, NAMES, PAGE
from vispa_mp.project import load_project
from vispa_mp.review_drag import MarkerDragCard, marker_mime
from vispa_mp.ui import MainWindow, item_frame


IDENTITY = {"project_id": "project-order", "timeline_id": "timeline-order"}


def _proposal(frame, color):
    return {"frame": frame, "color": color, "name": NAMES[color], "note": NAMES[color],
            "rule": "page" if color == PAGE else "body", "image": "", "sharpness": 100,
            "mouth": 0.2, "cavity": 0.2, "teeth": 0, "strength": 0}


def _window(mode="strip", manual=False):
    window = MainWindow(client=None)
    window.set_setting("core_page_target", 0)
    window.set_setting("episode_minutes", 0)
    window.set_setting("action_extras", 0)
    window.snapshot = {
        "project_name": "Order review", "timeline_name": "Chapter", "timeline_identity": dict(IDENTITY),
        "fps": 24, "start_frame": 0, "end_frame": 100, "start_timecode": "00:00:00:00", "drop": False,
        "video_clips": [], "audio_clips": [], "markers": [{"frame": 15, "automatic": False}] if manual else [],
        "warnings": [],
    }
    window.analysis = {
        "project_name": "Order review", "timeline_name": "Chapter", "timeline_identity": dict(IDENTITY),
        "fps": 24, "timebase": {"fps": 24, "start_frame": 0, "start_timecode": "00:00:00:00", "drop": False},
        "shots": [{"start": 0, "end": 100, "frames": [
            {"frame": frame, "sharpness": 100, "image": "", "open_mouth": 0.2, "closed_mouth": 0.5}
            for frame in (10, 20, 25, 30, 40, 50, 60)]}],
        "manual_frames": [15] if manual else [], "utterances": [], "warnings": [],
    }
    window.proposals = [_proposal(frame, color) for frame, color in
                        ((10, PAGE), (20, CORE), (30, EXTRA), (40, PAGE), (50, CORE), (60, EXTRA))]
    window._fill()
    window._set_mode(mode)
    window._project_dirty = False
    return window


def _reading_order(window):
    return [(page["id"], [item_frame(item) for item in page["items"] if not item["manual"]])
            for page in window.pages if any(not item["manual"] for item in page["items"])]


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_a_page_start_can_finish_the_preceding_page_without_moving_its_video_marker(qapp, mode):
    window = _window(mode)
    source = deepcopy(window.proposals)
    before_resolve = deepcopy(window.resolve_payload())
    window.open_pages = set()  # Dropping on a collapsed page appends.

    assert window._move_marker_to_page(40, 10)

    assert _reading_order(window) == [(10, [10, 20, 30, 40]), (40, [50, 60])]
    assert window.proposals == source
    assert window.resolve_payload() == before_resolve
    assert window.selected_frame == 40 and window.selected_page_id == 10
    assert window._project_dirty is True
    assert window.mode == mode
    assert window._proposal(40)["color"] == PAGE
    hints = window.findChildren(QLabel)
    assert any("Manual page order" in label.text() and not label.isHidden() for label in hints)
    assert "Resolve keeps timeline order" in window.manual_order_bar.toolTip()


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_an_expanded_page_can_receive_an_image_between_two_existing_images(qapp, mode):
    window = _window(mode)
    window.open_pages = {10}
    assert window._move_marker_to_page(50, 10, before_frame=20)
    assert _reading_order(window) == [(10, [10, 50, 20, 30]), (40, [40, 60])]
    assert 10 in window.open_pages
    assert window.selected_page_id == 10


def test_images_can_be_reordered_in_the_same_page(qapp):
    window = _window()
    before = deepcopy(window.resolve_payload())
    assert window._move_marker_to_page(30, 10, before_frame=20)
    assert _reading_order(window)[0] == (10, [10, 30, 20])
    assert window.resolve_payload() == before


def test_a_lone_source_page_disappears_without_shifting_the_target_id(qapp):
    window = _window()
    window.proposals = [item for item in window.proposals if item["frame"] not in (20, 30)]
    window._fill()
    assert window._move_marker_to_page(10, 40, before_frame=50)
    assert _reading_order(window) == [(40, [40, 10, 50, 60])]
    assert window.selected_page_id == 40


@pytest.mark.parametrize("frame,target,before", [(999, 10, None), (20, 999, None), (20, 10, 50), (15, 40, None)])
def test_unknown_manual_or_stale_drop_is_a_noop(qapp, frame, target, before):
    window = _window(manual=True)
    proposals = deepcopy(window.proposals)
    pages = _reading_order(window)
    assert not window._move_marker_to_page(frame, target, before)
    assert window.proposals == proposals
    assert _reading_order(window) == pages
    assert window._page_layout is None
    assert window._project_dirty is False
    assert window.analysis["manual_frames"] == [15]


def test_reorder_is_blocked_during_a_worker_and_never_calls_resolve(qapp):
    window = _window()

    class NoRPC:
        def read(self):
            pytest.fail("Page arrangement must remain local")

        def apply(self, *args, **kwargs):
            pytest.fail("Page arrangement must not place markers")

        def seek(self, *args, **kwargs):
            pytest.fail("Page arrangement must not seek Resolve")

    window.client = NoRPC()
    before = _reading_order(window)
    window.worker = object()
    try:
        assert not window._move_marker_to_page(50, 10)
    finally:
        window.worker = None
    assert _reading_order(window) == before
    assert window._page_layout is None
    assert window._move_marker_to_page(50, 10)


def test_arranging_proposals_leaves_hand_placed_markers_read_only_and_unchanged(qapp):
    window = _window(manual=True)
    snapshot = deepcopy(window.snapshot)
    assert window._move_marker_to_page(50, 10, before_frame=20)
    assert window.snapshot == snapshot
    assert window.analysis["manual_frames"] == [15]
    manual_items = [item for page in window.pages for item in page["items"] if item["manual"]]
    assert manual_items == [{"manual": True, "frame": 15}]
    assert all(15 not in group["frames"] for group in window._page_layout)


def test_recalculation_reconciles_candidates_without_resetting_the_reading_order(qapp, monkeypatch):
    window = _window()
    assert window._move_marker_to_page(50, 10, before_frame=20)
    source = deepcopy(window.proposals)
    source.append(_proposal(25, CORE))
    monkeypatch.setattr("vispa_mp.ui.propose", lambda *_args: {"proposals": deepcopy(source), "warnings": []})
    window.recompute()
    assert _reading_order(window) == [(10, [10, 50, 20, 25, 30]), (40, [40, 60])]
    assert window._proposal(50)["frame"] == 50


def test_automatic_order_can_be_restored_without_changing_proposals(qapp):
    window = _window()
    source = deepcopy(window.proposals)
    assert window._move_marker_to_page(50, 10, before_frame=20)
    window._reset_page_layout()
    assert window._page_layout is None
    assert _reading_order(window) == [(10, [10, 20, 30]), (40, [40, 50, 60])]
    assert window.proposals == source


def test_a_new_analysis_does_not_inherit_another_reviews_page_order(qapp, monkeypatch):
    window = _window()
    source = deepcopy(window.proposals)
    assert window._move_marker_to_page(50, 10, before_frame=20)
    monkeypatch.setattr("vispa_mp.ui.propose", lambda *_args: {"proposals": deepcopy(source), "warnings": []})
    window.show_analysis(deepcopy(window.analysis))
    assert window._page_layout is None
    assert _reading_order(window) == [(10, [10, 20, 30]), (40, [40, 50, 60])]


def test_replacing_a_suggestion_keeps_its_manual_reading_position(qapp):
    window = _window()
    assert window._move_marker_to_page(50, 10, before_frame=20)
    window._choose_frame(20, False)
    window._open_suggestions(20, False)
    window._use_suggestion(25)
    assert _reading_order(window) == [(10, [10, 50, 25, 30]), (40, [40, 60])]
    assert window.selected_frame == 25 and window.selected_page_id == 10
    assert window._proposal(25)["origin_frame"] == 20


def test_deleting_an_arranged_image_keeps_the_remaining_page_order(qapp):
    window = _window()
    assert window._move_marker_to_page(50, 10, before_frame=20)
    window._delete_marker_proposal(20)
    assert _reading_order(window) == [(10, [10, 50, 30]), (40, [40, 60])]


def test_a_saved_review_restores_manual_page_order_and_original_resolve_positions(qapp, tmp_path, monkeypatch):
    original = _window("board")
    assert original._move_marker_to_page(50, 10, before_frame=20)
    order = _reading_order(original)
    payload = original.resolve_payload()
    path = tmp_path / "manual-order.vispamp"
    assert original.save_project_file(path)
    project = load_project(path, tmp_path / "cache")
    assert project["view"]["page_layout"] == original._page_layout
    restored = MainWindow(client=None)
    monkeypatch.setattr(restored, "recompute", lambda:
                        pytest.fail("Opening the review must not rebuild the user's choices"))
    restored._restore_project(project, deepcopy(original.snapshot), None, path)
    assert _reading_order(restored) == order
    assert restored.resolve_payload() == payload
    assert restored.mode == "board"
    assert restored._project_dirty is False


@pytest.mark.parametrize("label,color", [("Page start", PAGE), ("Core", CORE), ("Extra", EXTRA)])
def test_context_role_action_changes_its_target_instead_of_another_selected_image(qapp, label, color):
    window = _window()
    if color == CORE:
        window._proposal(20).update(color=EXTRA, name=NAMES[EXTRA])
        window._fill()
    window._choose_frame(50, False)
    before = deepcopy(window._proposal(50))
    action = next(action for action in window._marker_menu(20).actions() if action.text() == label)
    assert action.isEnabled()
    action.trigger()
    assert window._proposal(20)["color"] == color
    assert window._proposal(20)["name"] == NAMES[color]
    assert window._proposal(50) == before
    assert window._project_dirty is True


def test_role_changes_keep_an_already_manual_page_layout(qapp):
    window = _window()
    assert window._move_marker_to_page(50, 10, before_frame=20)
    layout = deepcopy(window._page_layout)
    window._set_proposal_color(50, EXTRA)
    assert window._page_layout == layout
    assert _reading_order(window) == [(10, [10, 50, 20, 30]), (40, [40, 60])]


def test_context_role_choice_survives_threshold_recalculation(qapp, monkeypatch):
    window = _window()
    source = deepcopy(window.proposals)
    window._set_proposal_color(20, EXTRA)
    monkeypatch.setattr("vispa_mp.ui.propose", lambda *_args: {"proposals": deepcopy(source), "warnings": []})
    window.recompute()
    assert window._proposal(20)["color"] == EXTRA
    assert window._proposal(20)["user_role"] is True


def test_adjust_uses_role_labels_instead_of_color_names(qapp):
    window = _window()
    labels = {label.text() for label in window.review_adjust.findChildren(QLabel)}
    assert {"Page start", "Core", "Extra"} <= labels
    assert not {"Green", "Blue", "Cyan"} & labels


def _send_move(widget, position, buttons):
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(position), QPointF(widget.mapToGlobal(position)),
                        Qt.MouseButton.NoButton, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


def _source_point(window, frame):
    if window.mode == "board":
        window.board.grab()  # Refresh the actual painted hit rectangles after pan/resize.
        rect = next(rect for rect, item in window.board._hits if item_frame(item) == frame)
        return window.board, rect.center()
    view = window.thumb_area
    card = view.widget().findChild(MarkerDragCard, f"thumb-{frame}-a")
    assert card is not None
    view.ensureWidgetVisible(card)
    point = card.picture.mapTo(view.widget(), card.picture.rect().center())
    return view.viewport(), view.mapFromScene(QPointF(point))


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_drag_from_the_central_view_reaches_the_real_page_drop_target(qapp, monkeypatch, mode):
    window = _window(mode)
    window.resize(1600, 900)
    window.show()
    window._choose_frame(40, False)
    qapp.processEvents()
    if mode == "strip":
        window._zoom_thumbs(3)
        qapp.processEvents()
        assert window.thumb_area.transform().m11() > 1

    calls, mime_refs = [], []

    class NoRPC:
        def read(self):
            pytest.fail("An editorial drag must not read Resolve")

        def apply(self, *args, **kwargs):
            pytest.fail("An editorial drag must not write markers")

        def seek(self, *args, **kwargs):
            pytest.fail("An editorial drag must not seek Resolve")

    window.client = NoRPC()
    original_proposals = deepcopy(window.proposals)
    original_payload = deepcopy(window.resolve_payload())

    def drop_on_the_first_page(widget, frame, token, pixmap, frames=None):
        # Replace the native OS drag loop, retaining the real source signal,
        # MainWindow transport owner, MIME validation, target geometry and drop.
        calls.append((widget, frame, token))
        assert widget is window
        assert frame == 40 and token == window._drag_token
        assert frames == [40]
        header = window._rows[10]["row"]
        global_point = header.mapToGlobal(header.rect().center())
        point = window.pages_panel.mapFromGlobal(global_point)
        mime = marker_mime(frame, token, frames=frames)
        mime_refs.append(mime)
        before_hover = deepcopy((window.proposals, window._page_layout, window._selected_keys,
                                 window.selected_frame, window.selected_page_id))
        enter = QDragEnterEvent(point, Qt.DropAction.MoveAction, mime,
                               Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        enter._test_mime = mime
        QApplication.sendEvent(window.pages_panel, enter)
        assert enter.isAccepted()
        assert window.pages_panel._drop_target_info[:2] == (10, None)
        assert window.pages_panel._drop_indicator.isHidden()
        assert header.property("dropTarget") is True
        hint = header.findChild(QLabel, "page-drop-hint-10")
        assert hint is not None and hint.isVisible()
        assert not hint.pixmap().isNull()
        assert (window.proposals, window._page_layout, window._selected_keys,
                window.selected_frame, window.selected_page_id) == before_hover
        drop = QDropEvent(QPointF(point), Qt.DropAction.MoveAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        drop._test_mime = mime
        QApplication.sendEvent(window.pages_panel, drop)
        assert drop.isAccepted()
        assert not header.property("dropTarget")
        assert hint.isHidden()
        return Qt.DropAction.MoveAction

    monkeypatch.setattr("vispa_mp.ui.start_marker_drag", drop_on_the_first_page)
    source, point = _source_point(window, 40)
    assert source.rect().contains(point)

    # The middle button still pans the view and must never start a marker drag.
    pan_before = (QPointF(window.board.offset) if mode == "board" else
                  window.thumb_area.mapToScene(window.thumb_area.viewport().rect().center()))
    QTest.mousePress(source, Qt.MouseButton.MiddleButton, pos=point)
    _send_move(source, point + QPoint(35, 22), Qt.MouseButton.MiddleButton)
    QTest.mouseRelease(source, Qt.MouseButton.MiddleButton, pos=point + QPoint(35, 22))
    pan_after = (QPointF(window.board.offset) if mode == "board" else
                 window.thumb_area.mapToScene(window.thumb_area.viewport().rect().center()))
    assert pan_after != pan_before
    assert calls == []
    assert window.proposals == original_proposals
    qapp.processEvents()

    # For Strip this enters the QGraphicsView viewport and is dispatched through
    # its transformed proxy to MarkerDragCard, rather than calling the card slot.
    source, point = _source_point(window, 40)
    delta = QPoint(QApplication.startDragDistance() + 18, 0)
    QTest.mousePress(source, Qt.MouseButton.LeftButton, pos=point)
    _send_move(source, point + delta, Qt.MouseButton.LeftButton)
    QTest.mouseRelease(source, Qt.MouseButton.LeftButton, pos=point + delta)
    assert calls == [(window, 40, window._drag_token)]
    assert _reading_order(window) == [(10, [10, 20, 30, 40]), (40, [50, 60])]
    assert window.proposals == original_proposals
    assert window._proposal(40)["color"] == PAGE  # The drop edits preview order, not the marker's role.
    assert window.resolve_payload() == original_payload
    assert window.pages_panel._drop_indicator.isHidden()
    assert not window.pages_panel._drop_scroll_timer.isActive()

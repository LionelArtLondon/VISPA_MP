"""Zoom is a view of fixed cards, rather than a request to rearrange them."""

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest

from vispa_mp.strip_canvas import CanvasImage, balanced_columns
from vispa_mp.ui import MainWindow


def _review(qapp, count=12):
    window = MainWindow()
    frames = [{"frame": index * 10, "sharpness": 100, "image": ""} for index in range(count)]
    window.analysis = {
        "fps": 24, "timebase": {"fps": 24, "start_frame": 0, "start_timecode": "00:00:00:00"},
        "shots": [{"start": 0, "end": count * 10, "frames": frames}], "manual_frames": [],
    }
    window.proposals = [dict(frame, color="Green" if index == 0 else "Blue", note="Core", rule="body")
                        for index, frame in enumerate(frames)]
    window._fill()
    window.resize(1600, 900)
    window.show()
    qapp.processEvents()
    return window


def _positions(window):
    layout = window.thumb_layout
    return {layout.itemAt(index).widget().objectName(): layout.getItemPosition(index)
            for index in range(layout.count())}


def _wheel(window, steps, point=None):
    viewport = window.thumb_area.viewport()
    point = point or viewport.rect().center()
    event = QWheelEvent(QPointF(point), QPointF(viewport.mapToGlobal(point)), QPoint(), QPoint(0, steps * 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    window.eventFilter(viewport, event)


def test_complete_rows_are_preferred_without_a_long_unreadable_row():
    assert balanced_columns(12, 900, 550) in (3, 4)
    assert balanced_columns(10, 900, 550) == 5
    assert balanced_columns(7, 900, 550) not in (1, 7)


def test_zoom_selection_resize_and_suggestions_never_recompose_the_strip(qapp):
    window = _review(qapp)
    original = _positions(window)
    geometry = {window.thumb_layout.itemAt(i).widget().objectName(): window.thumb_layout.itemAt(i).widget().geometry()
                for i in range(window.thumb_layout.count())}
    _wheel(window, 5)
    assert window._thumb_zoom is not None
    assert _positions(window) == original
    window._choose_frame(30, False)
    assert _positions(window) == original
    window.resize(1800, 720)
    qapp.processEvents()
    assert _positions(window) == original
    window._open_suggestions(30, False)
    qapp.processEvents()
    window.set_suggestions_height(350)
    qapp.processEvents()
    assert _positions(window) == original
    assert {window.thumb_layout.itemAt(i).widget().objectName(): window.thumb_layout.itemAt(i).widget().geometry()
            for i in range(window.thumb_layout.count())} == geometry
    _wheel(window, -30)
    assert window._thumb_zoom is None
    assert _positions(window) == original


def test_zoom_keeps_the_same_board_point_under_the_pointer(qapp):
    window = _review(qapp)
    viewport = window.thumb_area.viewport()
    point = QPoint(viewport.width() * 2 // 3, viewport.height() // 3)
    before = window.thumb_area.mapToScene(point)
    _wheel(window, 3, point)
    after = window.thumb_area.mapToScene(point)
    assert abs(before.x() - after.x()) < 3
    assert abs(before.y() - after.y()) < 3


def test_middle_drag_on_a_thumbnail_pans_without_changing_rows(qapp):
    window = _review(qapp)
    _wheel(window, 3)
    card = window.thumb_layout.itemAt(0).widget()
    picture = card.findChild(CanvasImage)
    local = picture.mapTo(window.thumb_area.widget(), picture.rect().center())
    point = window.thumb_area.mapFromScene(QPointF(local))
    window.thumb_area.ensureWidgetVisible(card)
    point = window.thumb_area.mapFromScene(QPointF(local))
    view = window.thumb_area.viewport()
    before = window.thumb_area.mapToScene(view.rect().center())
    arrangement = _positions(window)
    QTest.mousePress(view, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(view, point + QPoint(60, 35))
    QTest.mouseRelease(view, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, point + QPoint(60, 35))
    after = window.thumb_area.mapToScene(view.rect().center())
    assert before != after
    assert _positions(window) == arrangement


def test_zoomed_click_and_double_click_keep_the_existing_review_actions(qapp):
    window = _review(qapp)
    _wheel(window, 3)
    card = window.thumb_layout.itemAt(4).widget()
    window.thumb_area.ensureWidgetVisible(card)
    local = card.mapTo(window.thumb_area.widget(), card.rect().center())
    point = window.thumb_area.mapFromScene(QPointF(local))
    view = window.thumb_area.viewport()
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    assert window.selected_frame == 40
    QTest.mouseDClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    assert window._suggestions_open
    assert window.suggestion_area.isVisible()


def test_each_wheel_step_still_zooms_a_small_fitted_arrangement(qapp):
    window = _review(qapp, count=72)
    window._open_suggestions(0, False)
    window.set_suggestions_height(4000)
    for _ in range(4):
        qapp.processEvents()
    before = window.thumb_area.transform().m11()
    for _ in range(6):
        _wheel(window, 1)
        after = window.thumb_area.transform().m11()
        assert after > before
        before = after


def test_selecting_at_fit_does_not_recentre_a_panned_arrangement(qapp):
    window = _review(qapp)
    view = window.thumb_area
    view.horizontalScrollBar().setValue(view.horizontalScrollBar().value() + 70)
    before = view.mapToScene(view.viewport().rect().center())
    window._choose_frame(30, False)
    after = view.mapToScene(view.viewport().rect().center())
    assert before == after

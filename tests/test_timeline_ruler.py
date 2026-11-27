"""Timeline navigation changes its visible window without changing marker choices."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from vispa_mp.timeline_ruler import TimelineRuler


@pytest.fixture
def ruler(qapp):
    widget = TimelineRuler()
    widget.resize(800, 94)
    widget.set_view(0, 2400, [(600, "Green"), (1200, "Blue")], 900,
                    {"fps": 24, "start_frame": 0, "start_timecode": "00:00:00:00"},
                    [(0, 1200), (1200, 2400)])
    widget.show()
    qapp.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


def wheel(widget, steps, x=None, *, pixels=0):
    point = QPointF(widget.width() / 2 if x is None else x, 44)
    event = QWheelEvent(point, QPointF(widget.mapToGlobal(point.toPoint())), QPoint(0, pixels),
                        QPoint(0, round(steps * 120)), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


def middle_pan(widget, delta):
    point = QPoint(widget.width() // 2, 45)
    QTest.mousePress(widget, Qt.MouseButton.MiddleButton, pos=point)
    target = point + QPoint(delta, 0)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(target), QPointF(widget.mapToGlobal(target)),
                       Qt.MouseButton.NoButton, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, move)
    QTest.mouseRelease(widget, Qt.MouseButton.MiddleButton, pos=target)


def visible(widget):
    return widget.view_start, widget.view_end


@pytest.mark.parametrize("fps,origin", [(23.976, 0), (24, 86400), (25, 90000), (29.97, 108000), (50, 180000)])
def test_wheel_zoom_keeps_the_absolute_timeline_position_under_the_pointer(ruler, fps, origin):
    ruler.set_view(origin, origin + 2400, [], origin + 900,
                   {"fps": fps, "start_frame": origin, "start_timecode": "01:00:00:00"})
    x = ruler.PAD + ruler._track_width() * 0.37
    before = ruler._position_at(x)
    moves, choices = [], []
    ruler.moved.connect(moves.append)
    ruler.chosen.connect(choices.append)

    wheel(ruler, 4, x)

    assert ruler._position_at(x) == pytest.approx(before)
    assert ruler.view_end - ruler.view_start == pytest.approx(2400 / 1.25 ** 4)
    assert ruler.start == origin and ruler.end == origin + 2400
    assert ruler.playhead == origin + 900
    assert moves == choices == []


def test_middle_drag_pans_in_the_drag_direction_and_clamps_to_the_source(ruler):
    moves, choices = [], []
    ruler.moved.connect(moves.append)
    ruler.chosen.connect(choices.append)
    wheel(ruler, 5)
    before = visible(ruler)
    middle_pan(ruler, 70)
    assert ruler.view_start < before[0]
    assert ruler.view_end - ruler.view_start == pytest.approx(before[1] - before[0])
    middle_pan(ruler, 10000)
    assert ruler.view_start == ruler.start
    middle_pan(ruler, -10000)
    assert ruler.view_end == ruler.end
    assert ruler.playhead == 900 and moves == choices == []
    assert ruler._pan is None


def test_zoom_is_bounded_by_one_frame_and_the_whole_source(ruler):
    wheel(ruler, 10000)
    assert ruler.view_end - ruler.view_start == pytest.approx(1.0)
    assert ruler.start <= ruler.view_start < ruler.view_end <= ruler.end
    wheel(ruler, 10000)
    assert ruler.view_end - ruler.view_start == pytest.approx(1.0)
    wheel(ruler, -10000)
    assert visible(ruler) == (float(ruler.start), float(ruler.end))
    middle_pan(ruler, 50)
    assert visible(ruler) == (float(ruler.start), float(ruler.end))


@pytest.mark.parametrize("x", [-10000, 0, 12, 400, 788, 800, 10000])
def test_every_click_stays_inside_the_exclusive_source_end(ruler, x):
    ruler.set_view(90000, 90001, [(90000, "Green")], 90000, {"fps": 25, "start_frame": 90000})
    wheel(ruler, 40, x)
    middle_pan(ruler, 200)
    assert ruler._frame_at(x) == 90000
    assert visible(ruler) == (90000.0, 90001.0)


def test_zoomed_right_boundary_and_invisible_pins_are_not_selectable(ruler):
    ruler._set_visible(500, 500)
    ruler.markers = [(499, "Blue"), (1000, "Cyan")]
    assert ruler._frame_at(ruler.width() - ruler.PAD) == 999
    assert ruler._frame_at(-1000) == 500
    assert ruler._pin_at(ruler._x_of(499)) is None
    assert ruler._pin_at(ruler._x_of(1000)) is None


def test_marker_and_playhead_updates_leave_the_visible_range_unchanged(ruler):
    wheel(ruler, 4)
    middle_pan(ruler, 30)
    before = visible(ruler)
    ruler.set_view(ruler.start, ruler.end, [(700, "Cyan"), (1500, "Blue")], 700,
                   deepcopy(ruler.timebase), [(0, 2400)])
    ruler.set_playhead(1500)

    assert visible(ruler) == before
    assert ruler.markers == [(700, "Cyan"), (1500, "Blue")]
    assert ruler.pages == [(0, 2400)]
    assert ruler.playhead == 1500


@pytest.mark.parametrize("change", ["start", "end", "fps", "timecode", "source_key"])
def test_source_range_or_timebase_changes_reset_the_visible_range(ruler, change):
    ruler.set_view(0, 2400, [], 900, ruler.timebase, source_key="chapter-a")
    wheel(ruler, 5)
    first, last, base, source = ruler.start, ruler.end, deepcopy(ruler.timebase), "chapter-a"
    if change == "start":
        first = 100
    elif change == "end":
        last = 3000
    elif change == "fps":
        base["fps"] = 25
    elif change == "timecode":
        base["start_timecode"] = "01:00:00:00"
    else:
        source = "chapter-b"
    ruler.set_view(first, last, [], 900, base, source_key=source)

    assert visible(ruler) == (float(first), float(last))
    assert ruler.playhead == 900


def test_mutating_a_callers_timebase_cannot_silently_change_the_rulers_source(ruler):
    base = {"fps": 24, "start_frame": 0}
    ruler.set_view(0, 2400, [], 900, base)
    wheel(ruler, 3)
    base["fps"] = 25
    assert ruler.timebase["fps"] == 24
    ruler.set_view(0, 2400, [], 900, base)
    assert visible(ruler) == (0.0, 2400.0)


def test_pin_click_selects_its_exact_frame_after_zoom(ruler):
    wheel(ruler, 3, ruler._x_of(600))
    moves, choices = [], []
    ruler.moved.connect(moves.append)
    ruler.chosen.connect(choices.append)
    top, height = ruler._track()
    point = QPoint(round(ruler._x_of(600)), top + height // 2)
    QTest.mouseClick(ruler, Qt.MouseButton.LeftButton, pos=point)

    assert moves == [600] and choices == [600]
    assert ruler.playhead == 600


def test_blank_scrub_changes_the_playhead_without_selecting_a_marker(ruler):
    wheel(ruler, 2)
    choices, moves = [], []
    ruler.chosen.connect(choices.append)
    ruler.moved.connect(moves.append)
    point = QPoint(320, 80)
    QTest.mousePress(ruler, Qt.MouseButton.LeftButton, pos=point)
    target = QPoint(ruler.width() + 1000, 80)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(target), QPointF(ruler.mapToGlobal(target)),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(ruler, move)
    QTest.mouseRelease(ruler, Qt.MouseButton.LeftButton, pos=target)

    assert moves[0] == ruler._frame_at(point.x())
    assert moves[-1] == ruler._frame_at(target.x())
    assert ruler.start <= ruler.playhead < ruler.end
    assert choices == [] and not ruler._drag


@pytest.mark.parametrize("pin", [False, True])
def test_context_menu_moves_to_the_exact_point_or_pin_and_reports_global_position(ruler, pin):
    wheel(ruler, 3, ruler._x_of(600))
    point = QPoint(round(ruler._x_of(600)) + 3, 45) if pin else QPoint(351, 80)
    expected = 600 if pin else ruler._frame_at(point.x())
    global_point = ruler.mapToGlobal(point)
    requests, choices, moves = [], [], []
    ruler.context_requested.connect(lambda frame, position: requests.append((frame, position)))
    ruler.chosen.connect(choices.append)
    ruler.moved.connect(moves.append)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, global_point)
    QApplication.sendEvent(ruler, event)

    assert requests == [(expected, global_point)]
    assert moves == [expected] and choices == []
    assert ruler.playhead == expected


@pytest.mark.parametrize("gesture", ["method", "alias", "middle", "left_blank"])
def test_fit_restores_the_source_without_changing_the_playhead_or_selection(ruler, gesture):
    wheel(ruler, 5)
    moves, choices = [], []
    ruler.moved.connect(moves.append)
    ruler.chosen.connect(choices.append)
    if gesture == "method":
        ruler.fit_timeline()
    elif gesture == "alias":
        ruler.fit_view()
    else:
        button = Qt.MouseButton.MiddleButton if gesture == "middle" else Qt.MouseButton.LeftButton
        QTest.mouseDClick(ruler, button, pos=QPoint(320, 80))

    assert visible(ruler) == (0.0, 2400.0)
    assert ruler.playhead == 900 and moves == choices == []


def test_fractional_wheel_and_pixel_scroll_support_trackpads(ruler):
    before = ruler.view_end - ruler.view_start
    wheel(ruler, 0.5)
    assert ruler.view_end - ruler.view_start == pytest.approx(before / 1.25 ** 0.5)
    before = ruler.view_end - ruler.view_start
    wheel(ruler, 0, pixels=20)
    assert ruler.view_end - ruler.view_start == pytest.approx(before / 1.25 ** 0.5)


def test_resize_large_timeline_and_both_modes_keep_valid_readable_geometry(ruler, qapp):
    origin = 2_000_000_000
    ruler.set_view(origin, origin + 2_000_000, [(origin + 500_000, "Cyan")], origin + 250_000,
                   {"fps": 29.97, "start_frame": origin, "start_timecode": "01:00:00;00", "drop": True})
    wheel(ruler, 8)
    before = visible(ruler)
    for compact in (True, False):
        ruler.set_compact(compact)
        assert ruler.height() == 94 and ruler._track() == (34, 24)
        for width in (1, 120, 1600):
            ruler.resize(width, 94)
            qapp.processEvents()
            assert visible(ruler) == before
            assert ruler.start <= ruler._frame_at(width) < ruler.end
            assert not ruler.grab().isNull()


@pytest.mark.parametrize("base,offset,expected", [
    ({"fps": 24, "start_frame": 86400, "start_timecode": "01:00:00:00"}, 24, "01:00:01:00"),
    ({"fps": 29.97, "start_frame": 108000, "start_timecode": "01:00:00;00", "drop": True}, 30, "01:00:01;00"),
    ({"fps": 50, "timecode_fps": 25, "start_frame": 180000, "start_timecode": "01:00:00:00"}, 50, "01:00:01:00"),
])
def test_timecodes_keep_source_origin_drop_frame_and_interlaced_rates(ruler, base, offset, expected):
    origin = base["start_frame"]
    ruler.set_view(origin, origin + 2400, [], origin + offset, base)
    assert ruler._timecode(origin + offset) == expected

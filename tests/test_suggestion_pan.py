"""Middle-button panning of the candidate strip preserves review actions."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget

from vispa_mp.review_panes import SuggestionArea
from tests.test_suggestions_resize import _open, _settle


def _area(qapp):
    area = SuggestionArea()
    area.resize(360, 160)
    area.setWidgetResizable(True)
    host = QWidget()
    host.setFixedSize(1400, 120)
    area.setWidget(host)
    card = QFrame(host)
    card.setGeometry(300, 5, 180, 100)
    picture = QLabel("picture", card)
    picture.setGeometry(0, 0, 180, 60)
    label = QLabel("caption", card)
    label.setGeometry(0, 60, 180, 40)
    area.show()
    qapp.processEvents()
    area.horizontalScrollBar().setValue(200)
    return area, {"viewport": area.viewport(), "host": host, "card": card,
                  "picture": picture, "label": label}


def _move(area, global_position, buttons=Qt.MouseButton.MiddleButton):
    viewport = area.viewport()
    local = viewport.mapFromGlobal(global_position)
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(local), QPointF(global_position),
                        Qt.MouseButton.NoButton, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewport, event)


@pytest.mark.parametrize("surface", ["viewport", "host", "card", "picture", "label"])
def test_middle_drag_scrolls_the_strip_from_every_surface(qapp, surface):
    area, widgets = _area(qapp)
    target = widgets[surface]
    position = QPoint(320, 30) if surface == "host" else QPoint(20, 20)
    origin = target.mapToGlobal(position)
    QTest.mousePress(target, Qt.MouseButton.MiddleButton, pos=position)
    assert area._pan_origin is not None
    assert area.viewport().cursor().shape() == Qt.CursorShape.ClosedHandCursor
    _move(area, origin - QPoint(80, 0))
    assert area.horizontalScrollBar().value() == 280
    _move(area, origin + QPoint(60, 0))
    assert area.horizontalScrollBar().value() == 140
    QTest.mouseRelease(area.viewport(), Qt.MouseButton.MiddleButton, pos=QPoint(20, 20))
    assert area._pan_origin is None
    assert area.viewport().cursor().shape() != Qt.CursorShape.ClosedHandCursor
    area.hide()


def test_pan_is_clamped_and_release_outside_finishes_the_grab(qapp):
    area, widgets = _area(qapp)
    position = QPoint(30, 30)
    origin = widgets["picture"].mapToGlobal(position)
    area.viewport().setCursor(Qt.CursorShape.CrossCursor)
    QTest.mousePress(widgets["picture"], Qt.MouseButton.MiddleButton, pos=position)
    _move(area, origin - QPoint(10000, 0))
    assert area.horizontalScrollBar().value() == area.horizontalScrollBar().maximum()
    _move(area, origin + QPoint(10000, 0))
    assert area.horizontalScrollBar().value() == 0
    QTest.mouseRelease(area.viewport(), Qt.MouseButton.MiddleButton, pos=QPoint(-120, -50))
    assert area._pan_origin is None
    assert QWidget.mouseGrabber() is not area.viewport()
    assert area.viewport().cursor().shape() == Qt.CursorShape.CrossCursor
    area.hide()


def test_newly_created_nested_children_also_start_a_pan(qapp):
    area, widgets = _area(qapp)
    nested = QWidget(widgets["card"])
    nested.setGeometry(0, 0, 100, 80)
    label = QLabel("new", nested)
    label.setGeometry(0, 0, 80, 40)
    nested.show()
    label.show()
    qapp.processEvents()
    origin = label.mapToGlobal(QPoint(10, 10))
    QTest.mousePress(label, Qt.MouseButton.MiddleButton, pos=QPoint(10, 10))
    _move(area, origin - QPoint(55, 0))
    assert area.horizontalScrollBar().value() == 255
    QTest.mouseRelease(area.viewport(), Qt.MouseButton.MiddleButton, pos=QPoint(10, 10))
    area.hide()


def test_left_and_right_clicks_reach_the_card_and_do_not_pan(qapp):
    area, widgets = _area(qapp)
    received = []
    widgets["card"].mousePressEvent = lambda event: received.append(event.button())
    for button in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
        QTest.mouseClick(widgets["card"], button, pos=QPoint(20, 20))
    assert received == [Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton]
    assert area._pan_origin is None
    assert area.horizontalScrollBar().value() == 200
    area.hide()


@pytest.mark.parametrize("mode", ["strip", "board"])
def test_dragging_a_suggestion_image_keeps_the_review_choices(qapp, mode):
    window = _open(qapp, mode)
    window.set_suggestions_height(340)
    _settle(qapp)
    area = window.suggestion_area
    maximum = area.horizontalScrollBar().maximum()
    assert maximum > 0
    start = maximum // 4
    distance = min(60, maximum - start)
    area.horizontalScrollBar().setValue(start)
    picture = next(iter(window._suggestion_cards.values()))._suggestion_picture
    before = deepcopy(window.proposals)
    selected = window.selected_frame
    origin = picture.mapToGlobal(QPoint(80, 40))
    QTest.mousePress(picture, Qt.MouseButton.MiddleButton, pos=QPoint(80, 40))
    _move(area, origin - QPoint(distance, 0))
    assert area.horizontalScrollBar().value() == start + distance
    QTest.mouseRelease(area.viewport(), Qt.MouseButton.MiddleButton, pos=QPoint(10, 10))
    assert window.proposals == before
    assert window.selected_frame == selected
    assert window._preview is None
    window.hide()


def test_losing_the_button_or_hiding_cancels_pan_and_preserves_resize_signal(qapp):
    area, widgets = _area(qapp)
    emitted = []
    area.viewport_resized.connect(lambda: emitted.append(True))
    origin = widgets["picture"].mapToGlobal(QPoint(10, 10))
    QTest.mousePress(widgets["picture"], Qt.MouseButton.MiddleButton, pos=QPoint(10, 10))
    _move(area, origin - QPoint(30, 0), Qt.MouseButton.NoButton)
    assert area._pan_origin is None
    assert area.horizontalScrollBar().value() == 200
    QTest.mousePress(widgets["picture"], Qt.MouseButton.MiddleButton, pos=QPoint(10, 10))
    area.hide()
    assert area._pan_origin is None
    assert QWidget.mouseGrabber() is not area.viewport()
    area.show()
    area.resize(400, 180)
    for _ in range(3):
        qapp.processEvents()
    assert emitted
    area.hide()

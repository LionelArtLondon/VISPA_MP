"""Range-selection gestures never turn into drags or suggestion activation."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout

from tests.test_page_reorder_ui import _proposal
from tests.test_review_drag import _move
from vispa_mp.markers import CORE, PAGE
from vispa_mp.review_drag import MarkerDragCard, PageMarkerRow
from vispa_mp.ui import PageBoard, item_frame


SHIFT = Qt.KeyboardModifier.ShiftModifier
CTRL_SHIFT = SHIFT | Qt.KeyboardModifier.ControlModifier


@pytest.fixture
def widgets(qapp):
    created = []
    yield created
    for widget in created:
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


@pytest.mark.parametrize("modifiers", [SHIFT, CTRL_SHIFT])
@pytest.mark.parametrize("manual", [False, True])
def test_shift_on_a_card_emits_only_its_range_request(qapp, widgets, modifiers, manual):
    card = MarkerDragCard(123, manual=manual)
    widgets.append(card)
    card.setProperty("multiSelected", True)
    card.resize(200, 100)
    card.show()
    qapp.processEvents()
    clicks, additive, ranges, drags, opens = [], [], [], [], []
    card.clicked.connect(lambda: clicks.append(True))
    card.additive_clicked.connect(lambda: additive.append(True))
    card.range_clicked.connect(ranges.append)
    card.drag_requested.connect(drags.append)
    card.opened.connect(lambda: opens.append(True))
    point = QPoint(20, 20)
    QTest.mousePress(card, Qt.MouseButton.LeftButton, modifiers, pos=point)
    assert ranges == [bool(modifiers & Qt.KeyboardModifier.ControlModifier)]
    _move(card, point, QPoint(QApplication.startDragDistance() + 20, 0))
    QTest.mouseRelease(card, Qt.MouseButton.LeftButton, modifiers, pos=point)
    assert clicks == additive == drags == []
    assert len(ranges) == 1
    QTest.mouseDClick(card, Qt.MouseButton.LeftButton, modifiers, pos=point)
    assert opens == []
    assert len(ranges) == 1


def make_board(qapp, widgets):
    board = PageBoard()
    widgets.append(board)
    items = [{"manual": False, "proposal": _proposal(10, PAGE)},
             {"manual": True, "frame": 15},
             {"manual": False, "proposal": _proposal(20, CORE)}]
    board.resize(640, 800)
    board.set_page(items, (148, 210), 10, False,
                   selected_keys={(10, False), (15, True), (20, False)})
    board.show()
    qapp.processEvents()
    board.grab()
    return board


@pytest.mark.parametrize("modifiers", [SHIFT, CTRL_SHIFT])
@pytest.mark.parametrize("manual", [False, True])
def test_shift_on_board_emits_only_its_range_request(qapp, widgets, modifiers, manual):
    board = make_board(qapp, widgets)
    frame = 15 if manual else 20
    point = next(rect.center() for rect, item in board._hits
                 if item_frame(item) == frame and bool(item["manual"]) == manual)
    choices, additive, ranges, drags, opens = [], [], [], [], []
    board.chosen.connect(lambda *args: choices.append(args))
    board.additive_chosen.connect(lambda *args: additive.append(args))
    board.range_chosen.connect(lambda *args: ranges.append(args))
    board.drag_requested.connect(drags.append)
    board.opened.connect(lambda *args: opens.append(args))
    QTest.mousePress(board, Qt.MouseButton.LeftButton, modifiers, pos=point)
    assert ranges == [(frame, manual, bool(modifiers & Qt.KeyboardModifier.ControlModifier))]
    _move(board, point, QPoint(QApplication.startDragDistance() + 20, 0))
    QTest.mouseRelease(board, Qt.MouseButton.LeftButton, modifiers, pos=point)
    assert choices == additive == drags == []
    assert len(ranges) == 1
    QTest.mouseDClick(board, Qt.MouseButton.LeftButton, modifiers, pos=point)
    assert opens == []
    assert len(ranges) == 1


@pytest.mark.parametrize("modifiers", [SHIFT, CTRL_SHIFT])
def test_shift_on_sidebar_row_keeps_the_button_click_and_blocks_drag(qapp, widgets, modifiers):
    row = PageMarkerRow(123)
    widgets.append(row)
    layout = QVBoxLayout(row)
    button = QPushButton("Marker")
    layout.addWidget(button)
    row.watch_drag(button)
    row.resize(300, 100)
    row.show()
    qapp.processEvents()
    clicks, drags = [], []
    button.clicked.connect(lambda: clicks.append(True))
    row.drag_requested.connect(drags.append)
    point = button.rect().center()
    QTest.mousePress(button, Qt.MouseButton.LeftButton, modifiers, pos=point)
    _move(button, point, QPoint(QApplication.startDragDistance() + 20, 0))
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton, modifiers, pos=point)
    assert clicks == [True]
    assert drags == []


def test_plain_board_click_still_defers_group_collapse_until_release(qapp, widgets):
    board = make_board(qapp, widgets)
    point = next(rect.center() for rect, item in board._hits if item_frame(item) == 20)
    choices, ranges, drags = [], [], []
    board.chosen.connect(lambda *args: choices.append(args))
    board.range_chosen.connect(lambda *args: ranges.append(args))
    board.drag_requested.connect(drags.append)
    QTest.mousePress(board, Qt.MouseButton.LeftButton, pos=point)
    assert choices == []
    QTest.mouseRelease(board, Qt.MouseButton.LeftButton, pos=point)
    assert choices == [(20, False)]
    choices.clear()
    QTest.mousePress(board, Qt.MouseButton.LeftButton, pos=point)
    _move(board, point, QPoint(QApplication.startDragDistance() + 20, 0))
    QTest.mouseRelease(board, Qt.MouseButton.LeftButton, pos=point)
    assert choices == ranges == []
    assert drags == [20]

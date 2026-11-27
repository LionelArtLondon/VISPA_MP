"""Suggestion popup actions visibly distinguish hover and unavailable choices."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu

from vispa_mp.ui_tokens import MENU_DISABLED_TEXT, SELECTED_ROW, window_stylesheet


@pytest.fixture
def popup(qapp):
    menu = QMenu()
    menu.setStyleSheet(window_stylesheet())
    menu.addAction("Add as Extra")
    menu.addAction("Add as Core")
    menu.addSeparator()
    menu.addAction("This image already has a marker").setEnabled(False)
    menu.popup(QPoint(100, 100))
    qapp.processEvents()
    yield menu
    menu.close()
    menu.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_hover_paints_a_clear_selected_background(popup, qapp):
    action = popup.actions()[0]
    rect = popup.actionGeometry(action)
    sample = QPoint(rect.left() + 5, rect.center().y())
    before = popup.grab().toImage().pixelColor(sample)
    QTest.mouseMove(popup, rect.center())
    qapp.processEvents()
    assert popup.activeAction() is action
    after = popup.grab().toImage().pixelColor(sample)
    assert after == QColor(SELECTED_ROW) and after != before


def test_unavailable_action_stays_muted_and_does_not_look_hovered(popup, qapp):
    action = popup.actions()[-1]
    rect = popup.actionGeometry(action)
    QTest.mouseMove(popup, rect.center())
    qapp.processEvents()
    picture = popup.grab().toImage()
    assert picture.pixelColor(rect.left() + 5, rect.center().y()) != QColor(SELECTED_ROW)
    # Check rendered glyphs, rather than merely asserting a stylesheet string.
    assert any(picture.pixelColor(x, y) == QColor(MENU_DISABLED_TEXT)
               for y in range(rect.top(), rect.bottom() + 1)
               for x in range(rect.left(), rect.right() + 1))

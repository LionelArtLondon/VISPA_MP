"""Status and selection remain visually independent in both review renderers."""

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

from vispa_mp.review_selection_style import STATUS_COLOURS, paint_review_frame
from vispa_mp.ui_tokens import APP_BG


def _frame(color, size=(128, 76), **state):
    image = QImage(*size, QImage.Format.Format_RGB32)
    image.fill(QColor("#f7f4ee"))  # the Board's paper, where white alone is subtle
    painter = QPainter(image)
    paint_review_frame(painter, QRect(0, 0, *size), color, **state)
    painter.end()
    return image


def _pixels_of(image, color):
    expected = QColor(color)
    return {(x, y) for y in range(image.height()) for x in range(image.width())
            if image.pixelColor(x, y) == expected}


@pytest.mark.parametrize("color", STATUS_COLOURS.values())
def test_selection_preview_and_kept_feedback_never_replace_status_color(qapp, color):
    normal = _frame(color)
    role_pixels = _pixels_of(normal, color)
    assert role_pixels
    for state in ({"selected": True}, {"selected": True, "preview": True},
                  {"selected": True, "kept": True}, {"kept": True}):
        assert _pixels_of(_frame(color, **state), color) == role_pixels


@pytest.mark.parametrize("size", [(192, 108), (96, 54), (48, 27), (32, 18)])
def test_white_selection_is_separated_from_three_pixel_status_border_on_small_images(qapp, size):
    color = STATUS_COLOURS["Blue"]
    normal = _frame(color, size)
    selected = _frame(color, size, selected=True)
    y = size[1] // 2
    white = [x for x in range(size[0] // 2) if selected.pixelColor(x, y) == QColor("#FFFFFF")]
    status = [x for x in range(size[0] // 2) if selected.pixelColor(x, y) == QColor(color)]
    assert white and len(status) == 3
    assert max(white) < min(status)
    assert any(selected.pixelColor(x, y) == QColor(APP_BG)
               for x in range(max(white) + 1, min(status)))
    assert all(normal.pixelColor(x, y) != QColor("#FFFFFF") for x in white)

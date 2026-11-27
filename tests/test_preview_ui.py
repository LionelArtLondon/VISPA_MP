"""Frame crops and Board labels remain presentation choices during review."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QComboBox

from tests.test_project_ui import _review
from vispa_mp.strip_canvas import CanvasImage
from vispa_mp.ui import SWATCH


def _striped_review(qapp, tmp_path):
    window = _review(qapp, tmp_path)
    source = QPixmap(180, 60)
    painter = QPainter(source)
    for index, color in enumerate(("red", "green", "blue")):
        painter.fillRect(index * 60, 0, 60, 60, QColor(color))
    painter.end()
    path = tmp_path / "three-drawings.png"
    assert source.save(str(path))
    for shot in window.analysis["shots"]:
        for frame in shot["frames"]:
            frame["image"] = str(path)
    for proposal in window.proposals:
        proposal["image"] = str(path)
    window._fill()
    window._set_mode("board")
    window.board.resize(640, 780)
    return window, path


def _render_card(board, item, rect=QRect(10, 10, 180, 100)):
    image = QImage(210, 130, QImage.Format.Format_RGB32)
    image.fill(QColor("yellow"))
    painter = QPainter(image)
    board._paint_card(painter, item, rect)
    painter.end()
    return image


def test_frame_format_combo_controls_board_geometry_and_custom_ratio(qapp, tmp_path):
    window, _path = _striped_review(qapp, tmp_path)
    combo = window.frame_format_box
    assert isinstance(combo, QComboBox)
    assert combo.currentText() == "Source"
    assert window.frame_dimensions.isHidden()
    assert window.board.image_ratio == pytest.approx(16 / 9)
    assert not window.board.crop_images

    combo.setCurrentText("1:1")
    assert window.frame_format == "1:1"
    assert window.board.image_ratio == 1
    assert window.board.crop_images
    for _item, rect in window.board._card_rects(window.board._page_rect()):
        assert rect.width() == rect.height()

    combo.setCurrentText("Custom")
    window.frame_width_box.setValue(2)
    window.frame_height_box.setValue(3)
    assert not window.frame_dimensions.isHidden()
    assert window.frame_custom_width == 2
    assert window.frame_custom_height == 3
    assert window.board.image_ratio == pytest.approx(2 / 3)
    for _item, rect in window.board._card_rects(window.board._page_rect()):
        assert abs(rect.width() - rect.height() * 2 / 3) <= 1


def test_board_source_shows_side_drawings_and_square_crop_shows_the_center(qapp, tmp_path):
    window, path = _striped_review(qapp, tmp_path)
    original = path.read_bytes()
    window.board_labels_check.setChecked(False)
    item = window.board.items[0]
    # In Source mode the entire drawing is visible, with fit bars as needed.
    source = _render_card(window.board, item)
    assert source.pixelColor(25, 60) == QColor("red")
    assert source.pixelColor(100, 60) == QColor("green")
    assert source.pixelColor(175, 60) == QColor("blue")

    window.frame_format_box.setCurrentText("1:1")
    square = _render_card(window.board, item, rect=QRect(10, 10, 100, 100))
    assert square.pixelColor(20, 60) == QColor("green")
    assert square.pixelColor(60, 60) == QColor("green")
    assert square.pixelColor(100, 60) == QColor("green")
    window.frame_format_box.setCurrentText("Source")
    assert _render_card(window.board, item) == source
    assert path.read_bytes() == original


def test_hiding_labels_keeps_board_borders_and_marker_payload_unchanged(qapp, tmp_path):
    window, _path = _striped_review(qapp, tmp_path)
    proposals = deepcopy(window.proposals)
    payload = deepcopy(window.resolve_payload())
    item = window.board.items[0]
    window._flash = None
    window._refresh_board()
    window.board_labels_check.setChecked(True)
    with_labels = _render_card(window.board, item)
    window.board_labels_check.setChecked(False)
    assert window.show_board_labels is False
    assert window.board.show_labels is False
    without_labels = _render_card(window.board, item)
    color = QColor(SWATCH[item["proposal"]["color"]])
    assert with_labels.pixelColor(11, 60) == without_labels.pixelColor(11, 60)
    assert without_labels.pixelColor(11, 60) != QColor("yellow")
    # The large role badge disappears, while the image and perimeter remain.
    badge_area = QRect(20, 20, 40, 14)
    labelled = sum(with_labels.pixelColor(x, y) == color
                   for y in range(badge_area.top(), badge_area.bottom())
                   for x in range(badge_area.left(), badge_area.right()))
    unlabelled = sum(without_labels.pixelColor(x, y) == color
                     for y in range(badge_area.top(), badge_area.bottom())
                     for x in range(badge_area.left(), badge_area.right()))
    assert labelled > 100
    assert unlabelled == 0
    assert window.proposals == proposals
    assert window.resolve_payload() == payload


def test_frame_ratio_resizes_strip_and_suggestions_and_survives_view_switches(qapp, tmp_path):
    window, _path = _striped_review(qapp, tmp_path)
    window.resize(1600, 1000)
    window.show()
    window._set_mode("strip")
    window._open_suggestions(12, False)
    qapp.processEvents()
    window.set_suggestions_height(300)
    qapp.processEvents()
    original = deepcopy(window.resolve_payload())

    window.frame_format_box.setCurrentText("1:1")
    qapp.processEvents()
    thumb = window.thumb_layout.itemAt(0).widget().findChild(CanvasImage)
    assert thumb.width() == thumb.height()
    for card in window._suggestion_cards.values():
        picture = card._suggestion_picture
        assert picture.width() == picture.height()
        assert picture.frame_format == "1:1"

    window.board_labels_check.setChecked(False)
    window._set_mode("board")
    qapp.processEvents()
    assert window.frame_format_box.currentText() == "1:1"
    assert not window.board.show_labels
    assert window.board.image_ratio == 1
    window._set_mode("strip")
    assert window.frame_format == "1:1"
    assert not window.show_board_labels
    assert window.resolve_payload() == original


def test_custom_preview_dimensions_never_recompute_or_change_markers(qapp, tmp_path, monkeypatch):
    window, _path = _striped_review(qapp, tmp_path)
    before = deepcopy(window.proposals)
    payload = deepcopy(window.resolve_payload())
    monkeypatch.setattr(window, "recompute", lambda: pytest.fail("A frame crop must not recompute markers"))
    window.frame_format_box.setCurrentText("Custom")
    window.frame_width_box.setValue(3.5)
    window.frame_height_box.setValue(5)
    assert window.board.image_ratio == pytest.approx(0.7)
    assert window.proposals == before
    assert window.resolve_payload() == payload
    assert window._project_dirty

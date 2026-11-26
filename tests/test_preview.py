"""Frame formats alter the preview geometry and crop, never the source image."""

from pathlib import Path

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from vispa_mp.preview import FRAME_FORMATS, crop_rect, draw_preview, frame_ratio
from vispa_mp.strip_canvas import CanvasImage


def _coloured_source(portrait=False):
    source = QPixmap(60 if portrait else 180, 180 if portrait else 60)
    painter = QPainter(source)
    for index, colour in enumerate(("red", "green", "blue")):
        painter.fillRect(0 if portrait else index * 60, index * 60 if portrait else 0,
                         60, 60, QColor(colour))
    painter.end()
    return source


def _render(source, crop, target=QRectF(0, 0, 90, 90)):
    image = QImage(160, 120, QImage.Format.Format_RGB32)
    image.fill(QColor("yellow"))
    painter = QPainter(image)
    draw_preview(painter, source, target, "magenta", crop=crop)
    painter.end()
    return image


@pytest.mark.parametrize("name, expected", [
    ("Source", None), ("16:9", 16 / 9), ("4:3", 4 / 3), ("3:2", 3 / 2),
    ("1:1", 1), ("2:3", 2 / 3), ("9:16", 9 / 16), ("Custom", 5.5 / 3.1),
])
def test_frame_formats_have_the_expected_width_to_height_ratio(name, expected):
    assert name in FRAME_FORMATS
    ratio = frame_ratio(name, 5.5, 3.1)
    assert ratio is None if expected is None else ratio == pytest.approx(expected)


@pytest.mark.parametrize("name,width,height", [
    ("Other", 16, 9), ("Custom", 0, 1), ("Custom", 1, -1),
    ("Custom", float("nan"), 1), ("Custom", 1, float("inf")),
])
def test_unusable_frame_formats_are_rejected(name, width, height):
    with pytest.raises(ValueError):
        frame_ratio(name, width, height)


@pytest.mark.parametrize("source,target,expected", [
    ((1920, 1080), (400, 400), (420, 0, 1080, 1080)),
    ((1080, 1920), (400, 400), (0, 420, 1080, 1080)),
    ((1920, 1080), (160, 90), (0, 0, 1920, 1080)),
    ((1920, 1080), (300, 450), (600, 0, 720, 1080)),
])
def test_centered_crops_keep_the_target_ratio_without_stretching(source, target, expected):
    result = crop_rect(*source, *target)
    assert (result.x(), result.y(), result.width(), result.height()) == pytest.approx(expected)


@pytest.mark.parametrize("dimensions", [(0, 1080, 100, 100), (1920, 0, 100, 100),
                                         (100, 100, 0, 100), (100, 100, 100, -1)])
def test_empty_preview_geometry_does_not_divide_by_zero(dimensions):
    assert crop_rect(*dimensions).isEmpty()


@pytest.mark.parametrize("portrait", [False, True])
def test_center_crop_shows_the_center_drawing_without_changing_pixels(qapp, portrait):
    source = _coloured_source(portrait)
    original = source.toImage()
    image = _render(source, crop=True)
    for x, y in ((3, 3), (45, 45), (86, 86)):
        assert image.pixelColor(x, y) == QColor("green")
    assert source.toImage() == original


def test_source_format_keeps_the_whole_picture_and_clears_letterbox_area(qapp):
    image = _render(_coloured_source(), crop=False)
    assert image.pixelColor(45, 10) == QColor("magenta")
    assert image.pixelColor(10, 45) == QColor("red")
    assert image.pixelColor(45, 45) == QColor("green")
    assert image.pixelColor(80, 45) == QColor("blue")
    assert image.pixelColor(45, 80) == QColor("magenta")


def test_fit_uses_the_target_origin_and_paints_no_pixels_outside_it(qapp):
    image = _render(_coloured_source(), crop=False, target=QRectF(20, 10, 90, 90))
    assert image.pixelColor(25, 55) == QColor("red")
    assert image.pixelColor(65, 55) == QColor("green")
    assert image.pixelColor(105, 55) == QColor("blue")
    assert image.pixelColor(25, 15) == QColor("magenta")
    assert image.pixelColor(19, 55) == QColor("yellow")
    assert image.pixelColor(110, 55) == QColor("yellow")


def test_missing_image_paints_the_entire_requested_preview(qapp):
    image = _render(QPixmap(), crop=True, target=QRectF(20, 10, 90, 90))
    assert image.pixelColor(20, 10) == QColor("magenta")
    assert image.pixelColor(109, 99) == QColor("magenta")
    assert image.pixelColor(19, 10) == QColor("yellow")


def test_canvas_can_switch_from_source_to_crop_and_back_without_writing_source(qapp, tmp_path):
    source = _coloured_source()
    path = tmp_path / "source.png"
    assert source.save(str(path))
    before = Path(path).read_bytes()
    widget = CanvasImage()
    widget.resize(90, 90)
    widget.set_source(str(path), "magenta")
    widget.set_frame_format("Source")
    fitted = widget.grab().toImage()
    assert fitted.pixelColor(45, 10) == QColor("magenta")
    widget.set_frame_format("1:1")
    cropped = widget.grab().toImage()
    assert cropped.pixelColor(45, 10) == QColor("green")
    widget.set_frame_format("Source")
    assert widget.grab().toImage() == fitted
    assert Path(path).read_bytes() == before

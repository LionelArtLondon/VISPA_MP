"""Common preview quality keeps Medium intact and bounds High's display work."""

import gc

import pytest
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QVBoxLayout, QWidget

from vispa_mp import preview_quality, strip_canvas
from vispa_mp.preview import crop_rect, draw_preview
from vispa_mp.preview_quality import (MAX_PREVIEW_EDGE, MAX_PREVIEW_PIXELS, PixmapCache,
                                      bounded_size, physical_size)
from vispa_mp.strip_canvas import CanvasImage, StripCanvasView


@pytest.fixture(autouse=True)
def clear_preview_caches():
    preview_quality._resampled.clear()
    strip_canvas._sources.clear()
    yield
    preview_quality._resampled.clear()
    strip_canvas._sources.clear()


def detailed_image(width=259, height=173):
    image = Image.new("RGBA", (width, height))
    image.putdata([((x * 31 + y * 9) % 256, (x * 3 + y * 41) % 256,
                    ((x // 3 + y // 2) % 2) * 255, 255)
                   for y in range(height) for x in range(width)])
    return image


def as_qimage(image):
    return QImage(image.tobytes(), image.width, image.height, image.width * 4,
                  QImage.Format.Format_RGBA8888).copy()


def render(source, *, quality="Medium", crop=False, width=61, height=43, dpr=1, zoom=1):
    image = QImage(width * dpr * zoom, height * dpr * zoom, QImage.Format.Format_RGBA8888)
    image.setDevicePixelRatio(dpr)
    image.fill(QColor("magenta"))
    painter = QPainter(image)
    painter.scale(zoom, zoom)
    draw_preview(painter, source, QRectF(0, 0, width, height), "magenta", crop=crop, quality=quality)
    painter.end()
    return image


def former_strip_render(source, crop):
    image = QImage(61, 43, QImage.Format.Format_RGBA8888)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    target = QRectF(0, 0, 61, 43)
    painter.fillRect(target, QColor("magenta"))
    if crop:
        source_rect = crop_rect(source.width(), source.height(), target.width(), target.height())
    else:
        source_rect = QRectF(source.rect())
        scale = min(target.width() / source_rect.width(), target.height() / source_rect.height())
        width, height = source_rect.width() * scale, source_rect.height() * scale
        target = QRectF((61 - width) / 2, (43 - height) / 2, width, height)
    painter.drawPixmap(target, source, source_rect)
    painter.end()
    return image


@pytest.mark.parametrize("crop", [False, True])
def test_medium_matches_the_former_smooth_strip_pixels_exactly(qapp, crop):
    source = QPixmap.fromImage(as_qimage(detailed_image()))
    original = source.toImage()
    assert render(source, quality="Medium", crop=crop) == former_strip_render(source, crop)
    assert source.toImage() == original


def test_low_is_a_distinct_fast_display_filter_without_mutating_source(qapp):
    source = QPixmap.fromImage(as_qimage(detailed_image()))
    original = source.toImage()
    assert render(source, quality="Low") != render(source, quality="Medium")
    assert source.toImage() == original


def test_high_uses_lanczos_for_the_exact_center_crop_from_the_available_still(qapp):
    original = detailed_image()
    source = QPixmap.fromImage(as_qimage(original))
    region = crop_rect(original.width, original.height, 37, 29)
    box = (region.x(), region.y(), region.x() + region.width(), region.y() + region.height())
    expected = original.resize((37, 29), resample=Image.Resampling.LANCZOS, box=box)
    actual = render(source, quality="High", crop=True, width=37, height=29)
    assert actual == as_qimage(expected)
    assert actual != render(source, quality="Medium", crop=True, width=37, height=29)
    assert source.toImage().convertToFormat(QImage.Format.Format_RGBA8888) == as_qimage(original)


@pytest.mark.parametrize("dpr,zoom", [(2, 1), (1, 2), (2, 2)])
def test_high_samples_at_the_physical_device_and_zoom_resolution(qapp, dpr, zoom):
    original = detailed_image()
    source = QPixmap.fromImage(as_qimage(original))
    actual = render(source, quality="High", crop=True, width=43, height=27, dpr=dpr, zoom=zoom)
    region = crop_rect(original.width, original.height, 43, 27)
    box = (region.x(), region.y(), region.x() + region.width(), region.y() + region.height())
    expected = as_qimage(original.resize((43 * dpr * zoom, 27 * dpr * zoom),
                                         resample=Image.Resampling.LANCZOS, box=box))
    actual.setDevicePixelRatio(1)
    assert actual == expected


def test_high_reuses_a_prepared_size_and_keeps_distinct_crops_separate(qapp, monkeypatch):
    source = QPixmap.fromImage(as_qimage(detailed_image()))
    calls = []
    original = preview_quality._pillow_source

    def read(pixmap):
        calls.append(pixmap.cacheKey())
        return original(pixmap)

    monkeypatch.setattr(preview_quality, "_pillow_source", read)
    first = render(source, quality="High", width=53, height=53)
    gc.collect()
    assert render(source, quality="High", width=53, height=53) == first
    assert len(calls) == 1
    cropped = render(source, quality="High", crop=True, width=53, height=53)
    assert cropped != first
    assert len(calls) == 2
    assert render(source, quality="High", crop=True, width=53, height=53) == cropped
    assert len(calls) == 2


def test_high_falls_back_to_smooth_qt_when_source_conversion_would_exceed_the_budget(qapp, monkeypatch):
    source = QPixmap.fromImage(as_qimage(detailed_image()))
    monkeypatch.setattr(preview_quality, "MAX_SOURCE_PIXELS", 1)
    monkeypatch.setattr(preview_quality, "_pillow_source", lambda *_args:
                        pytest.fail("An oversized source must not be copied into Pillow buffers"))
    assert render(source, quality="High", crop=True) == render(source, quality="Medium", crop=True)


@pytest.mark.parametrize("quality", ["Low", "Medium", "High"])
def test_preview_quality_does_not_leak_a_changed_filter_to_other_paint_operations(qapp, quality):
    source = QPixmap.fromImage(as_qimage(detailed_image()))
    image = QImage(61, 43, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    original = quality == "Low"
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, original)
    draw_preview(painter, source, QRectF(image.rect()), "magenta", quality=quality)
    assert painter.testRenderHint(QPainter.RenderHint.SmoothPixmapTransform) is original
    painter.end()


def test_render_allocation_is_bounded_even_at_extreme_zoom(qapp):
    for width, height in ((100000, 70000), (100000, 10), (10, 100000), (4096, 4096)):
        physical = bounded_size(width, height)
        assert 0 < max(physical) <= MAX_PREVIEW_EDGE
        assert physical[0] * physical[1] <= MAX_PREVIEW_PIXELS
    image = QImage(10, 10, QImage.Format.Format_RGB32)
    image.setDevicePixelRatio(2)
    painter = QPainter(image)
    painter.scale(3, 4)
    assert physical_size(painter, QRectF(0, 0, 10, 12)) == (60, 96)
    painter.end()


def test_pixmap_lru_limits_memory_and_entry_count_and_evicts_the_oldest(qapp):
    cache = PixmapCache(max_bytes=3200, max_items=2)
    picture = QPixmap(20, 20)
    cache.put("first", picture)
    cache.put("second", picture)
    assert cache.get("first") is picture
    cache.put("third", picture)
    assert cache.get("second") is None
    assert cache.get("first") is picture
    assert len(cache) == 2 and cache.bytes_used <= cache.max_bytes
    cache.put("oversized", QPixmap(30, 30))
    assert cache.get("oversized") is None
    assert len(cache) == 2 and cache.bytes_used <= cache.max_bytes
    cache.clear()
    assert len(cache) == 0 and cache.bytes_used == 0


def test_sources_are_loaded_only_when_painted_and_not_retained_by_every_canvas(qapp, tmp_path, monkeypatch):
    path = tmp_path / "cached-frame.png"
    detailed_image().save(path)
    source_bytes = path.read_bytes()
    widget = CanvasImage()
    widget.resize(61, 43)
    widget.set_source(str(path), "magenta")
    widget.set_frame_format("Source")
    assert len(strip_canvas._sources) == 0
    assert "picture" not in vars(widget)
    medium = widget.grab().toImage()
    assert len(strip_canvas._sources) == 1
    widget.set_preview_quality("Low")
    assert widget.grab().toImage() != medium
    widget.set_preview_quality("High")
    assert widget.preview_quality == "High"
    assert not widget.grab().isNull()
    assert path.read_bytes() == source_bytes
    widget.close()


def test_strip_quality_changes_existing_canvas_images_and_the_view_filter(qapp):
    view = StripCanvasView()
    host = QWidget()
    layout = QVBoxLayout(host)
    canvas = CanvasImage()
    layout.addWidget(canvas)
    view.setWidget(host)
    assert view.preview_quality == canvas.preview_quality == "Medium"
    for quality in ("Low", "High", "Medium"):
        view.set_preview_quality(quality)
        assert view.preview_quality == canvas.preview_quality == quality
        assert bool(view.renderHints() & QPainter.RenderHint.SmoothPixmapTransform) == (quality != "Low")
    view.close()

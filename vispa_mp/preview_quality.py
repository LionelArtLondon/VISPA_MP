"""Bounded display resampling of cached stills; no media extraction or inference."""

from collections import OrderedDict
from math import ceil, hypot, isfinite, sqrt

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPixmap


PREVIEW_QUALITIES = ("Low", "Medium", "High")
DEFAULT_PREVIEW_QUALITY = "Medium"
MAX_PREVIEW_EDGE = 4096
MAX_PREVIEW_PIXELS = 8 * 1024 * 1024
MAX_SOURCE_PIXELS = 16 * 1024 * 1024
PREVIEW_CACHE_BYTES = 64 * 1024 * 1024


def normalized_quality(value):
    return value if value in PREVIEW_QUALITIES else DEFAULT_PREVIEW_QUALITY


class PixmapCache:
    """An LRU limited by both decoded pixel memory and entry count."""

    def __init__(self, max_bytes=PREVIEW_CACHE_BYTES, max_items=96):
        self.max_bytes, self.max_items = max(0, int(max_bytes)), max(0, int(max_items))
        self.bytes_used = 0
        self._items = OrderedDict()

    def get(self, key):
        entry = self._items.get(key)
        if entry is None:
            return None
        self._items.move_to_end(key)
        return entry[0]

    def put(self, key, pixmap):
        previous = self._items.pop(key, None)
        if previous is not None:
            self.bytes_used -= previous[1]
        cost = pixmap.width() * pixmap.height() * max(4, ceil(pixmap.depth() / 8))
        if cost > self.max_bytes or not self.max_items:
            return pixmap
        self._items[key] = (pixmap, cost)
        self.bytes_used += cost
        while self.bytes_used > self.max_bytes or len(self._items) > self.max_items:
            _key, (_pixmap, removed_cost) = self._items.popitem(last=False)
            self.bytes_used -= removed_cost
        return pixmap

    def clear(self):
        self._items.clear()
        self.bytes_used = 0

    def __len__(self):
        return len(self._items)


_resampled = PixmapCache()


def bounded_size(width, height):
    """Limit a physical render allocation, preserving the requested aspect."""
    width, height = max(1, int(ceil(width))), max(1, int(ceil(height)))
    scale = min(1.0, MAX_PREVIEW_EDGE / width, MAX_PREVIEW_EDGE / height,
                sqrt(MAX_PREVIEW_PIXELS / (width * height)))
    return max(1, int(width * scale)), max(1, int(height * scale))


def physical_size(painter, target):
    """Include scene zoom and device pixel ratio exactly once."""
    transform = painter.deviceTransform()
    width = target.width() * hypot(transform.m11(), transform.m12())
    height = target.height() * hypot(transform.m21(), transform.m22())
    if not isfinite(width) or not isfinite(height):
        return None
    return bounded_size(width, height)


def low_source(pixmap, source):
    """Use a cheap, small decoded copy with the same centered crop geometry."""
    if max(pixmap.width(), pixmap.height()) <= 640:
        return pixmap, source
    key = ("Low", pixmap.cacheKey())
    small = _resampled.get(key)
    if small is None:
        small = pixmap.scaled(640, 640, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.FastTransformation)
        _resampled.put(key, small)
    x_scale, y_scale = small.width() / pixmap.width(), small.height() / pixmap.height()
    return small, QRectF(source.x() * x_scale, source.y() * y_scale,
                         source.width() * x_scale, source.height() * y_scale)


def _pillow_source(pixmap):
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes("RGBA", (image.width(), image.height()), bytes(image.constBits()),
                           "raw", "RGBA", image.bytesPerLine())


def high_source(painter, pixmap, source, target):
    """Lanczos the requested source crop to the physical display resolution.

    Large source images stay on Qt's smooth path to avoid converting an
    unbounded image into several Python/Qt buffers during a paint event.
    """
    dimensions = physical_size(painter, target)
    if dimensions is None or pixmap.width() * pixmap.height() > MAX_SOURCE_PIXELS:
        return None
    box = (source.x(), source.y(), source.x() + source.width(), source.y() + source.height())
    key = ("High", pixmap.cacheKey(), box, dimensions)
    result = _resampled.get(key)
    if result is not None:
        return result
    try:
        with _pillow_source(pixmap) as original:
            resized = original.resize(dimensions, resample=Image.Resampling.LANCZOS, box=box)
        try:
            pixels = resized.tobytes("raw", "RGBA")
            image = QImage(pixels, dimensions[0], dimensions[1], dimensions[0] * 4,
                           QImage.Format.Format_RGBA8888).copy()
            result = QPixmap.fromImage(image)
        finally:
            resized.close()
    except (MemoryError, OSError, ValueError):
        return None
    return _resampled.put(key, result)

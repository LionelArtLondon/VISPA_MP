"""Preview-only frame formats and centered crops; source files stay untouched."""

from math import isfinite

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor

from vispa_mp.preset import FRAME_FORMATS


def frame_ratio(format_name, custom_width=16, custom_height=9):
    """The chosen frame's width/height, or None to fit the source unchanged."""
    if format_name not in FRAME_FORMATS:
        raise ValueError(f"Unknown frame format: {format_name}")
    if format_name == "Source":
        return None
    if format_name == "Custom":
        width, height = float(custom_width), float(custom_height)
    else:
        width, height = (float(value) for value in format_name.split(":"))
    if not isfinite(width) or not isfinite(height) or width <= 0 or height <= 0:
        raise ValueError("Frame dimensions must be finite and greater than zero.")
    return width / height


def crop_rect(source_width, source_height, target_width, target_height):
    """The centered source region that fills a target without stretching."""
    sizes = tuple(float(value) for value in (source_width, source_height, target_width, target_height))
    if any(not isfinite(value) or value <= 0 for value in sizes):
        return QRectF()
    source_width, source_height, target_width, target_height = sizes
    scale = max(target_width / source_width, target_height / source_height)
    width, height = target_width / scale, target_height / scale
    return QRectF((source_width - width) / 2, (source_height - height) / 2, width, height)


def draw_preview(painter, pixmap, target_rect, fallback, crop=False):
    """Paint a source fit or center crop, clearing the entire preview first."""
    target = QRectF(target_rect)
    painter.fillRect(target, QColor(fallback))
    if (pixmap is None or pixmap.isNull() or target.width() <= 0 or target.height() <= 0):
        return
    if crop:
        source = crop_rect(pixmap.width(), pixmap.height(), target.width(), target.height())
    else:
        source = QRectF(pixmap.rect())
        scale = min(target.width() / source.width(), target.height() / source.height())
        width, height = source.width() * scale, source.height() * scale
        target = QRectF(target.x() + (target.width() - width) / 2,
                        target.y() + (target.height() - height) / 2, width, height)
    painter.drawPixmap(target, pixmap, source)

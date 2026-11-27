"""Inspect the exact cached stills of one approved reference, without media access."""

from copy import deepcopy
import math
from pathlib import Path
import re

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from vispa_mp.timebase import format_timecode
from vispa_mp.window_chrome import ChromeDialog


PAGE_SIZE = 24
GRID_COLUMNS = 3
THUMBNAIL_SIZE = QSize(156, 92)
PREVIEW_SIZE = QSize(1280, 800)
_COLOURS = {"page": "#6fd17d", "core": "#6f9bff", "extra": "#8be8f5", "unmarked": "#73828c"}
_MISSING = "Preview unavailable\nReimport this reference to restore cached images."


def _role(sample):
    roles = sample.get("roles") or []
    return next((role for role in ("page", "extra", "core") if role in roles), "unmarked")


def _role_label(sample):
    return {"page": "Page start · Core", "core": "Core", "extra": "Extra",
            "unmarked": "Unmarked alternative"}[_role(sample)]


def _read_still(path, size):
    """Decode one local raster to a bounded size; never recover it from source media."""
    if not isinstance(path, str) or not path or "\x00" in path or "://" in path or path.startswith(("\\\\", "//")):
        return QPixmap()
    image_path = Path(path)
    if not image_path.is_absolute() or image_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        return QPixmap()
    try:
        if not image_path.is_file() or image_path.stat().st_size > 32 * 1024 * 1024:
            return QPixmap()
        reader = QImageReader(str(image_path))
        reader.setAutoTransform(True)
        original = reader.size()
        # The imports use 448 px stills. Reject unexpectedly large rasters before
        # decoding, then request only the pixels required by this view.
        if (not original.isValid() or max(original.width(), original.height()) > 16_384
                or original.width() * original.height() > 32_000_000
                or bytes(reader.format()).lower() not in (b"jpeg", b"png")):
            return QPixmap()
        if original.width() > size.width() or original.height() > size.height():
            reader.setScaledSize(original.scaled(size, Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            return QPixmap()
        # Keep the bound even for a format plugin that ignores setScaledSize.
        if image.width() > size.width() or image.height() > size.height():
            image = image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        return QPixmap.fromImage(image)
    except (OSError, RuntimeError, ValueError):
        return QPixmap()


def _placeholder():
    pixmap = QPixmap(THUMBNAIL_SIZE)
    pixmap.fill(QColor("#172128"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#c3d1d6"))
    painter.drawText(pixmap.rect().adjusted(5, 5, -5, -5),
                     Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "Preview unavailable")
    painter.end()
    return pixmap


class _ContainedPreview(QLabel):
    """Contain the selected image at its physical aspect ratio, including on resize."""

    def __init__(self):
        super().__init__()
        self._pixmap = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumSize(280, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background: #0e1419; color: #c3d1d6; padding: 8px;")

    def setPixmap(self, pixmap):
        self._pixmap = pixmap
        self.setText("")
        self.update()

    def pixmap(self):
        return self._pixmap

    def show_placeholder(self, text):
        self._pixmap = QPixmap()
        self.setText(text)
        self.update()

    def paintEvent(self, event):
        if self._pixmap.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0e1419"))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        size = self._pixmap.size().scaled(self.contentsRect().size(), Qt.AspectRatioMode.KeepAspectRatio)
        rect = QRect(0, 0, size.width(), size.height())
        rect.moveCenter(self.contentsRect().center())
        painter.drawPixmap(rect, self._pixmap)
        painter.end()


class ReferencePreviewDialog(ChromeDialog):
    """A paginated, read-only view of one reference's already cached images."""

    def __init__(self, owner, reference):
        super().__init__(getattr(owner, "learning_dialog", None) or owner, "Inspect learning reference")
        self.owner = owner
        self.reference = deepcopy(reference)
        self.samples = self.reference.get("samples") or []
        self.filtered_indices = []
        self.page = 0
        self.selected_index = None
        self.cards = []
        self.setStyleSheet(owner.styleSheet())
        self.resize(1150, 850)
        column = QVBoxLayout(self.body)
        column.setContentsMargins(18, 16, 18, 16)
        self.heading = QLabel(self.reference.get("name") or "Reference chapter")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        self.source_info = self.reference.get("source")
        self.source_info = self.source_info if isinstance(self.source_info, dict) else {}
        source = self.source_info
        self.source = QLabel(f"Project: {source.get('project_name') or 'not recorded'}\n"
                             f"Timeline: {source.get('timeline_name') or 'not recorded'}")
        self.source.setTextFormat(Qt.TextFormat.PlainText)
        self.source.setWordWrap(True)
        column.addWidget(self.heading)
        column.addWidget(self.source)
        self.notice = QLabel("Read-only reference. These are the cached images used for learning; inspecting them keeps marker roles and the current review unchanged.")
        self.notice.setWordWrap(True)
        column.addWidget(self.notice)
        self.timecode_warning = self._timecode_warning()
        self.warning = QLabel(self.timecode_warning)
        self.warning.setWordWrap(True)
        self.warning.setVisible(bool(self.timecode_warning))
        column.addWidget(self.warning)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Show"))
        self.filter = QComboBox()
        for label, key in (("All marked", "marked"), ("Core incl. starts", "core"),
                           ("Extra", "extra"), ("Page start", "page"),
                           ("Unmarked alternatives", "unmarked")):
            self.filter.addItem(label, key)
        self.filter.currentIndexChanged.connect(self._filter_changed)
        filters.addWidget(self.filter)
        filters.addStretch(1)
        column.addLayout(filters)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        browser = QWidget()
        browser.setMinimumWidth(550)
        browser_column = QVBoxLayout(browser)
        browser_column.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_widget = QWidget()
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(8)
        self.scroll.setWidget(self.grid_widget)
        browser_column.addWidget(self.scroll, 1)
        self.empty = QLabel("No images match this filter.")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        browser_column.addWidget(self.empty)
        pages = QHBoxLayout()
        self.previous_page = QPushButton("Previous page")
        self.previous_page.clicked.connect(lambda: self._change_page(-1))
        self.next_page = QPushButton("Next page")
        self.next_page.clicked.connect(lambda: self._change_page(1))
        self.page_label = QLabel()
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pages.addWidget(self.previous_page)
        pages.addWidget(self.page_label, 1)
        pages.addWidget(self.next_page)
        browser_column.addLayout(pages)
        self.splitter.addWidget(browser)
        selected = QWidget()
        selected_column = QVBoxLayout(selected)
        selected_column.setContentsMargins(10, 0, 0, 0)
        self.preview = _ContainedPreview()
        selected_column.addWidget(self.preview, 1)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        selected_column.addWidget(self.details)
        self.preview_status = QLabel()
        self.preview_status.setWordWrap(True)
        selected_column.addWidget(self.preview_status)
        self.copy_details = QPushButton("Copy example details")
        self.copy_details.clicked.connect(self._copy_example_details)
        selected_column.addWidget(self.copy_details)
        self.splitter.addWidget(selected)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([560, 550])
        column.addWidget(self.splitter, 1)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        column.addWidget(self.close_button, alignment=Qt.AlignmentFlag.AlignRight)
        self._filter_changed()

    def _timecode_warning(self):
        base = self.reference.get("timebase")
        if not isinstance(base, dict):
            return "Resolve timecode origin was not recorded. Reimport this reference for exact timecodes."
        try:
            fps = base.get("fps")
            origin = base.get("start_timecode")
            if (isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0
                    or type(base.get("start_frame")) is not int
                    or not isinstance(origin, str) or not re.fullmatch(r"\d{2,}:\d{2}:\d{2}[:;]\d{2}", origin)):
                return "Resolve timecode origin was not recorded. Reimport this reference for exact timecodes."
            if fps > 30 and "timecode_fps" not in base:
                return "Timecode display rate was not recorded. Reimport this reference for exact Resolve timecodes."
            shown = base.get("timecode_fps", fps)
            if (isinstance(shown, bool) or not isinstance(shown, (int, float))
                    or not math.isfinite(shown) or shown <= 0
                    or "drop" in base and type(base["drop"]) is not bool):
                return "Resolve timecode was not recorded correctly. Reimport this reference for exact timecodes."
            _hours, minutes, seconds, frames = (int(part) for part in origin.replace(";", ":").split(":"))
            if minutes >= 60 or seconds >= 60 or frames >= max(1, round(shown)):
                return "Resolve timecode was not recorded correctly. Reimport this reference for exact timecodes."
            format_timecode(0, base)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            return "Resolve timecode was not recorded correctly. Reimport this reference for exact timecodes."
        return ""

    def _timecode(self, sample):
        if self.timecode_warning:
            return "Timecode unavailable"
        try:
            return format_timecode(sample["frame"], self.reference["timebase"])
        except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
            return "Timecode unavailable"

    def _filter_changed(self, *_args):
        key = self.filter.currentData()
        self.filtered_indices = [index for index, sample in enumerate(self.samples)
                                 if (bool(sample.get("roles")) if key == "marked" else
                                     not sample.get("roles") if key == "unmarked" else
                                     key in sample.get("roles", []))]
        self.page = 0
        self._show_page()

    def _change_page(self, delta):
        last_page = max(0, (len(self.filtered_indices) - 1) // PAGE_SIZE)
        self.page = min(last_page, max(0, self.page + delta))
        self._show_page()

    def _show_page(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() is not None:
                item.widget().setIcon(QIcon())
                item.widget().hide()
                item.widget().deleteLater()
        self.cards = []
        start = self.page * PAGE_SIZE
        indices = self.filtered_indices[start:start + PAGE_SIZE]
        total = len(self.filtered_indices)
        self.page_label.setText(f"{start + 1}–{start + len(indices)} of {total}" if indices else "0 images")
        self.previous_page.setEnabled(self.page > 0)
        self.next_page.setEnabled(start + PAGE_SIZE < total)
        self.empty.setVisible(not indices)
        self.scroll.setVisible(bool(indices))
        for offset, index in enumerate(indices):
            sample = self.samples[index]
            card = QToolButton(self.grid_widget)
            card.sample_index = index
            card.sample = sample
            card.setCheckable(True)
            card.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            card.setText(f"{_role_label(sample)}\n{self._timecode(sample)}")
            card.setToolTip(f"{_role_label(sample)} · absolute timeline frame {sample['frame']}")
            card.setIconSize(THUMBNAIL_SIZE)
            pixmap = _read_still(sample.get("image"), THUMBNAIL_SIZE)
            card.preview_available = not pixmap.isNull()
            card.setIcon(QIcon(pixmap if card.preview_available else _placeholder()))
            colour = _COLOURS[_role(sample)]
            card.ensurePolished()
            content_height = max(132, THUMBNAIL_SIZE.height() + 2 * card.fontMetrics().lineSpacing() + 8)
            # The application caps ordinary tool buttons at one line. Override
            # both QSS bounds so an inherited max-height cannot collapse a card.
            card.setStyleSheet(f"QToolButton {{ min-height: {content_height}px; max-height: {content_height}px;"
                              f" border: 2px solid {colour}; border-radius: 3px; padding: 5px; }}"
                              f"QToolButton:checked {{ border: 4px solid {colour}; padding: 3px; background: #24333d; }}")
            card.setMinimumSize(170, content_height + 14)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            card.clicked.connect(lambda _checked=False, sample_index=index: self._select_sample(sample_index))
            self.grid.addWidget(card, offset // GRID_COLUMNS, offset % GRID_COLUMNS)
            self.cards.append(card)
        self.grid.setRowStretch((len(indices) + GRID_COLUMNS - 1) // GRID_COLUMNS, 1)
        self.scroll.verticalScrollBar().setValue(0)
        selected = self.selected_index if self.selected_index in indices else indices[0] if indices else None
        self._select_sample(selected)

    def _select_sample(self, index):
        self.selected_index = index
        self.copy_details.setEnabled(index is not None)
        for card in self.cards:
            card.setChecked(card.sample_index == index)
        if index is None:
            self.preview.show_placeholder("No images match this filter.")
            self.details.clear()
            self.preview_status.clear()
            return
        sample = self.samples[index]
        source = sample.get("source_frame")
        self.details.setText(f"{_role_label(sample)}\n{self._timecode(sample)}\n"
                             f"Absolute timeline frame: {sample['frame']}\n"
                             f"Source frame: {source if source is not None else 'not recorded'}")
        self.preview.show_placeholder("")
        pixmap = _read_still(sample.get("image"), PREVIEW_SIZE)
        if pixmap.isNull():
            self.preview.show_placeholder(_MISSING)
            self.preview_status.setText("The cached image is missing or unreadable. Reimport this reference to restore its previews.")
        else:
            self.preview.setPixmap(pixmap)
            self.preview_status.setText("Exact cached still; original image proportions are preserved.")

    def _copy_example_details(self):
        if self.selected_index is None:
            return
        sample = self.samples[self.selected_index]
        source = self.source_info
        lines = [f"Reference: {self.reference.get('name') or 'Reference chapter'}",
                 f"Project: {source.get('project_name') or 'not recorded'}",
                 f"Timeline: {source.get('timeline_name') or 'not recorded'}",
                 f"Role: {_role_label(sample)}", self._timecode(sample),
                 f"Absolute timeline frame: {sample['frame']}",
                 f"Source frame: {sample.get('source_frame', 'not recorded')}"]
        QApplication.clipboard().setText("\n".join(lines))

"""Independent, read-only views of two already measured marker selections."""

from copy import deepcopy
from math import ceil

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from vispa_mp.markers import CORE, EXTRA, PAGE
from vispa_mp.preview import frame_ratio
from vispa_mp.strip_canvas import CanvasImage, StripCanvasView, balanced_columns
from vispa_mp.timebase import format_timecode
from vispa_mp.ui_tokens import ACCENT, APP_BG, TEXT_MUTED
from vispa_mp.window_chrome import TitleBar, WindowChromeMixin


class ComparisonCard(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ComparisonStrip(StripCanvasView):
    """Use the regular fixed canvas with pointer zoom and middle-button pan."""

    def __init__(self):
        super().__init__()
        self.scale = 1.0
        self._pan = None
        self.setToolTip("Wheel: zoom · Wheel held down and dragged: pan")

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120
        if steps:
            self.scale = min(8.0, max(0.08, self.scale * 1.2 ** steps))
            self.set_scale(self.scale, event.position())
            event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan = (event.position(), self.horizontalScrollBar().value(), self.verticalScrollBar().value())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan is not None:
            origin, horizontal, vertical = self._pan
            delta = event.position() - origin
            self.horizontalScrollBar().setValue(horizontal - round(delta.x()))
            self.verticalScrollBar().setValue(vertical - round(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._pan is not None:
            self._pan = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ComparisonWindow(WindowChromeMixin, QMainWindow):
    """A cached-image viewer with no client, preferences, editor, or analysis jobs."""

    def __init__(self, owner, variant, analysis, view):
        super().__init__(owner, Qt.WindowType.Window)
        # Local imports avoid making ui.py depend on itself during construction.
        from vispa_mp.ui import FORMATS, PageBoard, group_pages

        class ComparisonBoard(PageBoard):
            def paintEvent(self, event):
                if self.items:
                    super().paintEvent(event)
                    return
                painter = QPainter(self)
                painter.fillRect(self.rect(), QColor(APP_BG))
                painter.setPen(QColor(TEXT_MUTED))
                painter.drawText(self.rect().adjusted(16, 16, -16, -16),
                                 Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                                 "No images selected with these rules or this filter.")

        self.variant, self.analysis, self.view = deepcopy(variant), deepcopy(analysis), deepcopy(view)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("mainWindow")
        self.setStyleSheet(owner.styleSheet())
        self.setWindowTitle("Comparison — " + self.variant["name"])
        self.resize(760, 800)
        self.setMinimumSize(440, 420)
        self.titlebar = TitleBar(self)
        self.titlebar.set_caption(self.windowTitle())
        self.setMenuWidget(self.titlebar)
        self.mode = self.view.get("mode", "strip")
        self.selected_frame, self.selected_manual = None, False
        self.current_page = 0
        self._strip_key = None
        self._strip_cards = []
        self._strip_size = (1, 1)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit_view)
        self.pages = group_pages(self.variant["proposals"], self.analysis.get("manual_frames") or [],
                                 include_leading_extras=True)
        dimensions = {name: (width, height) for name, width, height in FORMATS}
        self.page_size = dimensions.get(self.view.get("page_format"), (148, 210))
        if self.view.get("page_format") == "Custom":
            self.page_size = (self.view.get("custom_width", 148), self.view.get("custom_height", 210))
        if self.view.get("orientation") == "landscape":
            self.page_size = tuple(reversed(self.page_size))
        self.ratio = frame_ratio(self.view.get("frame_format", "Source"),
                                 self.view.get("frame_custom_width", 16), self.view.get("frame_custom_height", 9))

        root = QWidget()
        column = QVBoxLayout(root)
        column.setContentsMargins(10, 8, 10, 8)
        column.setSpacing(8)
        self.name_label = QLabel(self.variant["name"])
        self.name_label.setStyleSheet(f"color: {ACCENT}; font-weight: 600;")
        self.name_label.setWordWrap(True)
        column.addWidget(self.name_label)
        note = QLabel("Read-only · same analysis and settings\nAutomatic comparison · MP manual edits excluded")
        note.setToolTip("Existing Resolve markers remain protected. These views compare fresh automatic proposals without changing your current review.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {TEXT_MUTED};")
        column.addWidget(note)
        proposals = self.variant["proposals"]
        cores = sum(item["color"] in (PAGE, CORE) for item in proposals)
        extras = sum(item["color"] == EXTRA for item in proposals)
        self.summary = QLabel(f"{len(self.pages)} pages · {cores} Core incl. starts · {extras} Extras")
        self.summary.setWordWrap(True)
        column.addWidget(self.summary)
        timeline = self.analysis.get("timeline_name") or "Analyzed timeline"
        self.timeline_label = QLabel(timeline)
        self.timeline_label.setWordWrap(True)
        self.timeline_label.setStyleSheet(f"color: {TEXT_MUTED};")
        column.addWidget(self.timeline_label)

        controls = QHBoxLayout()
        self.strip_button, self.board_button = QPushButton("Strip"), QPushButton("Board")
        modes = QButtonGroup(self)
        modes.setExclusive(True)
        for button, mode in ((self.strip_button, "strip"), (self.board_button, "board")):
            button.setCheckable(True)
            button.setProperty("role", "mode")
            button.clicked.connect(lambda _checked=False, value=mode: self.set_mode(value))
            modes.addButton(button)
            controls.addWidget(button)
        self.filter = QComboBox()
        for text, key in (("All images", "all"), ("Core", "core"), ("Page starts", "starts")):
            self.filter.addItem(text, key)
        self.filter.setCurrentIndex(max(0, self.filter.findData(self.view.get("view_filter", "all"))))
        self.filter.currentIndexChanged.connect(lambda _index: self._render_current())
        controls.addWidget(self.filter, 1)
        self.fit = QPushButton("Fit")
        self.fit.setToolTip("Show the complete page or fixed image arrangement")
        self.fit.clicked.connect(self.fit_view)
        controls.addWidget(self.fit)
        column.addLayout(controls)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.page_list = QTreeWidget()
        self.page_list.setHeaderLabels(["Pages"])
        self.page_list.setRootIsDecorated(False)
        self.page_list.setMinimumWidth(100)
        self.page_list.setMaximumWidth(230)
        self.page_list.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.page_list.setStyleSheet("QTreeWidget::item { padding: 6px; }")
        for index, page in enumerate(self.pages):
            item = QTreeWidgetItem([f"Page {page['number']} · {len(page['items'])} images"])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            item.setToolTip(0, self.timecode(page["id"]))
            self.page_list.addTopLevelItem(item)
        self.page_list.currentItemChanged.connect(self._page_changed)
        self.splitter.addWidget(self.page_list)
        self.stack = QStackedWidget()
        self.strip = ComparisonStrip()
        self.strip.set_preview_quality(self.view.get("preview_quality", "Medium"))
        self.strip_canvas = QWidget()
        self.strip.setWidget(self.strip_canvas)
        self.board = ComparisonBoard()
        self.board.preview_quality = self.view.get("preview_quality", "Medium")
        self.board.show_labels = self.view.get("show_board_labels", True)
        self.board.image_ratio = self.ratio or 16 / 9
        self.board.crop_images = self.ratio is not None
        self.board.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.board.setAcceptDrops(False)
        self.board.chosen.connect(self.select_frame)
        self.board.opened.connect(self.select_frame)
        # Context and drag signals intentionally have no receivers: this viewer
        # never routes them to the marker editor or the Resolve bridge.
        self.stack.addWidget(self.strip)
        self.stack.addWidget(self.board)
        self.splitter.addWidget(self.stack)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([155, 580])
        column.addWidget(self.splitter, 1)
        self.caption = QLabel("No proposed markers.")
        self.caption.setWordWrap(True)
        column.addWidget(self.caption)
        self.warning_label = QLabel("\n".join(self.variant.get("warnings") or []))
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(f"color: {TEXT_MUTED};")
        self.warning_label.setVisible(bool(self.variant.get("warnings")))
        self.warning_label.setMaximumHeight(65)
        self.warning_label.setToolTip(self.warning_label.text())
        column.addWidget(self.warning_label)
        self.setCentralWidget(root)
        self.set_mode(self.mode)
        if self.pages:
            self.select_page(0)
        for key, callback in ((Qt.Key.Key_Left, lambda: self._step(-1)),
                              (Qt.Key.Key_Right, lambda: self._step(1)),
                              (Qt.Key.Key_PageUp, lambda: self.select_page(self.current_page - 1)),
                              (Qt.Key.Key_PageDown, lambda: self.select_page(self.current_page + 1))):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)

    def timecode(self, frame):
        base = self.analysis.get("timebase") or {"fps": self.analysis.get("fps", 24)}
        return format_timecode(int(frame), base)

    def select_page(self, index):
        if self.pages:
            self.page_list.setCurrentItem(self.page_list.topLevelItem(max(0, min(len(self.pages) - 1, index))))

    def _page_changed(self, current, _previous):
        if current is None:
            return
        self.current_page = current.data(0, Qt.ItemDataRole.UserRole)
        from vispa_mp.ui import item_frame
        page = self.pages[self.current_page]
        if page["items"]:
            self.selected_frame = item_frame(page["items"][0])
            self.selected_manual = page["items"][0]["manual"]
        self._render_current()

    def _view_items(self):
        if not self.pages:
            return []
        items = self.pages[self.current_page]["items"]
        key = self.filter.currentData()
        if key == "starts":
            return [item for page in self.pages for item in page["items"]
                    if not item["manual"] and item["proposal"]["color"] == PAGE]
        if key == "core":
            return [item for item in items if not item["manual"] and item["proposal"]["color"] in (PAGE, CORE)]
        return items

    def set_mode(self, mode):
        self.mode = "board" if mode == "board" else "strip"
        self.strip_button.setChecked(self.mode == "strip")
        self.board_button.setChecked(self.mode == "board")
        self.stack.setCurrentWidget(self.board if self.mode == "board" else self.strip)
        self._render_current()
        self._fit_timer.start(0)

    def select_frame(self, frame, manual=False):
        self.selected_frame, self.selected_manual = int(frame), bool(manual)
        self.board.selected, self.board.selected_manual = self.selected_frame, self.selected_manual
        self.board.update()
        self._paint_strip_selection()
        self._update_caption()

    def _render_current(self):
        items = self._view_items()
        self.board.set_page(items, self.page_size, self.selected_frame, self.selected_manual)
        self._render_strip(items)
        self._update_caption()

    def _render_strip(self, items):
        from vispa_mp.ui import MANUAL_DOT, SWATCH, item_frame
        key = tuple((item_frame(item), item["manual"]) for item in items)
        if key == self._strip_key:
            self._paint_strip_selection()
            return
        self._strip_key = key
        for _item, card, _color in self._strip_cards:
            card.deleteLater()
        self._strip_cards = []
        if not items:
            self.strip.set_content_size(1, 1)
            return
        width, gap = 220, 10
        image_height = round(width / (self.ratio or 16 / 9))
        height = image_height + 42
        columns = balanced_columns(len(items), self.strip.viewport().width(), self.strip.viewport().height(), width, height, gap)
        for index, item in enumerate(items):
            number = item_frame(item)
            proposal = item.get("proposal") or {}
            color = MANUAL_DOT if item["manual"] else SWATCH.get(proposal.get("color"), ACCENT)
            card = ComparisonCard(self.strip_canvas)
            card.setFixedSize(width, height)
            card.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            card.setAccessibleName(f"Image at {self.timecode(number)}")
            card.clicked.connect(lambda frame=number, manual=item["manual"]: self.select_frame(frame, manual))
            layout = QVBoxLayout(card)
            layout.setContentsMargins(3, 3, 3, 3)
            layout.setSpacing(3)
            image = CanvasImage()
            image.set_preview_quality(self.view.get("preview_quality", "Medium"))
            image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            image.setMinimumHeight(image_height)
            image.set_source(proposal.get("image") or "", color)
            image.set_frame_format(self.view.get("frame_format", "Source"), self.view.get("frame_custom_width", 16), self.view.get("frame_custom_height", 9))
            layout.addWidget(image, 1)
            role = "Manual · kept" if item["manual"] else {PAGE: "Page start", CORE: "Core", EXTRA: "Extra"}.get(proposal.get("color"), "Marker")
            label = QLabel(f"{role} · {self.timecode(number)}")
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            row, column = divmod(index, columns)
            card.move(column * (width + gap), row * (height + gap))
            card.show()
            self._strip_cards.append((item, card, color))
        self._strip_size = (columns * width + max(0, columns - 1) * gap,
                            ceil(len(items) / columns) * height + max(0, ceil(len(items) / columns) - 1) * gap)
        self.strip.set_content_size(*self._strip_size)
        self.fit_view()
        self._paint_strip_selection()

    def _paint_strip_selection(self):
        from vispa_mp.ui import item_frame
        for item, card, color in self._strip_cards:
            selected = item_frame(item) == self.selected_frame and item["manual"] == self.selected_manual
            card.setStyleSheet(f"ComparisonCard {{ background: {APP_BG}; border: {3 if selected else 2}px solid {ACCENT if selected else color}; }}")

    def _update_caption(self):
        if self.selected_frame is None or not self._view_items():
            self.caption.setText("No images selected with these rules or this filter.")
            return
        page = self.pages[self.current_page] if self.pages else None
        prefix = f"Page {page['number']} · " if page else ""
        self.caption.setText(prefix + self.timecode(self.selected_frame) + " · Wheel: zoom · Middle button: pan")

    def fit_view(self):
        if self.mode == "board":
            self.board.zoom, self.board.offset = 1.0, QPointF()
            self.board.update()
        else:
            width, height = self._strip_size
            self.strip.scale = min(1.0, max(0.08, min(max(1, self.strip.viewport().width() - 24) / width,
                                                    max(1, self.strip.viewport().height() - 24) / height)))
            self.strip.set_scale(self.strip.scale)

    def _step(self, direction):
        from vispa_mp.ui import item_frame
        items = self._view_items()
        if not items:
            return
        numbers = [(item_frame(item), item["manual"]) for item in items]
        current = (self.selected_frame, self.selected_manual)
        index = numbers.index(current) if current in numbers else 0
        self.select_frame(*numbers[max(0, min(len(items) - 1, index + direction))])

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_timer.start(0)

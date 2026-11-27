"""Review proposed markers, then write them to Resolve.

Strip and Board are two views of one selection. The orange playhead stays
inside this window: dragging the Video 1 ruler does not move Resolve.
"""

import os
import re
import threading
import uuid
from functools import partial
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPalette, QPen, QPixmap, QPolygon, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QStackedWidget, QTabWidget, QToolButton, QVBoxLayout,
    QWidget, QMainWindow, QFileDialog, QMenu,
)

from shiboken6 import isValid

from vispa_mp.application_identity import create_vispa_mp_application
from vispa_mp.analyze import analysis_key, analyze, refresh_utterances, saved_analysis
from vispa_mp.client import open_client
from vispa_mp.learning_evaluation_ui import LearningEvaluationMixin
from vispa_mp.learning_batch_ui import LearningBatchMixin
from vispa_mp.learning_ui import LearningReviewMixin
from vispa_mp.learning_profile_ui import LearningProfilePanel
from vispa_mp.comparison_review import ComparisonReviewMixin
from vispa_mp.suggestions_review import SuggestionsReviewMixin
from vispa_mp.suggestion_selection import SuggestionCard
from vispa_mp.marker_budget_ui import MarkerBudgetMixin
from vispa_mp.resolve_link import free_script_installed, link_running
from vispa_mp.resolve_source_label import ResolveSourceLabel
from vispa_mp.markers import CORE, EXTRA, NAMES, PAGE
from vispa_mp.page_layout import capture_layout, move_frames, reconcile_layout
from vispa_mp.preset import PREVIEW_QUALITIES, SAVED_DIR, export_settings, import_settings, load, load_user, save_user
from vispa_mp.preview import FRAME_FORMATS, draw_preview, frame_ratio
from vispa_mp.project_ui import ProjectReviewMixin
from vispa_mp.review_camera import ReviewCameraMixin
from vispa_mp.review_counts import PanelCounter
from vispa_mp.review_report import ReviewReportMixin
from vispa_mp.review_drag import MarkerDragCard, PageMarkerRow, PagesDropMixin, start_marker_drag
from vispa_mp.review_history import ReviewHistoryMixin, review_edit
from vispa_mp.review_multi_selection import ReviewMultiSelectionMixin
from vispa_mp.review_panes import ReviewSplitter, SuggestionArea, WorkspaceSplitter
from vispa_mp.rules import _cavity, analyzed_minutes, core_target, page_goal, propose, target_pages
from vispa_mp.snapshot import describe_rate, normalize
from vispa_mp.strip_canvas import CanvasImage, StripCanvasView, _source_pixmap, balanced_columns
from vispa_mp.timebase import format_timecode
from vispa_mp.timeline_identity import normalize_identity
from vispa_mp.timeline_ruler import TimelineRuler as Ruler
from vispa_mp.timeline_review import TimelineReviewMixin
from vispa_mp.ui_tokens import (
    ACCENT, APP_BG, BAR_BG, BORDER_ROW, BORDER_STRONG, CONTROL, CONTROL_BG, HEADER_CONTROL, HEADER_HEIGHT, MONO_FAMILY, PANEL_BG,
    PANEL_TITLE_BG, PAGE_DROP_BG, PAGE_DROP_ACCENT, PLAYHEAD, PRIMARY_BG, RADIUS, SELECTED_ROW, TEXT_FAMILY,
    TEXT_MAIN, TEXT_MUTED, TEXT_SECONDARY, window_stylesheet,
)
from vispa_mp.window_chrome import BORDER_COLOUR, ChromeDialog, TitleBar, WindowChromeMixin

ICONS = Path(__file__).resolve().parent / "icons"
LINE = "#1F4250"  # the one-pixel line between two surfaces
THUMB_W, THUMB_H = 192, 108  # the largest 16:9 still on a page card
FILTERS = (("all", "All images"), ("core", "Core"), ("starts", "Page starts"))
ZOOM_HINT = "Wheel: zoom · Wheel held down and dragged: pan"
CARD_TEXT = 64  # timecode, caption and room for the independent status/selection outlines
SWATCH = {"Green": "#3c8c4a", "Blue": "#2f6fed", "Cyan": "#3ec2d6"}
MANUAL_DOT = "#8AA0A8"
COLOR_LABEL = {"Green": "Page start", "Blue": "Core", "Cyan": "Extra"}
FORMATS = (("A5", 148, 210), ("A4", 210, 297), ("B5", 176, 250), ("Custom", None, None))
SLIDER_SCALE = {"compression": 100, "mouth_min": 100, "sharpness_floor": 2}
INTEGERS = {
    "speech_min_silence_ms", "speech_min_duration_ms", "speech_pad_ms",
    "action_extras", "candidates_per_line",
    "target_pages_min", "target_pages_max", "core_page_min", "core_page_max",
    "total_page_min", "total_page_max", "episode_minutes",
}
SPINS = (
    ("end_fraction", "End of shot, share of the shot", 0.05, 0.9, 0.05),
    ("sharpness_ratio", "Sharpness against the shot, minimum", 0, 1, 0.05),
    ("motion_blur_max", "Motion blur, maximum", 0, 1, 0.05),
    ("hold_ratio", "Held drawing, tolerance", 0.5, 3, 0.05),
    ("min_marker_seconds", "Time between markers, minimum (s)", 0, 4, 0.05),
    ("expression_weight", "Facial expression, weight", 0, 1, 0.05),
    ("speech_min_silence_ms", "Silence separation (ms)", 40, 2000, 10),
    ("speech_min_duration_ms", "Line length, minimum (ms)", 40, 2000, 10),
    ("speech_threshold", "Speech probability, minimum", 0.05, 0.95, 0.05),
    ("speech_pad_ms", "Margin around a line (ms)", 0, 400, 10),
    ("action_max_seconds", "Action shot length, maximum (s)", 0.2, 10, 0.1),
    ("action_motion", "Action shot motion, minimum", 0, 80, 0.5),
    ("action_extras", "Extras per action shot", 0, 8, 1),
    ("min_extra_seconds", "Time between Extras, minimum (s)", 0, 4, 0.01),
    ("action_structure", "Action drawing change, minimum", 0, 2, 0.05),
    ("duplicate_diff", "Look-alike images, difference", 0, 40, 0.5),
    ("scene_grey", "Scene change, brightness", 0, 120, 1),
    ("scene_colour", "Scene change, colors", 0, 1, 0.05),
    ("group_min", "Group shot, confidence", 0, 1, 0.05),
    ("min_green_seconds", "Time between pages, minimum (s)", 0, 30, 0.25),
    ("target_pages_min", "Pages, minimum", 1, 400, 1),
    ("target_pages_max", "Pages, maximum", 1, 400, 1),
    ("core_page_min", "Core images, minimum", 0, 30, 1),
    ("core_page_max", "Core images, maximum", 1, 30, 1),
    ("core_page_target", "Core images, target average (0 = off)", 0, 30, 0.5),
    ("total_page_min", "All images, minimum", 0, 40, 1),
    ("total_page_max", "All images, maximum", 1, 40, 1),
    ("candidates_per_line", "Images examined per line", 1, 8, 1),
    ("long_shot_seconds", "Decompose shots longer than (s)", 1, 120, 0.1),
    ("episode_minutes", "Episode length (min)", 0, 180, 1),
)

SPIN_OF = {key: (label, low, high, step) for key, label, low, high, step in SPINS}
CORE_TIP = "Green and blue markers of one page: the page start and its Core images."
ALL_TIP = "Every marker of one page: Core images and the cyan Extras."
TIPS = {
    "target_pages_min": "Pages for a whole episode. A shorter In/Out range gets its share.",
    "target_pages_max": "Pages for a whole episode. A shorter In/Out range gets its share.",
    "episode_minutes": "The length the page counts are for. 0 applies them to whatever is analyzed.",
    "core_page_min": CORE_TIP,
    "core_page_max": CORE_TIP,
    "core_page_target": ("A soft average of green and blue markers per page. Cyan Extras do not count. "
                         "Page and image limits still apply. 0 keeps the compression setting in charge."),
    "total_page_min": ALL_TIP,
    "total_page_max": ALL_TIP,
    "min_green_seconds": "Two page starts are never closer than this.",
    "scene_grey": "How much the brightness must jump at a cut for a new page to open.",
    "scene_colour": "How much the colors must change at a cut for a new page to open.",
    "group_min": "How sure the recognition must be that several characters are in view to open a page.",
    "end_fraction": "The last part of a shot where its Core image is looked for. 0.30 is the last 30 %.",
    "sharpness_ratio": "An image must reach this share of the sharpest image of its shot.",
    "motion_blur_max": "Images the recognition finds more blurred than this are left out.",
    "hold_ratio": "How close an image must stay to its neighbours to count as a held drawing.",
    "expression_weight": "How much a visible expression (smile, anger, surprise) favours an image.",
    "min_marker_seconds": "Two markers of the same shot are never closer than this.",
    "duplicate_diff": "Below this difference an Extra is too close to a Core image and is dropped.",
    "action_max_seconds": "Shots up to this length with a lot of motion get Extras.",
    "action_motion": "How much a shot must move to count as action.",
    "action_structure": "Drawing changes after contrast normalization, including repeated animation frames. Lower finds more action candidates.",
    "min_extra_seconds": "Minimum spacing for Extra candidates. Core marker spacing stays separate.",
    "speech_threshold": "How sure the speech detection must be. Lower finds quieter lines.",
    "speech_min_silence_ms": "A silence this long splits two lines.",
    "speech_min_duration_ms": "Shorter sounds are not lines.",
    "speech_pad_ms": "Time added before and after each line.",
    "candidates_per_line": "Images of each line sent to the recognition. More is slower.",
    "split_long_shots": ("Look for sustained framing or brightness changes inside long shots. "
                         "Static shots stay whole; each detected part keeps its own end-of-shot preference. "
                         "Run Analyze again after changing this setting; Recalculate alone cannot find new parts."),
    "long_shot_seconds": ("Search for internal visual changes only in shots longer than this duration, in seconds. "
                          "4.30 means 4.3 seconds, not a timecode or a fixed marker interval. "
                          "Run Analyze again after changing this setting."),
}
CHECKS = {
    "require_open_mouth": "A line needs an open mouth",
    "keep_second_mouth": "Add a second open mouth as an Extra",
    "skip_marked_shots": "Skip shots that already have markers",
    "use_in_out": "Analyze only the In/Out range",
    "split_long_shots": "Decompose long shots",
}
# Settings window: tab, then sections of (title, keys). "compression" and
# "mouth_fallback" are built apart; every other key is a spin box or a check box.
SETTINGS_TABS = (
    ("Pages", (
        ("", ("_global_marker_budget",)),
        ("Pages per episode", ("target_pages_min", "target_pages_max", "episode_minutes")),
        ("Images per page",
         ("core_page_min", "core_page_max", "core_page_target", "total_page_min", "total_page_max")),
        ("New page", ("min_green_seconds", "scene_grey", "scene_colour", "group_min")),
    )),
    ("Images", (
        ("Choosing an image", ("end_fraction", "sharpness_ratio", "motion_blur_max", "hold_ratio",
                               "expression_weight")),
        ("Spacing", ("min_marker_seconds", "duplicate_diff")),
        ("Action shots", ("action_max_seconds", "action_motion", "action_structure", "action_extras", "min_extra_seconds")),
    )),
    ("Speech", (
        ("Dialogue analysis", ("_dialogue_status",)),
        ("Lines", ("speech_threshold", "speech_min_silence_ms", "speech_min_duration_ms", "speech_pad_ms")),
        ("Mouths", ("require_open_mouth", "mouth_fallback", "keep_second_mouth")),
    )),
    ("Analysis", (
        ("What is read", ("use_in_out", "skip_marked_shots")),
        ("Long shots", ("split_long_shots", "long_shot_seconds")),
        ("Images examined", ("candidates_per_line",)),
    )),
)


def _icon(name):
    return (ICONS / name).as_posix()


def separator(vertical=False):
    """A one-pixel line where two surfaces meet."""
    line = QFrame()
    line.setProperty("role", "line")
    if vertical:
        line.setFixedWidth(1)
    else:
        line.setFixedHeight(1)
    return line


def dark_palette():
    """Fusion's colours for what the stylesheet does not draw: check boxes, popups, selections."""
    palette = QPalette()
    for role, colour in (
        (QPalette.ColorRole.Window, PANEL_BG), (QPalette.ColorRole.WindowText, TEXT_MAIN),
        (QPalette.ColorRole.Base, APP_BG), (QPalette.ColorRole.AlternateBase, BAR_BG),
        (QPalette.ColorRole.Text, TEXT_MAIN), (QPalette.ColorRole.Button, CONTROL_BG),
        (QPalette.ColorRole.ButtonText, TEXT_MAIN), (QPalette.ColorRole.Highlight, SELECTED_ROW),
        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.ToolTipBase, BAR_BG),
        (QPalette.ColorRole.ToolTipText, TEXT_MAIN), (QPalette.ColorRole.PlaceholderText, TEXT_MUTED),
    ):
        palette.setColor(role, QColor(colour))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(TEXT_MUTED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(TEXT_MUTED))
    return palette


# Rule warnings that come once per page or per line, told once with their count.
FOLDED = (
    (re.compile(r"^Page at frame \d+: .* below the minimum\.$"),
     "{n} pages have fewer images than the minimum (Settings › Pages › Images per page)."),
    (re.compile(r"^Page at frame \d+: the minimum keeps the page above the maximum\.$"),
     "{n} pages stay above the maximum because of the minimum."),
    (re.compile(r"^Line at frame \d+ has no examined image\.$"),
     "{n} lines have no examined image."),
)


def fold_warnings(lines):
    """Several warnings of one kind become one line; the full list stays in the tooltip."""
    shown, counts = [], {}
    for line in lines:
        for pattern, summary in FOLDED:
            if pattern.match(line):
                if summary not in counts:
                    shown.append(summary)
                counts[summary] = counts.get(summary, 0) + 1
                break
        else:
            shown.append(line)
    folded = []
    for line in shown:
        if line in counts:
            if counts[line] == 1:
                folded.append(next(item for item in lines
                                   for pattern, summary in FOLDED if summary == line and pattern.match(item)))
            else:
                folded.append(line.format(n=counts[line]))
        else:
            folded.append(line)
    return folded


def group_pages(proposals, manual_frames, include_leading_extras=False):
    """One row per page. A green starts a page; later markers belong to it."""
    ordered = sorted((dict(item) for item in proposals), key=lambda item: int(item["frame"]))
    taken = {int(item["frame"]) for item in ordered}
    manuals = [int(frame) for frame in manual_frames if int(frame) not in taken]
    events = [("proposal", item) for item in ordered] + [("manual", frame) for frame in manuals]
    events.sort(key=lambda event: int(event[1]["frame"]) if event[0] == "proposal" else int(event[1]))
    pages, current = [], None

    def open_page(frame):
        nonlocal current
        current = {"id": int(frame), "items": []}
        pages.append(current)

    for kind, payload in events:
        if kind == "proposal" and payload["color"] == PAGE:
            leading_extras = (include_leading_extras and current is not None
                              and not any(not item["manual"] and item["proposal"]["color"] in (PAGE, CORE)
                                          for item in current["items"]))
            if leading_extras:
                current["id"] = int(payload["frame"])
            else:
                open_page(payload["frame"])
            current["items"].append({"manual": False, "proposal": payload})
            continue
        if current is None:
            open_page(payload["frame"] if kind == "proposal" else payload)
        if kind == "proposal":
            current["items"].append({"manual": False, "proposal": payload})
        else:
            current["items"].append({"manual": True, "frame": int(payload)})
    for number, page in enumerate(pages, start=1):
        page["number"] = number
    return pages


def item_frame(item):
    return int(item["frame"] if item["manual"] else item["proposal"]["frame"])


def short_note(note):
    text = (note or "").strip()
    if text.startswith("Page start"):
        return "Page start"
    if text.startswith("Core") or text.startswith("Body"):
        return "Core"
    if "not verified" in text:
        return "Mouth not verified"
    if "mouth open" in text:
        return "Mouth open"
    if text.startswith("Extra"):
        return "Extra"
    if text.startswith("Line"):
        return "Line"
    return text or "Marker"


def motif_of(frame, settings):
    """Why this cached frame is worth a look. No new inference."""
    blur = float(frame.get("motion_blur") or 0)
    if blur > float(settings.get("motion_blur_max", 0.5)):
        return "blurry"
    opened = float(frame.get("open_mouth") or 0)
    closed = float(frame.get("closed_mouth") or 0)
    if opened >= float(settings.get("mouth_min", 0.2)) and opened > closed:
        return f"mouth {opened:.2f}"
    if frame.get("hold"):
        return "hold"
    return "sharp"


class Worker(QThread):
    done = Signal(object)
    failed = Signal(str)
    progressed = Signal(object)  # a text, or a step of an analysis (a dict)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(self.progressed.emit))
        except Exception as error:
            self.failed.emit(str(error))


class StepBar(QWidget):
    """VISPA's loading bar, cut into one segment per step.

    Finished steps are full, the running one fills from the left, the others
    show their empty track, so the start, the end and the step are all visible.
    """

    GAP = 3

    def __init__(self):
        super().__init__()
        self.steps = 5
        self.step = 0
        self.fraction = 0.0
        self.setFixedSize(220, 10)

    def set_progress(self, step, steps, fraction):
        self.step, self.steps, self.fraction = int(step), max(1, int(steps)), float(fraction)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = (self.width() - self.GAP * (self.steps - 1)) / self.steps
        for index in range(self.steps):
            x = index * (width + self.GAP)
            track = QRect(int(round(x)), 0, int(round(width)), self.height())
            painter.setPen(QPen(QColor(BORDER_ROW), 1))
            painter.setBrush(QColor(APP_BG))
            painter.drawRoundedRect(track.adjusted(0, 0, -1, -1), 3, 3)
            number = index + 1
            filled = 1.0 if number < self.step else self.fraction if number == self.step else 0.0
            if filled > 0:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(PRIMARY_BG if number < self.step else ACCENT))
                painter.drawRoundedRect(QRect(track.x(), 0, max(4, int(track.width() * filled)), self.height()), 3, 3)
        painter.end()


class StepProgress(QWidget):
    """Bottom left during an analysis: the bar, « 2/5 Finding the shots · 45 % », the detail, the time left."""

    def __init__(self):
        super().__init__()
        self.setObjectName("stepProgress")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.bar = StepBar()
        self.step_label = QLabel("")
        self.step_label.setObjectName("stepLabel")
        self.percent = QLabel("")
        self.percent.setObjectName("stepPercent")
        self.detail = QLabel("")
        self.detail.setProperty("role", "muted")
        self.left = QLabel("")
        self.left.setObjectName("stepLeft")
        row.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.step_label)
        row.addWidget(self.percent)
        row.addWidget(self.detail)
        row.addWidget(self.left)
        self.hide()

    def show_step(self, value):
        self.bar.set_progress(value["step"], value["steps"], value["fraction"])
        self.step_label.setText(f"{value['step']}/{value['steps']}  {value['label']}")
        self.percent.setText(f"{int(value['fraction'] * 100)} %")
        self.detail.setText(value.get("detail") or "")
        self.detail.setVisible(bool(value.get("detail")))
        self.left.setText(value.get("left") or "")
        self.left.setVisible(bool(value.get("left")))
        self.show()


def left_click_only(callback):
    """A card's click: the left button acts, the others go to the view (wheel drag pans)."""
    def handler(event):
        if event.button() == Qt.MouseButton.LeftButton:
            callback()
        else:
            event.ignore()
    return handler


def note_caption(note):
    """« Core · end of shot » from the rule's note « Core, end of shot »."""
    return (note or "Marker").replace(", ", " · ", 1)


class Message(ChromeDialog):
    """VISPA's own question or notice: its caption, a heading, a line of detail, its buttons."""

    def __init__(self, parent, title, heading, text="", accept="OK", cancel=None):
        super().__init__(parent, title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setStyleSheet(_theme())
        column = QVBoxLayout(self.body)
        column.setContentsMargins(24, 20, 24, 18)
        column.setSpacing(6)
        head = QLabel(heading)
        head.setObjectName("messageHeading")
        head.setWordWrap(True)
        column.addWidget(head)
        if text:
            detail = QLabel(text)
            detail.setProperty("role", "muted")
            detail.setWordWrap(True)
            column.addWidget(detail)
        column.addSpacing(18)
        row = QHBoxLayout()
        self.button_row = row
        row.setSpacing(8)
        row.addStretch(1)
        if cancel:
            self.cancel_button = QPushButton(cancel)
            self.cancel_button.clicked.connect(self.reject)
            row.addWidget(self.cancel_button)
        self.accept_button = QPushButton(accept)
        self.accept_button.setProperty("primary", True)
        self.accept_button.setDefault(True)
        self.accept_button.clicked.connect(self.accept)
        row.addWidget(self.accept_button)
        column.addLayout(row)

    @classmethod
    def ask(cls, parent, title, heading, text, accept, cancel="Cancel"):
        return cls(parent, title, heading, text, accept, cancel).exec() == QDialog.DialogCode.Accepted

    @classmethod
    def tell(cls, parent, title, heading, text=""):
        cls(parent, title, heading, text).exec()

    @classmethod
    def save_changes(cls, parent):
        dialog = cls(parent, "Unsaved project", "Save your marker preparation?",
                     "Your image choices, marker colors and settings have not been saved.", "Save project", "Cancel")
        discard = QPushButton("Discard")
        discard.clicked.connect(lambda: dialog.done(2))
        dialog.button_row.insertWidget(1, discard)
        result = dialog.exec()
        return "save" if result == QDialog.DialogCode.Accepted else "discard" if result == 2 else "cancel"


class MarkerDot(QWidget):
    def __init__(self, color):
        super().__init__()
        self.color = QColor(color)
        self.setFixedSize(14, 14)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        painter.drawEllipse(2, 2, 10, 10)


class PagesPanel(PagesDropMixin, QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setObjectName("pages")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._init_page_drop(owner)

    def keyPressEvent(self, event):
        if self._page_step(event):
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and self._page_step(event):
            return True
        return super().eventFilter(watched, event)

    def _page_step(self, event):
        if not (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            return False
        if event.key() == Qt.Key.Key_Up:
            self.owner._step_page(-1)
            return True
        if event.key() == Qt.Key.Key_Down:
            self.owner._step_page(1)
            return True
        return False


class PageBoard(QWidget):
    """A plain reading-order preview. It does not write a VISPA layout."""

    chosen = Signal(int, bool)
    additive_chosen = Signal(int, bool)
    range_chosen = Signal(int, bool, bool)
    opened = Signal(int, bool)
    context_requested = Signal(int, bool, QPoint)
    drag_requested = Signal(int)
    view_interaction = Signal()
    view_changed = Signal()

    def __init__(self):
        super().__init__()
        self.items = []
        self.size_mm = (148, 210)
        self.selected = None
        self.selected_manual = False
        self.selected_keys = set()
        self._hits = []
        self.preview_quality = "Medium"
        self.zoom = 1.0
        self.offset = QPointF(0, 0)
        self._pan = None
        self._drag_frame = None
        self._drag_start = None
        self._deferred_chosen = None
        self.preview = ""
        self.flash = None
        self.show_labels = True
        self.image_ratio = 16 / 9
        self.crop_images = False
        self._shown = None
        self.setToolTip(ZOOM_HINT + " · Shift+click: select a range · Ctrl+Shift+click: add a range")

    def set_page(self, items, size_mm, selected, selected_manual, selected_keys=None, preserve_view=False):
        shown = tuple(item_frame(item) for item in items)
        if shown != self._shown:
            if not preserve_view:
                self.zoom, self.offset = 1.0, QPointF(0, 0)
            self._shown = shown
        self.items = list(items)
        self.size_mm = size_mm
        self.selected = selected
        self.selected_manual = selected_manual
        if selected_keys is None:
            self.selected_keys = {(int(selected), bool(selected_manual))} if selected is not None else set()
        else:
            self.selected_keys = {(int(frame), bool(manual)) for frame, manual in selected_keys}
        self.update()

    def _view_rect(self):
        base = QRectF(self._page_rect())
        width, height = base.width() * self.zoom, base.height() * self.zoom
        centre = base.center() + self.offset
        return QRectF(centre.x() - width / 2, centre.y() - height / 2, width, height)

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120
        if not steps or not self.items:
            return
        self.view_interaction.emit()
        before = self._view_rect()
        zoom = min(8.0, max(1.0, self.zoom * (1.2 ** steps)))
        if zoom == self.zoom:
            return
        point = event.position()
        share_x = (point.x() - before.x()) / max(1.0, before.width())
        share_y = (point.y() - before.y()) / max(1.0, before.height())
        base = QRectF(self._page_rect())
        width, height = base.width() * zoom, base.height() * zoom
        centre = QPointF(point.x() - share_x * width + width / 2, point.y() - share_y * height + height / 2)
        self.zoom = zoom
        self.offset = QPointF(0, 0) if zoom == 1.0 else centre - base.center()
        self.update()
        self.view_changed.emit()
        event.accept()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(APP_BG))
        self._hits = []
        if not self.items:
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Read the timeline, then analyze.")
            return
        page = self._view_rect().toRect()
        painter.fillRect(page, QColor("#f7f4ee"))
        for item, rect in self._card_rects(page):
            self._hits.append((rect, item))
            if rect.intersects(self.rect()):
                self._paint_card(painter, item, rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.view_interaction.emit()
            self._pan = (event.position(), QPointF(self.offset))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        item = self._item_at(event.position().toPoint())
        if item is not None:
            additive = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            extending = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._drag_frame = None if item["manual"] or additive or extending else item_frame(item)
            self._drag_start = None if additive or extending else event.globalPosition()
            grouped = ((item_frame(item), bool(item["manual"])) in self.selected_keys
                       and len(self.selected_keys) > 1 and not additive and not extending and not item["manual"])
            self._deferred_chosen = (item_frame(item), item["manual"]) if grouped else None
            if extending:
                self.range_chosen.emit(item_frame(item), item["manual"], additive)
            elif not grouped:
                signal = self.additive_chosen if additive else self.chosen
                signal.emit(item_frame(item), item["manual"])
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if (event.button() != Qt.MouseButton.LeftButton
                or event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
            return
        item = self._item_at(event.position().toPoint())
        if item is not None:
            self.opened.emit(item_frame(item), item["manual"])

    def contextMenuEvent(self, event):
        item = self._item_at(event.pos())
        if item is not None:
            self.context_requested.emit(item_frame(item), item["manual"], event.globalPos())
            event.accept()
        else:
            event.ignore()

    def _item_at(self, point):
        for rect, item in self._hits:
            if rect.contains(point):
                return item
        return None

    def mouseMoveEvent(self, event):
        if self._pan is not None:
            start, offset = self._pan
            self.offset = offset + (event.position() - start)
            self.update()
            self.view_changed.emit()
        elif (self._drag_frame is not None and event.buttons() & Qt.MouseButton.LeftButton
              and (event.globalPosition() - self._drag_start).manhattanLength() >= QApplication.startDragDistance()):
            frame, self._drag_frame = self._drag_frame, None
            self._deferred_chosen = None
            self.drag_requested.emit(frame)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_frame = None
            chosen, self._deferred_chosen = self._deferred_chosen, None
            if chosen is not None:
                self.chosen.emit(*chosen)
        if event.button() == Qt.MouseButton.MiddleButton and self._pan is not None:
            self._pan = None
            self.unsetCursor()

    def _page_rect(self):
        width_mm, height_mm = self.size_mm
        ratio = width_mm / max(height_mm, 1)
        margin = 28
        avail = QRect(margin, margin, max(10, self.width() - margin * 2), max(10, self.height() - margin * 2))
        if avail.width() / max(avail.height(), 1) > ratio:
            height = avail.height()
            width = int(height * ratio)
        else:
            width = avail.width()
            height = int(width / ratio)
        x = avail.left() + (avail.width() - width) // 2
        y = avail.top() + max(0, (avail.height() - height) // 8)
        return QRect(x, y, width, height)

    def _card_rects(self, page):
        """Equal frames in reading order, using the selected preview ratio."""
        pad, gutter = 12, 8
        inner = page.adjusted(pad, pad, -pad, -pad)
        count = len(self.items)
        best = None
        for columns in range(1, count + 1):
            rows = (count + columns - 1) // columns
            cell_w = (inner.width() - gutter * (columns - 1)) / columns
            cell_h = (inner.height() - gutter * (rows - 1)) / rows
            width = min(cell_w, cell_h * self.image_ratio)
            if width > 0 and (best is None or width > best[0]):
                best = (width, columns)
        if best is None:
            return []
        width, columns = best
        height = width / self.image_ratio
        left = inner.left() + (inner.width() - (columns * width + gutter * (columns - 1))) / 2
        rects = []
        for index, item in enumerate(self.items):
            row, column = divmod(index, columns)
            rects.append((item, QRect(int(left + column * (width + gutter)), int(inner.top() + row * (height + gutter)),
                                      max(1, int(width)), max(1, int(height)))))
        return rects

    def _paint_card(self, painter, item, rect):
        color = MANUAL_DOT if item["manual"] else SWATCH.get(item["proposal"]["color"], MANUAL_DOT)
        painter.fillRect(rect, QColor("#d7d0c4"))
        path = "" if item["manual"] else (item["proposal"].get("image") or "")
        chosen = (item_frame(item), bool(item["manual"])) in self.selected_keys
        active = item_frame(item) == self.selected and item["manual"] == self.selected_manual
        previewing = active and bool(self.preview)
        if previewing:
            path = self.preview
        pixmap = self._pixmap(path)
        if pixmap is not None and not pixmap.isNull():
            draw_preview(painter, pixmap, QRectF(rect), "#d7d0c4", crop=self.crop_images,
                         quality=self.preview_quality)
        else:
            painter.fillRect(rect.adjusted(8, 8, -8, -8), QColor(color))
        if self.show_labels and rect.width() > 32 and rect.height() > 36:
            note = "manual · kept" if item["manual"] else short_note(item["proposal"].get("note"))
            badge = QRect(rect.left() + 10, rect.top() + 10, min(rect.width() - 20, max(48, 8 * len(note) + 16)), 18)
            painter.fillRect(badge, QColor(color))
            painter.setPen(QColor("#f7f4ee"))
            painter.setFont(QFont(TEXT_FAMILY, 8))
            painter.drawText(badge.adjusted(4, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, note)
        from vispa_mp.review_selection_style import paint_review_frame
        paint_review_frame(painter, rect, color, selected=chosen, preview=previewing,
                           kept=not item["manual"] and item_frame(item) == self.flash)

    def _pixmap(self, path):
        if not path:
            return None
        return _source_pixmap(path)


def _grid(items, x, y, width, height, gutter):
    count = len(items)
    columns = 1 if count == 1 else min(3, count)
    rows = (count + columns - 1) // columns
    cell_w = (width - gutter * (columns - 1)) / columns
    cell_h = (height - gutter * (rows - 1)) / max(rows, 1)
    rects = []
    for index, item in enumerate(items):
        column, row = index % columns, index // columns
        rect = QRect(
            int(x + column * (cell_w + gutter)),
            int(y + row * (cell_h + gutter)),
            max(1, int(cell_w)),
            max(1, int(cell_h)),
        )
        rects.append((item, rect))
    return rects


def _theme():
    return window_stylesheet() + f"""
    QWidget#header, QWidget#footer, QWidget#modeBar {{ background: {BAR_BG}; }}
    QWidget#pages, QWidget#adjust, QWidget#center {{ background: {PANEL_BG}; }}
    QLabel {{ background: transparent; }}
    QLabel#brand {{ color: {ACCENT}; font-weight: 700; font-size: 16px; }}
    QLabel#brandWord, QLabel[role="muted"] {{ color: {TEXT_MUTED}; }}
    QLabel[role="panelTitle"] {{ background: {PANEL_TITLE_BG}; color: {TEXT_MAIN}; font-size: 13px;
        font-weight: 600; padding: 6px 10px; }}
    QLabel[role="resolveDot"][connected="false"] {{ color: #5C7380; }}
    QLabel[role="resolveDot"][connected="true"] {{ color: {ACCENT}; }}
    QLabel[role="alert"] {{ color: {PLAYHEAD}; font-weight: 700; }}
    QLabel#stepLabel {{ color: {TEXT_MAIN}; font-weight: 600; }}
    QLabel#stepPercent {{ color: {ACCENT}; font-family: {MONO_FAMILY}; font-weight: 600; }}
    QLabel#stepLeft {{ color: {TEXT_MAIN}; }}
    QLabel#playhead, QLabel[role="mono"] {{ font-family: {MONO_FAMILY}; font-size: {TEXT_SECONDARY}px; }}
    QPushButton[role="mode"] {{ background: transparent; border: 0; border-bottom: 2px solid transparent;
        border-radius: 0; color: {TEXT_MUTED}; padding: 0 12px; min-height: 30px; max-height: 30px; }}
    QPushButton[role="mode"]:checked {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}
    QPushButton[role="pageName"], QPushButton[role="childName"] {{ background: transparent; border: 0;
        border-radius: 0; text-align: left; padding: 0 8px; font-weight: 600; min-height: 28px; max-height: 28px; }}
    QPushButton[role="childName"] {{ font-weight: 400; }}
    QWidget#pages QWidget[role="pageRow"]:hover, QWidget#pages QWidget[role="childRow"]:hover {{
        background: {CONTROL_BG}; }}
    QWidget#pages QWidget[role="pageRow"][selected="true"] {{ background: {SELECTED_ROW};
        border-left: 3px solid {ACCENT}; }}
    QWidget#pages QWidget[role="childRow"][selected="true"] {{ background: {SELECTED_ROW}; }}
    QWidget#pages QWidget[role="pageRow"][dropTarget="true"],
    QWidget#pages QWidget[role="pageRow"][dropTarget="true"]:hover {{
        background: {PAGE_DROP_BG}; border-left: 3px solid {PAGE_DROP_ACCENT}; }}
    QWidget#pages QWidget[role="pageRow"][dropTarget="true"] QPushButton[role="pageName"] {{
        color: {PAGE_DROP_ACCENT}; }}
    QToolButton[role="historyControl"] {{ padding: 0; min-width: 24px; min-height: 24px; }}
    QToolButton[role="pageArrow"] {{ background: transparent; border: 0; padding: 0; min-width: 28px;
        max-width: 28px; min-height: 28px; max-height: 28px; }}
    QPushButton[role="choice"]:checked {{ background: {SELECTED_ROW}; border-color: {ACCENT}; color: {TEXT_MAIN}; }}
    QPushButton[role="swatch"] {{ padding: 0; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px;
        border: 2px solid transparent; border-radius: {RADIUS}px; }}
    QPushButton[role="swatch"][chosen="true"] {{ border-color: {ACCENT}; }}
    QPushButton[role="swatch"][compact="true"] {{ padding: 0; min-width: 18px; max-width: 18px;
        min-height: 18px; max-height: 18px; border-width: 1px; }}
    QPushButton#analysisDetailsButton[hasWarnings="true"] {{ color: {PAGE_DROP_ACCENT};
        border-color: {PAGE_DROP_ACCENT}; }}
    QPushButton#color-Green {{ background: {SWATCH['Green']}; }}
    QPushButton#color-Blue {{ background: {SWATCH['Blue']}; }}
    QPushButton#color-Cyan {{ background: {SWATCH['Cyan']}; }}
    QFrame[role="card"] {{ background: {BAR_BG}; border: 2px solid #1F4250; border-radius: {RADIUS}px; }}
    QFrame[role="card"]:hover {{ background: {CONTROL_BG}; border-color: {BORDER_STRONG}; }}
    QFrame[role="card"][kind="Green"] {{ border-color: {SWATCH['Green']}; }}
    QFrame[role="card"][kind="Blue"] {{ border-color: {SWATCH['Blue']}; }}
    QFrame[role="card"][kind="Cyan"] {{ border-color: {SWATCH['Cyan']}; }}
    QFrame[role="card"][kind="manual"] {{ border-color: {MANUAL_DOT}; }}
    QFrame[role="card"][kind]:hover {{ background: {CONTROL_BG}; }}
    QFrame[role="card"][selected="true"] {{ background: {SELECTED_ROW}; border: 3px solid {ACCENT}; }}
    QFrame[role="card"][state="preview"], QFrame[role="card"][kind][selected="true"][state="preview"] {{
        background: {SELECTED_ROW}; border: 3px dashed {ACCENT}; }}
    QFrame[role="card"][state="kept"], QFrame[role="card"][kind][selected="true"][state="kept"] {{
        background: #24655c; border: 3px solid #ffffff; }}
    QFrame[role="reviewCard"] {{ background: {BAR_BG}; border: 0; border-radius: {RADIUS}px; }}
    QFrame[role="reviewCard"]:hover {{ background: {CONTROL_BG}; }}
    QFrame[role="reviewCard"][selected="true"] {{ background: {SELECTED_ROW}; }}
    QFrame[role="reviewCard"][state="kept"] {{ background: #24655c; }}
    QLabel#messageHeading {{ font-size: 15px; font-weight: 600; color: {TEXT_MAIN}; }}
    QSlider::groove:horizontal {{ height: 4px; background: #1F4250; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 14px; margin: -6px 0; background: {ACCENT}; border-radius: 7px; }}
    QSlider::sub-page:horizontal {{ background: {PRIMARY_BG}; border-radius: 2px; }}
    QScrollArea {{ background: {PANEL_BG}; border: 0; }}
    QFrame#titlebar {{ background: #1d3947; border: 0; border-bottom: 1px solid #3c5b6b; }}
    QWidget#captionControls {{ background: transparent; }}
    QLabel#caption {{ color: rgba(225, 237, 241, 128); font-family: 'Segoe UI'; font-size: 13px;
        font-weight: 600; }}
    QPushButton[chrome="true"] {{ background: transparent; border: 0; border-radius: 0; padding: 0; margin: 0;
        min-height: 30px; max-height: 30px; min-width: 34px; color: #edf5fa;
        font-family: 'Segoe UI'; font-size: 13px; font-weight: 400; }}
    QPushButton[chrome="true"]:hover {{ background: #31565d; border: 0; color: #edf5fa; }}
    QPushButton#closeButton:hover {{ background: transparent; color: #edf5fa; }}

    QMainWindow#mainWindow {{ background: {BORDER_COLOUR}; }}
    QFrame[role="line"] {{ background: {LINE}; border: 0; }}
    QWidget#header .QWidget, QWidget#footer .QWidget, QWidget#modeBar .QWidget {{ background: transparent; }}
    QWidget#center .QWidget, QWidget#center QStackedWidget, QWidget#pages .QWidget,
    QWidget#adjust .QWidget {{ background: transparent; }}
    QLabel#timelineName {{ color: {TEXT_MAIN}; font-weight: 600; }}
    QFrame#timelinePanel {{ background: {PANEL_BG}; border: 1px solid {BORDER_STRONG};
        border-radius: {RADIUS}px; }}
    QFrame#timelinePanel QLabel {{ background: transparent; border: 0; }}
    QWidget#header QPushButton, QWidget#header QToolButton {{ padding: 0 8px;
        min-height: {HEADER_CONTROL - 2}px; max-height: {HEADER_CONTROL - 2}px; }}
    QWidget#header QToolButton#projectButton {{ padding: 0 28px 0 12px; }}
    QToolButton#projectButton::menu-indicator {{
        image: url("{_icon('chevron-down.svg')}");
        subcontrol-origin: padding; subcontrol-position: center right;
        width: 12px; height: 12px; right: 8px; }}
    QToolButton#projectButton::menu-indicator:hover {{ image: url("{_icon('chevron-down-hover.svg')}"); }}
    QWidget#header QPushButton[iconOnly="true"], QWidget#header QToolButton#settingsButton {{
        padding: 0; min-width: {HEADER_CONTROL - 2}px; max-width: {HEADER_CONTROL - 2}px;
        qproperty-iconSize: 16px; }}
    QWidget#reviewToolControls QPushButton[role="choice"] {{ padding: 0 4px; }}

    QDialog#chromeDialog {{ background: {BORDER_COLOUR}; }}
    QWidget#dialogBody, QWidget#settingsHost {{ background: {PANEL_BG}; }}
    QLabel[role="section"] {{ color: {ACCENT}; font-size: 12px; font-weight: 600; padding: 4px 0 2px 0; }}
    QTabWidget#settingsTabs::pane {{ border: 0; border-top: 1px solid {LINE}; }}
    QTabWidget#settingsTabs QTabBar {{ background: {BAR_BG}; }}
    QTabBar::tab {{ background: transparent; color: {TEXT_MUTED}; border: 0; border-bottom: 2px solid transparent;
        padding: 8px 16px; margin: 0; }}
    QTabBar::tab:hover:!selected {{ color: {TEXT_MAIN}; background: {CONTROL_BG};
        border-bottom: 2px solid {BORDER_STRONG}; }}
    QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}

    QAbstractSpinBox {{ background: {APP_BG}; color: {TEXT_MAIN}; border: 1px solid {BORDER_ROW};
        border-radius: {RADIUS}px; padding: 0 22px 0 8px; min-height: {CONTROL - 2}px; max-height: {CONTROL - 2}px;
        selection-background-color: {SELECTED_ROW}; }}
    QAbstractSpinBox:hover {{ border-color: {BORDER_STRONG}; }}
    QAbstractSpinBox:focus {{ border-color: {ACCENT}; }}
    QAbstractSpinBox:disabled {{ color: {TEXT_MUTED}; border-color: #1f3a46; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 20px;
        border: 0; background: transparent; }}
    QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
    QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
    QAbstractSpinBox::up-arrow {{ image: url("{_icon('chevron-up.svg')}"); width: 10px; height: 10px; }}
    QAbstractSpinBox::up-arrow:hover {{ image: url("{_icon('chevron-up-hover.svg')}"); }}
    QAbstractSpinBox::down-arrow {{ image: url("{_icon('chevron-down.svg')}"); width: 10px; height: 10px; }}
    QAbstractSpinBox::down-arrow:hover {{ image: url("{_icon('chevron-down-hover.svg')}"); }}
    QComboBox::drop-down {{ border: 0; width: 22px; }}
    QComboBox::down-arrow {{ image: url("{_icon('chevron-down.svg')}"); width: 10px; height: 10px; }}
    QComboBox QAbstractItemView {{ background: {APP_BG}; color: {TEXT_MAIN}; border: 1px solid {BORDER_STRONG};
        selection-background-color: {SELECTED_ROW}; outline: 0; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator, QTreeView::indicator {{ width: 16px; height: 16px; border: 1px solid {BORDER_STRONG}; border-radius: 3px;
        background: {APP_BG}; }}
    QCheckBox::indicator:hover, QTreeView::indicator:hover {{ border-color: {ACCENT}; }}
    QCheckBox::indicator:checked, QTreeView::indicator:checked {{ background: {PRIMARY_BG}; border-color: {PRIMARY_BG};
        image: url("{_icon('check.svg')}"); }}
    """


class MainWindow(TimelineReviewMixin, ReviewReportMixin, ReviewHistoryMixin, ReviewMultiSelectionMixin, LearningReviewMixin, LearningEvaluationMixin, LearningBatchMixin, ComparisonReviewMixin, SuggestionsReviewMixin, MarkerBudgetMixin, ReviewCameraMixin, ProjectReviewMixin, WindowChromeMixin, QMainWindow):
    def __init__(self, client=None):
        super().__init__()
        self.setWindowTitle("VISPA MP — markers")
        self.resize(1280, 800)
        self.client = client
        self.snapshot = None
        self.analysis = None
        self.proposals = []
        self._excluded_frames = set()
        self._page_layout = None
        self._drag_token = uuid.uuid4().hex
        self.rule_warnings = []
        self.pages = []
        self.open_pages = set()
        self.selected_page_id = None
        self.selected_frame = None
        self.selected_manual = False
        self._selected_keys = set()
        self._range_anchor_key = None
        self.playhead_frame = None
        self.last_seek = None
        self.worker = None
        self._comparison_windows = []
        self._stop_analysis = None
        self.mode = "strip"
        self.view_filter = "all"
        self._preview = None  # a suggestion shown in place of the selected image, not kept yet
        self._suggestions_open = False
        self._selected_suggestion_frames = set()
        self._suggestion_selection_context = None
        self.suggestions_auto_open = False
        self.suggestions_detached = False
        self.suggestions_window = None
        self._closing_suggestions = False
        self._flash = None  # the image just kept, framed in white for a moment
        self._thumb_zoom = None
        self._thumb_pan = None
        self._stored_settings, view = load_user()
        self._workspace_widths = [view.get("pages_panel_width", 280), view.get("review_tools_width", 280)]
        self._workspace_restored = False
        self.suggestions_rows = view.get("suggestions_rows", 0)
        names = [name for name, _width, _height in FORMATS]
        self.page_format = view["page_format"] if view["page_format"] in names else "A5"
        self.orientation = view["orientation"] if view["orientation"] in ("portrait", "landscape") else "portrait"
        self.custom_width = min(2000, max(10, int(view["custom_width"])))
        self.custom_height = min(2000, max(10, int(view["custom_height"])))
        self.show_board_labels = view.get("show_board_labels", True)
        self.preview_quality = view.get("preview_quality", "Medium")
        self.frame_format = view.get("frame_format", "Source")
        self.frame_custom_width = float(view.get("frame_custom_width", 16))
        self.frame_custom_height = float(view.get("frame_custom_height", 9))
        self._ready = False
        self._init_project_workflow(Message, SLIDER_SCALE)
        self._init_learning_workflow(Message)
        self._init_review_cameras(THUMB_W)
        self.widgets = {}
        self._rows = {}
        self._init_review_history()
        self._build()
        self._ready = True
        # Sliders fire on every step: the file is written once they settle.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self.save_settings)
        self._resolve_timer = QTimer(self)
        self._resolve_timer.setInterval(1000)
        self._resolve_timer.timeout.connect(self._sync_resolve)
        self._resolve_timer.start()
        self._load_selected_learning_profile()
        self._restore_suggestions_preferences(view)

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())
        layout.addWidget(separator())
        self.warnings = QLabel("")
        self.warnings.setWordWrap(True)
        self.warnings.setProperty("role", "muted")
        self.warnings.setContentsMargins(12, 4, 12, 4)
        self.warnings.hide()
        self.mode_switches = self._build_modes()
        self.selection_profile_panel = LearningProfilePanel(self, compact=True, sidebar=True)
        self.selection_profile_panel.manage.clicked.disconnect()
        self.selection_profile_panel.manage.setText("Profiles…")
        self.selection_profile_panel.manage.setToolTip("Choose and apply a selection profile in Settings.")
        self.selection_profile_panel.manage.clicked.connect(self._show_selection_profile_settings)
        self._build_marker_budget_review_summary().hide()
        self.workspace_splitter = WorkspaceSplitter()
        self.workspace_splitter.addWidget(self._build_pages())
        self.workspace_splitter.addWidget(self._build_center())
        self.workspace_splitter.addWidget(self._build_adjust())
        for index, stretch in enumerate((0, 1, 0)):
            self.workspace_splitter.setStretchFactor(index, stretch)
        self.workspace_splitter.resize_started.connect(self._begin_workspace_resize)
        self.workspace_splitter.resize_finished.connect(self._finish_workspace_resize)
        self.workspace_splitter.splitterMoved.connect(self._workspace_splitter_moved)
        self.workspace_splitter.installEventFilter(self)
        layout.addWidget(self.workspace_splitter, 1)
        layout.addWidget(separator())
        layout.addWidget(self._build_footer())
        self._build_settings()
        self._init_review_report()
        for key, slot in ((Qt.Key.Key_Left, partial(self._arrow, -1)),
                          (Qt.Key.Key_Right, partial(self._arrow, 1)),
                          (Qt.Key.Key_Return, self._keep_preview), (Qt.Key.Key_Enter, self._keep_preview),
                          (Qt.Key.Key_Escape, self._cancel_preview)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(slot)
        self.read_button.clicked.connect(self.read_timeline)
        self.analyze_button.clicked.connect(self.run_analysis)
        self.apply_button.clicked.connect(self.write_markers)
        self.setStyleSheet(_theme())
        self.settings_dialog.setStyleSheet(_theme())
        self.titlebar = TitleBar(self)
        self.titlebar.set_caption("VISPA MP")
        self.setMenuWidget(self.titlebar)
        self.setObjectName("mainWindow")
        self._sync_outline()
        self._sync_resolve()
        self._sync_size_fields()
        self._sync_preview_fields()
        self._refresh_target()
        self._update_global_marker_budget_summary()
        self.ruler.set_compact(False)

    def _build_header(self):
        """Project and actions, timeline name, then Learning, Resolve and Settings."""
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(HEADER_HEIGHT)
        grid = QGridLayout(header)
        grid.setContentsMargins(12, 0, 12, 0)
        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        left.addWidget(self._build_project_button())
        self.read_button = QPushButton()
        self.read_button.setIcon(QIcon(_icon("import.svg")))
        self.read_button.setAccessibleName("Read timeline")
        self.read_button.setToolTip("Read timeline — Import the current timeline from Resolve.")
        self.analyze_button = QPushButton()
        self._set_analysis_button_state()
        for button in (self.read_button, self.analyze_button):
            button.setProperty("iconOnly", True)
        self.apply_button = QPushButton("Place markers")
        self.apply_button.setProperty("primary", True)
        for button in (self.read_button, self.analyze_button, self.apply_button):
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            left.addWidget(button)
        self.timeline_label = ResolveSourceLabel()
        self.timeline_label.setObjectName("timelineName")
        self.timeline_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        right.addWidget(self._build_learning_button())
        right.addSpacing(12)
        self.resolve_dot = QLabel("●")
        self.resolve_dot.setProperty("role", "resolveDot")
        self.resolve_label = QLabel("Resolve not connected")
        right.addWidget(self.resolve_dot)
        right.addWidget(self.resolve_label)
        right.addSpacing(10)
        self.settings_button = QToolButton()
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setIcon(QIcon(_icon("gear.svg")))
        self.settings_button.setToolTip("Settings")
        self.settings_button.setAccessibleName("Settings")
        self.settings_button.clicked.connect(self._show_settings)
        right.addWidget(self.settings_button)
        grid.addLayout(left, 0, 0, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self.timeline_label, 0, 1)
        grid.addLayout(right, 0, 2, Qt.AlignmentFlag.AlignRight)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        return header

    def _restore_workspace_widths(self):
        splitter = self.workspace_splitter
        if self._workspace_restored or not splitter.isVisible():
            return
        available = splitter.width() - 2 * splitter.handleWidth()
        left = max(self.pages_panel.minimumWidth(), int(self._workspace_widths[0]))
        right = max(self.review_adjust.minimumWidth(), int(self._workspace_widths[1]))
        splitter.setSizes([left, max(self.review_center.minimumWidth(), available - left - right), right])
        self._workspace_restored = True

    def _begin_workspace_resize(self):
        self._remember_review_camera(self.mode)

    def _workspace_splitter_moved(self, *_args):
        if not self._workspace_restored:
            return
        sizes = self.workspace_splitter.sizes()
        self._workspace_widths = [sizes[0], sizes[2]]
        self._schedule_save()

    def _finish_workspace_resize(self):
        self._workspace_splitter_moved()
        self._queue_review_camera(self.mode)

    def _set_analysis_button_state(self, *, running=False):
        self.analyze_button.setIcon(QIcon(_icon("square.svg" if running else "sparkles.svg")))
        self.analyze_button.setAccessibleName("Cancel analysis" if running else "Analyze")
        self.analyze_button.setToolTip(
            "Cancel analysis — Stop the current analysis." if running else
            "Analyze — Analyze the timeline and propose markers.")

    def _build_modes(self):
        bar = QWidget()
        bar.setObjectName("modeBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 0, 8, 0)
        self.strip_button = QPushButton("Strip")
        self.board_button = QPushButton("Board")
        group = QButtonGroup(self)
        group.setExclusive(True)
        for button, mode in ((self.strip_button, "strip"), (self.board_button, "board")):
            button.setCheckable(True)
            button.setProperty("role", "mode")
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            button.clicked.connect(partial(self._set_mode, mode))
            group.addButton(button)
            row.addWidget(button)
        self.strip_button.setChecked(True)
        row.addStretch(1)
        return bar

    def _build_pages(self):
        self.pages_panel = PagesPanel(self)
        self.pages_panel.setMinimumWidth(180)
        column = QVBoxLayout(self.pages_panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        title = QLabel("Pages")
        title.setProperty("role", "panelTitle")
        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 8, 0)
        heading.setSpacing(4)
        heading.addWidget(title, 1)
        for name, action, icon in (("undo_button", self.undo_action, "undo.svg"),
                                    ("redo_button", self.redo_action, "redo.svg")):
            button = QToolButton()
            button.setProperty("role", "historyControl")
            button.setIcon(QIcon(_icon(icon)))
            button.clicked.connect(action.trigger)
            def sync_button(action=action, button=button):
                button.setEnabled(action.isEnabled())
                button.setToolTip(action.toolTip())
            action.changed.connect(sync_button)
            sync_button()
            button.setAccessibleName("Undo" if name == "undo_button" else "Redo")
            button.setFixedSize(28, 26)
            heading.addWidget(button)
            setattr(self, name, button)
        column.addLayout(heading)
        self.pages_scroll = QScrollArea()
        self.pages_scroll.setWidgetResizable(True)
        self.pages_scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self.pages_layout = QVBoxLayout(host)
        self.pages_layout.setContentsMargins(0, 4, 0, 8)
        self.pages_layout.setSpacing(0)
        self.pages_scroll.setWidget(host)
        column.addWidget(self.pages_scroll, 1)
        return self.pages_panel

    def _build_center(self):
        center = QWidget()
        self.review_center = center
        center.setMinimumWidth(320)
        center.setObjectName("center")
        column = QVBoxLayout(center)
        column.setContentsMargins(12, 8, 12, 8)
        column.setSpacing(8)
        self.timeline_panel = QFrame()
        self.timeline_panel.setObjectName("timelinePanel")
        timeline = QVBoxLayout(self.timeline_panel)
        timeline.setContentsMargins(10, 6, 10, 6)
        timeline.setSpacing(2)
        video = QLabel("Timeline")
        video.setProperty("role", "muted")
        timeline.addWidget(video)
        self.ruler = Ruler()
        self.ruler.moved.connect(self._on_ruler)
        self.ruler.chosen.connect(lambda frame: self._choose_frame(frame, False))
        self.ruler.context_requested.connect(self._show_timeline_menu)
        timeline.addWidget(self.ruler)
        column.addWidget(self.timeline_panel)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_strip())
        self.stack.addWidget(self._build_board())
        self.stack.setMinimumHeight(120)
        self.review_splitter = ReviewSplitter()
        self.review_splitter.addWidget(self.stack)
        # Shared by Strip and Board, opened on demand or following selection.
        self.suggestion_panel = QWidget()
        self.suggestion_panel.setMinimumHeight(120)
        suggestions = QVBoxLayout(self.suggestion_panel)
        suggestions.setContentsMargins(0, 0, 0, 0)
        suggestions.setSpacing(4)
        self.suggestions_header = self._build_suggestions_header()
        suggestions.addWidget(self.suggestions_header)
        self.suggestion_area, self.suggestion_layout = self._horizontal_strip()
        self.suggestion_area.hide()
        suggestions.addWidget(self.suggestion_area, 1)
        self.review_splitter.addWidget(self.suggestion_panel)
        self.review_splitter.setStretchFactor(0, 1)
        self.review_splitter.setStretchFactor(1, 0)
        self._suggestion_height = 200
        self.review_splitter.splitterMoved.connect(self._suggestions_splitter_moved)
        self.suggestion_area.viewport_resized.connect(self._resize_suggestions)
        self.suggestion_panel.hide()
        column.addWidget(self.review_splitter, 1)
        return center

    def _build_strip(self):
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        # The cards form a fixed board. Zoom changes its view, never its rows.
        self.thumb_area = StripCanvasView()
        self.strip_panel_counter = PanelCounter(self.thumb_area.viewport())
        self.strip_panel_counter.setProperty("canvasOverlay", True)
        self.strip_panel_counter.move(10, 10)
        self.thumb_area.installEventFilter(self)
        self.thumb_area.setFrameShape(QFrame.Shape.NoFrame)
        self.thumb_area.setToolTip(ZOOM_HINT)
        host = QWidget()
        # A graphics proxy owns its widget outside the window's QWidget tree.
        host.setStyleSheet(_theme())
        self.thumb_layout = QGridLayout(host)
        self.thumb_layout.setContentsMargins(0, 0, 0, 0)
        self.thumb_layout.setSpacing(8)
        self.thumb_layout.setSizeConstraint(QGridLayout.SizeConstraint.SetMinimumSize)
        self.thumb_area.setWidget(host)
        self.thumb_area.viewport().installEventFilter(self)
        self._thumb_items = None
        self._thumb_fit = None
        self._thumb_columns = None
        self._thumb_grid_context = None
        column.addWidget(self.thumb_area, 1)
        return page

    def _horizontal_strip(self):
        area = SuggestionArea()
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidgetResizable(True)
        area.setMinimumHeight(72)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        row = QGridLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        row.setSizeConstraint(QGridLayout.SizeConstraint.SetMinimumSize)
        area.setWidget(host)
        return area, row

    def _build_board(self):
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        self.board_scroll = QScrollArea()
        self.board_scroll.setWidgetResizable(True)
        self.board_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.board = PageBoard()
        self.board_panel_counter = PanelCounter(self.board)
        self.board_panel_counter.move(10, 10)
        self.board.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.board.installEventFilter(self)
        self.board.view_interaction.connect(lambda: self._prepare_camera_interaction("board"))
        self.board.view_changed.connect(lambda: self._remember_review_camera("board", dirty=True))
        self.board.chosen.connect(self._choose_frame)
        self.board.additive_chosen.connect(self._toggle_frame_selection)
        self.board.range_chosen.connect(self._select_frame_range)
        self.board.opened.connect(self._open_suggestions)
        self.board.context_requested.connect(self._show_marker_menu)
        self.board.drag_requested.connect(self._begin_marker_drag)
        self.board_scroll.setWidget(self.board)
        column.addWidget(self.board_scroll, 1)
        self.caption = QLabel("")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setProperty("role", "muted")
        self.caption.setWordWrap(True)
        return page

    def _build_format_bar(self):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self._muted("Format"))
        self.format_group = QButtonGroup(self)
        self.format_group.setExclusive(True)
        self.format_buttons = {}
        for name, _width, _height in FORMATS:
            button = QPushButton(name)
            button.setCheckable(True)
            button.setProperty("role", "choice")
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            button.clicked.connect(partial(self._choose_format, name))
            self.format_group.addButton(button)
            self.format_buttons[name] = button
            row.addWidget(button)
        self.format_buttons[self.page_format].setChecked(True)
        row.addSpacing(8)
        row.addWidget(self._muted("Frame format"))
        self.frame_format_box = QComboBox()
        self.frame_format_box.setObjectName("frameFormat")
        self.frame_format_box.addItems(FRAME_FORMATS)
        self.frame_format_box.setToolTip("Preview crop only. Source keeps the whole image; other formats crop its centre.")
        self.frame_format_box.currentIndexChanged.connect(self._preview_preferences_changed)
        row.addWidget(self.frame_format_box)
        self.frame_dimensions = QWidget()
        dimensions = QHBoxLayout(self.frame_dimensions)
        dimensions.setContentsMargins(0, 0, 0, 0)
        dimensions.setSpacing(4)
        self.frame_width_box, self.frame_height_box = QDoubleSpinBox(), QDoubleSpinBox()
        for box in (self.frame_width_box, self.frame_height_box):
            box.setRange(0.1, 100)
            box.setDecimals(2)
            box.setSingleStep(0.1)
            box.setFixedWidth(84)
            box.valueChanged.connect(self._preview_preferences_changed)
        self.frame_width_box.setToolTip("Frame width ratio")
        self.frame_height_box.setToolTip("Frame height ratio")
        dimensions.addWidget(self.frame_width_box)
        dimensions.addWidget(self._muted(":"))
        dimensions.addWidget(self.frame_height_box)
        row.addWidget(self.frame_dimensions)
        self.board_labels_check = QCheckBox("Labels")
        self.board_labels_check.setToolTip("Show role labels on Board images. Coloured borders always remain.")
        self.board_labels_check.toggled.connect(self._preview_preferences_changed)
        row.addWidget(self.board_labels_check)
        row.addSpacing(8)
        row.addWidget(self._muted("Orientation"))
        self.orientation_group = QButtonGroup(self)
        self.orientation_group.setExclusive(True)
        self.orientation_buttons = {}
        for name, label in (("portrait", "Portrait"), ("landscape", "Landscape")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("role", "choice")
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            button.clicked.connect(partial(self._choose_orientation, name))
            self.orientation_group.addButton(button)
            self.orientation_buttons[name] = button
            row.addWidget(button)
        self.orientation_buttons[self.orientation].setChecked(True)
        row.addSpacing(8)
        row.addWidget(self._muted("Width"))
        self.width_box = QSpinBox()
        self.width_box.setRange(10, 2000)
        self.width_box.setSuffix(" mm")
        row.addWidget(self.width_box)
        row.addWidget(self._muted("Height"))
        self.height_box = QSpinBox()
        self.height_box.setRange(10, 2000)
        self.height_box.setSuffix(" mm")
        row.addWidget(self.height_box)
        self.width_box.valueChanged.connect(self._custom_size_edited)
        self.height_box.valueChanged.connect(self._custom_size_edited)
        row.addStretch(1)
        row.setSizeConstraint(QHBoxLayout.SizeConstraint.SetMinimumSize)
        scroll = QScrollArea()
        scroll.setObjectName("formatBar")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        scroll.setFixedHeight(52)
        scroll.setWidget(bar)
        return scroll

    def _build_view_tools(self):
        tools = QWidget()
        tools.setObjectName("reviewToolControls")
        self.review_tool_controls = tools
        column = QVBoxLayout(tools)
        column.setContentsMargins(12, 4, 12, 8)
        column.setSpacing(8)
        column.addWidget(self.mode_switches)
        column.addWidget(self._muted("Show"))
        filters = QHBoxLayout()
        filters.setSpacing(4)
        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self.filter_buttons = {}
        for key, label in FILTERS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("role", "choice")
            button.clicked.connect(partial(self._set_filter, key))
            self.filter_group.addButton(button)
            self.filter_buttons[key] = button
            filters.addWidget(button, 1)
        self.filter_buttons["all"].setChecked(True)
        column.addLayout(filters)
        quality = QHBoxLayout()
        quality.addWidget(self._muted("Preview quality"), 1)
        self.preview_quality_box = QComboBox()
        self.preview_quality_box.setObjectName("previewQuality")
        self.preview_quality_box.addItems(PREVIEW_QUALITIES)
        self.preview_quality_box.setCurrentText(self.preview_quality)
        self.preview_quality_box.setFixedWidth(100)
        self.preview_quality_box.setToolTip("Shared display quality for Strip, Board and Suggestions.")
        self.preview_quality_box.currentTextChanged.connect(self._set_preview_quality)
        quality.addWidget(self.preview_quality_box)
        column.addLayout(quality)
        self.suggestions_button = QPushButton("Suggestions")
        self.suggestions_button.setCheckable(True)
        self.suggestions_button.setProperty("role", "choice")
        self.suggestions_button.setToolTip("Show or hide suggestions. Double-click an image to open them.")
        self.suggestions_button.toggled.connect(self._toggle_suggestions)
        column.addWidget(self.suggestions_button)
        column.addWidget(separator())
        column.addWidget(self._build_sidebar_format())
        column.addWidget(self.caption)
        self.manual_order_bar = QWidget()
        self.manual_order_bar.setToolTip("Preview only; Resolve keeps timeline order.")
        order = QVBoxLayout(self.manual_order_bar)
        order.setContentsMargins(0, 0, 0, 0)
        order.setSpacing(4)
        order.addWidget(self._muted("Manual page order"))
        self.automatic_order_button = QPushButton("Automatic pages")
        self.automatic_order_button.setToolTip("Return to automatic page grouping. Source timecodes stay unchanged.")
        self.automatic_order_button.clicked.connect(self._reset_page_layout)
        order.addWidget(self.automatic_order_button)
        self.manual_order_bar.hide()
        column.addWidget(self.manual_order_bar)
        column.addWidget(self._build_report_button())
        column.addStretch(1)
        return tools

    def _build_sidebar_format(self):
        # Keep the established controls/signals, arranged for a narrow sidebar.
        previous = self._build_format_bar()
        previous_bar = previous.takeWidget()
        panel = QWidget()
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(self._muted("Page format"))
        formats = QHBoxLayout()
        formats.setSpacing(4)
        for button in self.format_buttons.values():
            formats.addWidget(button, 1)
        column.addLayout(formats)
        orientation = QHBoxLayout()
        orientation.setSpacing(4)
        for button in self.orientation_buttons.values():
            orientation.addWidget(button, 1)
        column.addLayout(orientation)
        dimensions = QFormLayout()
        dimensions.setContentsMargins(0, 0, 0, 0)
        dimensions.setSpacing(6)
        dimensions.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        dimensions.addRow("Width", self.width_box)
        dimensions.addRow("Height", self.height_box)
        dimensions.addRow("Frame format", self.frame_format_box)
        column.addLayout(dimensions)
        column.addWidget(self.frame_dimensions)
        column.addWidget(self.board_labels_check)
        previous_bar.deleteLater()
        previous.deleteLater()
        return panel

    def _build_adjust(self):
        panel = QWidget()
        self.review_adjust = panel
        panel.setObjectName("adjust")
        panel.setMinimumWidth(240)
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 8)
        column.setSpacing(0)
        title = QLabel("Review tools")
        title.setProperty("role", "panelTitle")
        column.addWidget(title)
        column.addWidget(self.selection_profile_panel)
        self.review_tools_scroll = QScrollArea()
        self.review_tools_scroll.setWidgetResizable(True)
        self.review_tools_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.review_tools_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.review_tools_scroll.setMinimumHeight(80)
        self.review_tools_scroll.setWidget(self._build_view_tools())
        column.addWidget(self.review_tools_scroll, 1)
        title = QLabel("Adjust")
        title.setProperty("role", "panelTitle")
        column.addWidget(title)
        values = self._stored_settings
        form = QWidget()
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(12, 6, 12, 0)
        form_layout.setSpacing(6)
        self.sharpness_value = QLabel()
        sharpness = self._labeled_slider("sharpness_floor", "Sharpness", 0, 1000, values, self.sharpness_value)
        form_layout.addWidget(sharpness)
        self.mouth_value = QLabel()
        mouth = self._labeled_slider("mouth_min", "Open mouth", 0, 100, values, self.mouth_value)
        form_layout.addWidget(mouth)
        self.recalculate_button = QPushButton("Recalculate")
        self.recalculate_button.setObjectName("recalculate")
        self.recalculate_button.clicked.connect(self.recompute)
        form_layout.addWidget(self.recalculate_button)
        color_title = QLabel("Image role")
        color_title.setProperty("role", "muted")
        role_header = QHBoxLayout()
        role_header.addWidget(color_title)
        self.selection_count = QLabel("No image selected")
        self.selection_count.setProperty("role", "muted")
        self.selection_count.setWordWrap(True)
        self.selection_count.setToolTip("Ctrl+click: add or remove images. Shift+click: select a chronological range. "
                                       "Ctrl+Shift+click: add a range. Delete: remove selected proposals.")
        self.selection_count.setAlignment(Qt.AlignmentFlag.AlignRight)
        role_header.addWidget(self.selection_count, 1)
        form_layout.addLayout(role_header)
        swatches = QHBoxLayout()
        self.color_buttons = {}
        for color, label in COLOR_LABEL.items():
            box = QVBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(2)
            button = QPushButton("")
            button.setObjectName(f"color-{color}")
            button.setProperty("role", "swatch")
            button.setProperty("compact", True)
            button.setToolTip(label)
            button.clicked.connect(partial(self._set_marker_color, color))
            caption = QLabel(label)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setProperty("role", "muted")
            box.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
            box.addWidget(caption)
            swatches.addLayout(box)
            self.color_buttons[color] = button
        form_layout.addLayout(swatches)
        form.setToolTip("Hand-placed Resolve markers stay unchanged.")
        column.addWidget(form)
        self._show_slider_value("sharpness_floor", self.sharpness_value)
        self._show_slider_value("mouth_min", self.mouth_value)
        return panel

    def _labeled_slider(self, key, label, low, high, values, value_label):
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        header = QHBoxLayout()
        header.addWidget(QLabel(label))
        header.addStretch(1)
        value_label.setProperty("role", "mono")
        header.addWidget(value_label)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setValue(int(round(float(values[key]) * SLIDER_SCALE[key])))
        slider.valueChanged.connect(self._changed)
        slider.valueChanged.connect(partial(self._show_slider_value, key, value_label))
        tip = ("Minimum measured sharpness of candidate images. Raising it rejects softer frames; "
               "it does not sharpen the preview." if key == "sharpness_floor" else
               "Minimum visual open-mouth score. Open must also score higher than closed. "
               "Raising this threshold admits fewer images; it does not increase mouth priority. "
               "If none qualify, the configured fallback may keep a mouth-unverified image.")
        slider.setToolTip(tip)
        row.setToolTip(tip)
        self.widgets[key] = slider
        layout.addLayout(header)
        layout.addWidget(slider)
        return row

    def _build_footer(self):
        footer = QWidget()
        footer.setObjectName("footer")
        footer.setFixedHeight(36)
        row = QHBoxLayout(footer)
        row.setContentsMargins(12, 0, 12, 0)
        self.progress = StepProgress()
        row.addWidget(self.progress)
        self.playhead_label = QLabel("")
        self.playhead_label.setObjectName("playhead")
        row.addWidget(self.playhead_label)
        row.addStretch(1)
        self.status = QLabel("Open Resolve, then read the timeline.")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.status, 1)
        row.addStretch(1)
        self.tracks_label = QLabel("Video 1 · Audio 1")
        self.tracks_label.setProperty("role", "muted")
        row.addWidget(self.tracks_label)
        return footer

    def _build_settings(self):
        self.settings_dialog = ChromeDialog(self, "Settings")
        self.settings_dialog.resize(500, 600)
        outer = QVBoxLayout(self.settings_dialog.body)
        outer.setContentsMargins(0, 0, 0, 16)
        outer.setSpacing(0)
        values = self._stored_settings
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setObjectName("settingsTabs")
        self.settings_tabs.setDocumentMode(True)
        self.settings_tabs.tabBar().setDrawBase(False)
        for title, sections in SETTINGS_TABS:
            self.settings_tabs.addTab(self._settings_page(sections, values), title)
        self.widgets["split_long_shots"].toggled.connect(self.widgets["long_shot_seconds"].setEnabled)
        self.widgets["long_shot_seconds"].setEnabled(self.widgets["split_long_shots"].isChecked())
        self.settings_profile_panel = LearningProfilePanel(self)
        self.settings_tabs.addTab(self.settings_profile_panel, "Profiles")
        outer.addWidget(self.settings_tabs, 1)
        outer.addSpacing(16)
        outer.addWidget(separator())
        outer.addSpacing(14)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(16, 0, 16, 0)
        buttons.setSpacing(8)
        self.save_preset_button = QPushButton("Save…")
        self.save_preset_button.setToolTip("Save these settings to a file, to load them in another project.")
        self.load_preset_button = QPushButton("Load…")
        self.load_preset_button.setToolTip("Load settings saved earlier. The page format stays.")
        self.save_preset_button.clicked.connect(self._save_preset)
        self.load_preset_button.clicked.connect(self._load_preset)
        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Back to the shipped settings. The page format stays.")
        self.download_button = QPushButton("Download models")
        self.reset_button.clicked.connect(self.reset_settings)
        self.download_button.clicked.connect(self.download_models)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.save_preset_button)
        buttons.addWidget(self.load_preset_button)
        buttons.addStretch(1)
        buttons.addWidget(self.download_button)
        self.settings_preset_controls = QWidget()
        self.settings_preset_controls.setLayout(buttons)
        outer.addWidget(self.settings_preset_controls)
        self.settings_tabs.currentChanged.connect(
            lambda _index: self.settings_preset_controls.setVisible(
                self.settings_tabs.currentWidget() is not self.settings_profile_panel))

    def _settings_page(self, sections, values):
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The bar paints the viewport's colour behind itself: the same as the page, so it disappears.
        scroll.viewport().setStyleSheet(f"background: {PANEL_BG};")
        host = QWidget()
        host.setObjectName("settingsHost")
        column = QVBoxLayout(host)
        column.setContentsMargins(20, 12, 16, 8)
        column.setSpacing(0)
        # One form per tab, so every field of the tab lines up on the same edge.
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        for index, (title, keys) in enumerate(sections):
            if title:
                heading = QLabel(title)
                heading.setProperty("role", "section")
                if index:
                    heading.setContentsMargins(0, 12, 0, 0)
                form.addRow(heading)
            for key in keys:
                self._settings_row(form, key, values)
            if "split_long_shots" in keys:
                note = self._muted("Only sustained visual changes create parts; static shots stay whole. "
                                   "Run Analyze again after changing these settings. "
                                   "Recalculate alone cannot find new parts.")
                note.setWordWrap(True)
                note.setObjectName("longShotAnalysisNote")
                form.addRow(note)
        column.addLayout(form)
        column.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _settings_row(self, form, key, values):
        if key == "_dialogue_status":
            from vispa_mp.dialogue import dialogue_summary
            self.dialogue_status_note = self._muted(dialogue_summary(self.analysis))
            self.dialogue_status_note.setWordWrap(True)
            self.dialogue_status_note.setObjectName("dialogueStatusNote")
            form.addRow(self.dialogue_status_note)
            return
        if key == "_global_marker_budget":
            self._build_marker_budget_settings(form, values)
            return
        if key == "compression":
            story = QWidget()
            story_layout = QVBoxLayout(story)
            story_layout.setContentsMargins(0, 0, 0, 0)
            story_layout.setSpacing(2)
            self.compression = QSlider(Qt.Orientation.Horizontal)
            self.compression.setRange(0, 100)
            self.compression.setMinimumWidth(200)
            self.compression.setToolTip("Compression moves the whole global marker band, not a per-minute quota. "
                                       "50% is the reference density; 0% doubles its volume and 100% halves it. "
                                       "It also guides the page count within your page limits.")
            self.compression.setValue(int(round(float(values["compression"]) * 100)))
            self.compression.valueChanged.connect(self._marker_budget_compression_changed)
            self.widgets["compression"] = self.compression
            ends = QHBoxLayout()
            ends.addWidget(self._muted("Low"))
            ends.addStretch(1)
            ends.addWidget(self._muted("High"))
            self.compression_percent = QLabel(f"{self.compression.value()}%")
            self.compression_percent.setProperty("role", "mono")
            self.compression.valueChanged.connect(lambda value: self.compression_percent.setText(f"{value}%"))
            self.page_target = QLabel("")
            self.page_target.setProperty("role", "muted")
            self.page_target.setWordWrap(True)
            story_layout.addWidget(self.compression)
            story_layout.addLayout(ends)
            story_layout.addWidget(self.compression_percent)
            story_layout.addWidget(self.page_target)
            form.addRow("Story compression", story)
            return
        if key == "mouth_fallback":
            mouth = QComboBox()
            mouth.addItem("Take the sharpest image", "sharp")
            mouth.addItem("Propose no image", "none")
            mouth.setCurrentIndex(max(0, mouth.findData(values["mouth_fallback"])))
            mouth.currentIndexChanged.connect(self._changed)
            mouth.setFixedWidth(190)
            self.widgets["mouth_fallback"] = mouth
            form.addRow("When no mouth is visible", mouth)
            return
        if key in CHECKS:
            box = QCheckBox(CHECKS[key])
            box.setChecked(bool(values[key]))
            if key in TIPS:
                box.setToolTip(TIPS[key])
            box.toggled.connect(self._changed)
            self.widgets[key] = box
            form.addRow(box)
            return
        label, low, high, step = SPIN_OF[key]
        if key in INTEGERS:
            widget = QSpinBox()
            widget.setRange(int(low), int(high))
            widget.setSingleStep(int(step))
            widget.setValue(int(values[key]))
        else:
            widget = QDoubleSpinBox()
            widget.setRange(float(low), float(high))
            widget.setSingleStep(float(step))
            widget.setDecimals(2)
            widget.setValue(float(values[key]))
        widget.setFixedWidth(110)
        if key == "core_page_target":
            widget.setSpecialValueText("Off")
        widget.valueChanged.connect(self._changed)
        self.widgets[key] = widget
        caption = QLabel(label)
        if key in TIPS:
            caption.setToolTip(TIPS[key])
            widget.setToolTip(TIPS[key])
        form.addRow(caption, widget)

    def _muted(self, text):
        label = QLabel(text)
        label.setProperty("role", "muted")
        return label

    def _schedule_save(self):
        if self._ready and hasattr(self, "_save_timer"):
            self._save_timer.start()

    def save_settings(self):
        """Only what differs from presets/default.json goes to presets/user.json."""
        self._save_timer.stop()
        view = {
            "page_format": self.page_format, "orientation": self.orientation,
            "custom_width": int(self.custom_width), "custom_height": int(self.custom_height),
            "show_board_labels": self.show_board_labels, "frame_format": self.frame_format,
            "frame_custom_width": self.frame_custom_width, "frame_custom_height": self.frame_custom_height,
            "preview_quality": self.preview_quality,
            "suggestions_auto_open": self.suggestions_auto_open, "suggestions_detached": self.suggestions_detached,
            "suggestions_rows": self.suggestions_rows,
            "pages_panel_width": self._workspace_widths[0],
            "review_tools_width": self._workspace_widths[1],
        }
        try:
            save_user(self.settings(), view)
        except OSError as error:
            self.status.setText(f"Settings were not saved: {error}")

    def _changed(self, *_args):
        if self._ready:
            self._refresh_marker_budget_settings()
        self._schedule_save()
        if getattr(self, "page_target", None) is not None:
            self._refresh_target()
        self._show_slider_value("sharpness_floor", getattr(self, "sharpness_value", None))
        self._show_slider_value("mouth_min", getattr(self, "mouth_value", None))
        if self._ready and self.analysis is not None and self.worker is None:
            self.recompute()

    def _show_slider_value(self, key, label, *_args):
        if label is None or key not in self.widgets:
            return
        label.setText(f"{self.widgets[key].value() / SLIDER_SCALE[key]:.2f}")

    def settings(self):
        data = dict(self._stored_settings)
        for key, widget in self.widgets.items():
            if isinstance(widget, QCheckBox):
                data[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                data[key] = widget.currentData()
            elif isinstance(widget, QSlider):
                data[key] = widget.value() / SLIDER_SCALE.get(key, 100)
            else:
                data[key] = widget.value()
        return data

    def set_setting(self, key, value):
        widget = self.widgets[key]
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QComboBox):
            widget.setCurrentIndex(max(0, widget.findData(value)))
        elif isinstance(widget, QSlider):
            widget.setValue(int(round(float(value) * SLIDER_SCALE.get(key, 100))))
        else:
            widget.setValue(value)

    def save_settings_file(self, path):
        export_settings(self.settings(), path)
        self.status.setText(f"Settings saved: {Path(path).name}")

    def load_settings_file(self, path):
        """Apply a saved settings file, as if each value had been set by hand."""
        values = import_settings(path)
        if values.get("learning_profile"):
            from vispa_mp.learning_model import load_profile
            load_profile(values["learning_profile"])
        self._ready = False
        self._stored_settings = {**self._stored_settings, **values}
        for key, value in values.items():
            if key in self.widgets:
                self.set_setting(key, value)
        if "learning_profile" in values:
            self._load_selected_learning_profile()
        self._ready = True
        self.save_settings()
        self._refresh_target()
        self.recompute()
        self.status.setText(f"Settings loaded: {Path(path).name}")

    def _save_preset(self):
        SAVED_DIR.mkdir(parents=True, exist_ok=True)
        path, _kind = QFileDialog.getSaveFileName(
            self.settings_dialog, "Save settings", str(SAVED_DIR / "settings.json"), "VISPA MP settings (*.json)")
        if path:
            try:
                self.save_settings_file(path)
            except OSError as error:
                Message.tell(self.settings_dialog, "Settings", "The settings were not saved.", str(error))

    def _load_preset(self):
        SAVED_DIR.mkdir(parents=True, exist_ok=True)
        path, _kind = QFileDialog.getOpenFileName(
            self.settings_dialog, "Load settings", str(SAVED_DIR), "VISPA MP settings (*.json)")
        if path:
            try:
                self.load_settings_file(path)
            except ValueError as error:
                Message.tell(self.settings_dialog, "Settings", "These settings cannot be loaded.", str(error))

    def reset_settings(self):
        """Back to presets/default.json. The page format is a view choice and stays."""
        self._ready = False
        shipped = load()
        self._stored_settings = dict(shipped)
        for key, value in shipped.items():
            if key in self.widgets:
                self.set_setting(key, value)
        self._restore_learning_profile(None)
        self._ready = True
        self.save_settings()
        self._refresh_target()
        self.recompute()

    def show_analysis(self, analysis):
        self._clear_review_history()
        self.set_review_cameras(None)
        self.analysis = analysis
        self.proposals = []
        self._excluded_frames.clear()
        self._page_layout = None
        self._preview = None
        self._suggestions_open = False
        self.selected_frame = None
        self.selected_page_id = None
        self._selected_keys.clear()
        self._range_anchor_key = None
        self.open_pages = set()
        self.recompute()
        self._sync_selection_profile_panels()

    def recompute(self):
        previous = self.proposals
        if not self.analysis:
            self.proposals = []
            self.rule_warnings = []
            self._fill()
            return
        viewed = self._budget_analysis()
        if viewed.get("speech_tracks"):
            viewed["utterances"] = refresh_utterances(viewed, self.settings())
        if self._learning_profile is not None:
            result = propose(viewed, self.settings(), profile=self._learning_profile)
        else:
            result = propose(viewed, self.settings())
        # User additions belong to this review and survive threshold changes.
        # If a rule now chooses the same image, keep the user's chosen role.
        added = {int(item["frame"]): dict(item) for item in self.proposals
                 if item.get("rule") == "user" or item.get("user_role")}
        combined = {int(item["frame"]): item for item in result["proposals"]}
        combined.update(added)
        self.proposals = [combined[frame] for frame in sorted(combined) if frame not in self._excluded_frames]
        self.rule_warnings = result["warnings"]
        self._fill()
        if self.proposals != previous:
            self._clear_review_history()
        self._mark_project_dirty()

    def _budget_analysis(self):
        """Supply current duration and protected review choices without changing analysis."""
        if self.analysis is None:
            return None
        viewed = dict(self.analysis)
        snapshot = self.snapshot or {}
        identity = normalize_identity(viewed.get("timeline_identity"))
        if identity is not None and identity == normalize_identity(snapshot.get("timeline_identity")):
            start, end = snapshot.get("start_frame"), snapshot.get("end_frame")
            if type(start) is int and type(end) is int and end >= start:
                viewed["timeline_range"] = [start, end]
            if "markers" in snapshot:
                viewed["_budget_manual_frames"] = [int(marker["frame"]) for marker in snapshot.get("markers") or []
                                                   if not marker.get("automatic")
                                                   and marker.get("color") in (PAGE, CORE, EXTRA)]
        viewed.setdefault("_budget_manual_frames", list(viewed.get("manual_frames") or []))
        viewed["_budget_user_proposals"] = [dict(item) for item in self.proposals
                                           if item.get("rule") == "user" or item.get("user_role")]
        viewed["_budget_excluded_frames"] = sorted(self._excluded_frames)
        return viewed

    def timecode_of(self, frame):
        base = self._timebase()
        if not base:
            return str(frame)
        return format_timecode(int(frame), base)

    def _timebase(self):
        if self.analysis and self.analysis.get("timebase"):
            base = dict(self.analysis["timebase"])
            # An analysis saved before interlacing was read takes the rate from the timeline just read.
            if not base.get("timecode_fps") and self.snapshot and self.snapshot.get("timecode_fps"):
                if float(self.snapshot.get("fps") or 0) == float(base.get("fps") or 0):
                    base["timecode_fps"] = self.snapshot["timecode_fps"]
            return base
        if not self.snapshot:
            return None
        return {
            "fps": self.snapshot.get("fps") or 24,
            "timecode_fps": self.snapshot.get("timecode_fps"),
            "start_frame": self.snapshot.get("start_frame") or 0,
            "start_timecode": self.snapshot.get("start_timecode") or "00:00:00:00",
            "drop": bool(self.snapshot.get("drop")),
        }

    def _fill(self):
        if hasattr(self, "dialogue_status_note"):
            from vispa_mp.dialogue import dialogue_summary
            self.dialogue_status_note.setText(dialogue_summary(self.analysis))
        previous_primary = (self.selected_frame, bool(self.selected_manual))
        manuals = list((self.analysis or {}).get("manual_frames") or [])
        self.pages = group_pages(self.proposals, manuals,
                                 include_leading_extras=bool(core_target(self.settings())
                                                            or self.settings().get("global_markers_enabled")))
        self._page_layout = reconcile_layout(self._page_layout, self.proposals)
        if self._page_layout is not None:
            self.pages = self._manual_pages(self.pages)
        self.manual_order_bar.setVisible(self._page_layout is not None)
        known = {page["id"] for page in self.pages}
        self.open_pages &= known
        found = self._find(self.selected_frame, self.selected_manual) if self.selected_frame is not None else None
        if found:
            self.selected_page_id, self.selected_frame, self.selected_manual = found
        elif self.pages:
            item = self.pages[0]["items"][0]
            self.selected_page_id = self.pages[0]["id"]
            self.selected_manual = item["manual"]
            self.selected_frame = item_frame(item)
            self._move_playhead(self.selected_frame)
        else:
            self.selected_page_id = None
            self.selected_frame = None
            self.selected_manual = False
        self._reconcile_frame_selection(previous_primary)
        self._rebuild_tree()
        if self.suggestions_auto_open:
            self._suggestions_open = len(self._selected_keys) == 1 and not self.selected_manual
        self._refresh_center()
        self._refresh_target()
        self._update_global_marker_budget_summary()
        self._show_warnings()
        self._sync_header()
        self._sync_swatches()

    def _manual_pages(self, chronological):
        proposals = {int(item["frame"]): item for item in self.proposals}
        pages, membership = [], {}
        for group in self._page_layout:
            page = {"id": group["id"], "number": len(pages) + 1,
                    "items": [{"manual": False, "proposal": proposals[frame]} for frame in group["frames"]]}
            pages.append(page)
            for frame in group["frames"]:
                membership[frame] = page
        # Hand-placed Resolve markers stay visible, read-only, near their source
        # neighbours; they are never part of the editable reading-order list.
        if not pages:
            return chronological
        ordered = sorted(membership)
        for automatic in chronological:
            for item in automatic["items"]:
                if item["manual"]:
                    preceding = [frame for frame in ordered if frame <= item["frame"]]
                    anchor = preceding[-1] if preceding else ordered[0]
                    membership[anchor]["items"].append(item)
        return pages

    def _move_marker_to_page(self, frame, page_id, before_frame=None):
        return self._move_markers_to_page([frame], page_id, before_frame)

    @review_edit("Move images")
    def _move_markers_to_page(self, frames, page_id, before_frame=None):
        if self.worker is not None or self._learning_job_busy or self.analysis is None:
            return False
        previous = self._page_layout if self._page_layout is not None else capture_layout(self.pages)
        try:
            frames = list(frames)
            changed = move_frames(previous, frames, page_id, before_frame)
        except (TypeError, ValueError):
            return False
        if changed == previous:
            return False
        self._page_layout = changed
        numbers = set(frames)
        primary = self.selected_frame if self.selected_frame in numbers else frames[0]
        self.selected_frame, self.selected_manual = primary, False
        self._selected_keys = {(frame, False) for frame in frames}
        self._preview = None
        self._fill()
        self._move_playhead(primary)
        self._ensure_page_visible(self.selected_page_id)
        self._mark_project_dirty()
        self.status.setText(f"{len(frames)} image(s) moved in the page review. Source timecodes and Resolve marker positions stay unchanged.")
        return True

    @review_edit("Restore automatic order")
    def _reset_page_layout(self):
        if self.worker is None and not self._learning_job_busy and self._page_layout is not None:
            self._page_layout = None
            self._fill()
            self._mark_project_dirty()

    def _find(self, frame, manual):
        if frame is None:
            return None
        for page in self.pages:
            for item in page["items"]:
                if item["manual"] == manual and item_frame(item) == int(frame):
                    return page["id"], int(frame), manual
        return None

    def _page(self, page_id):
        for page in self.pages:
            if page["id"] == page_id:
                return page
        return None

    def _proposal(self, frame):
        for proposal in self.proposals:
            if int(proposal["frame"]) == int(frame):
                return proposal
        return None

    def _rebuild_tree(self):
        self._rows = {}
        self._clear_layout(self.pages_layout)
        warnings = self._warning_lines()
        for page in self.pages:
            row, children, arrow = self._make_page(page, warnings)
            self.pages_layout.addWidget(row)
            self.pages_layout.addWidget(children)
            opened = page["id"] in self.open_pages
            children.setVisible(opened)
            arrow.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
            self._rows[page["id"]] = {"row": row, "children": children, "arrow": arrow}
        self.pages_layout.addStretch(1)
        self._paint_selection()

    def _make_page(self, page, warnings):
        row = QWidget()
        row.setProperty("role", "pageRow")
        row.setProperty("dropTarget", False)
        row.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        line = QHBoxLayout(row)
        line.setContentsMargins(4, 0, 8, 0)
        line.setSpacing(2)
        arrow = QToolButton()
        arrow.setProperty("role", "pageArrow")
        arrow.setObjectName(f"page-arrow-{page['id']}")
        arrow.setAutoRaise(True)
        arrow.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        arrow.clicked.connect(partial(self._toggle_page, page["id"]))
        arrow.installEventFilter(self.pages_panel)
        name = QPushButton(f"Page {page['number']}")
        name.setProperty("role", "pageName")
        name.setObjectName(f"page-name-{page['id']}")
        name.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        name.clicked.connect(partial(self._select_page_from_click, page["id"]))
        name.installEventFilter(self.pages_panel)
        line.addWidget(arrow)
        line.addWidget(name, 1)
        hint = QLabel()
        hint.setObjectName(f"page-drop-hint-{page['id']}")
        hint.setPixmap(QIcon(_icon("arrow-right-to-line.svg")).pixmap(18, 18))
        hint.setFixedSize(20, 20)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hint.setAccessibleName("Move selected images into this page")
        hint.setToolTip("Hold here while dragging to expand the page. Release on the title to append the selected images.")
        policy = hint.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        hint.setSizePolicy(policy)
        hint.hide()
        row._drop_hint = hint
        line.addWidget(hint)
        alert_text = [text for text in warnings if f"frame {page['id']}:" in text]
        if alert_text:
            alert = QLabel("!")
            alert.setProperty("role", "alert")
            alert.setToolTip("\n".join(alert_text))
            line.addWidget(alert)
        children = QWidget()
        child_layout = QVBoxLayout(children)
        child_layout.setContentsMargins(28, 0, 4, 4)
        child_layout.setSpacing(0)
        for item in page["items"]:
            child_layout.addWidget(self._make_child(page, item))
        return row, children, arrow

    def _make_child(self, page, item):
        frame = item_frame(item)
        row = PageMarkerRow(frame, manual=item["manual"])
        row.drag_requested.connect(self._begin_marker_drag)
        row.setProperty("role", "childRow")
        row.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        if item["manual"]:
            color, note, object_name = MANUAL_DOT, "manual · kept", f"manual-{frame}"
        else:
            proposal = item["proposal"]
            color = SWATCH.get(proposal["color"], MANUAL_DOT)
            note = proposal.get("note") or ""
            object_name = f"marker-{frame}"
        line.addWidget(MarkerDot(color))
        timecode = QLabel(self.timecode_of(frame))
        timecode.setProperty("role", "mono")
        line.addWidget(timecode)
        button = QPushButton(note)
        button.setProperty("role", "childName")
        button.setObjectName(object_name)
        button.setProperty("frame", frame)
        button.setProperty("manual", item["manual"])
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(partial(self._select_tree_frame, frame, item["manual"]))
        button.installEventFilter(self.pages_panel)
        line.addWidget(button, 1)
        for widget in row.findChildren(QWidget):
            row.watch_drag(widget)
        return row

    def _toggle_page(self, page_id):
        if page_id in self.open_pages:
            self.open_pages.discard(page_id)
        else:
            self.open_pages.add(page_id)
        row = self._rows.get(page_id)
        if not row:
            return
        opened = page_id in self.open_pages
        row["children"].setVisible(opened)
        row["arrow"].setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)

    def _select_page(self, page_id):
        page = self._page(page_id)
        if page is None or not page["items"]:
            return
        item = page["items"][0]
        self._suggestions_open = bool(self.suggestions_auto_open and not item["manual"])
        self._preview = None
        self.selected_page_id = page_id
        self.selected_manual = item["manual"]
        self.selected_frame = item_frame(item)
        self._select_single_frame(self.selected_frame, self.selected_manual)
        self._move_playhead(self.selected_frame)
        self._paint_selection()
        self._refresh_center()
        self._sync_swatches()
        self._ensure_page_visible(page_id)

    def _select_page_from_click(self, page_id):
        modifiers = QApplication.keyboardModifiers()
        if not modifiers & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
            self._select_page(page_id)
            return
        page = self._page(page_id)
        if page is not None and page["items"]:
            item = page["items"][0]
            self._select_tree_frame(item_frame(item), item["manual"])
            self._ensure_page_visible(page_id)

    def _select_tree_frame(self, frame, manual):
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            self._select_frame_range(frame, manual,
                                     additive=bool(modifiers & Qt.KeyboardModifier.ControlModifier), scope="pages")
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            self._toggle_frame_selection(frame, manual)
        else:
            self._choose_frame(frame, manual)

    def _select_child(self, page_id, frame, manual, keep_suggestions=False):
        self._suggestions_open = bool((keep_suggestions or self.suggestions_auto_open) and not manual)
        self._preview = None
        self.selected_page_id = page_id
        self.selected_frame = int(frame)
        self.selected_manual = bool(manual)
        self._select_single_frame(frame, manual)
        self._move_playhead(frame)
        self._paint_selection()
        self._refresh_center()
        self._sync_swatches()

    def _choose_frame(self, frame, manual, keep_suggestions=False):
        found = self._find(frame, manual)
        if found:
            self._select_child(*found, keep_suggestions=keep_suggestions)

    def _navigable_items(self):
        """Images Left and Right walk: the current filter, in timeline order, across pages."""
        if self.view_filter == "starts":
            return list(self._view_items() or [])
        items = []
        for page in self.pages:
            for item in page["items"]:
                if self.view_filter == "core" and (item["manual"] or item["proposal"]["color"] not in (PAGE, CORE)):
                    continue
                items.append(item)
        return items

    def _arrow(self, step):
        """Left and Right. Suggestions, once opened, take the keys; otherwise the images and the ruler."""
        if self.worker is not None:
            return
        if self._suggestions_open:
            self._browse_suggestion(step)
        else:
            self._step_image(step)

    def _step_image(self, step):
        items = self._navigable_items()
        if not items:
            return
        keys = [(item_frame(item), bool(item["manual"])) for item in items]
        current = (self.selected_frame, bool(self.selected_manual))
        if current in keys:
            index = max(0, min(len(keys) - 1, keys.index(current) + step))
        elif self.selected_frame is None:
            index = 0 if step > 0 else len(keys) - 1
        else:
            frames = [frame for frame, _manual in keys]
            if step > 0:
                later = [i for i, frame in enumerate(frames) if frame > self.selected_frame]
                index = later[0] if later else len(keys) - 1
            else:
                earlier = [i for i, frame in enumerate(frames) if frame < self.selected_frame]
                index = earlier[-1] if earlier else 0
        frame, manual = keys[index]
        self._choose_frame(frame, manual)
        self._reveal_thumb()
        self.status.setText(self.timecode_of(frame))

    def _reveal_thumb(self):
        name = f"thumb-{self.selected_frame}-{'m' if self.selected_manual else 'a'}"
        card = self.thumb_area.widget().findChild(QFrame, name)
        if card is not None:
            self.thumb_area.ensureWidgetVisible(card)

    def _open_suggestions(self, frame, manual):
        """A double-click asks for the other cached images of this marker."""
        self._suggestions_open = not manual
        self._choose_frame(frame, manual, keep_suggestions=not manual)
        if manual:
            self.status.setText("A hand-placed marker has no suggestions.")
            return
        if not self._suggestion_frames():
            self._suggestions_open = False
            self._refresh_suggestions()
            self.status.setText("No cached candidate for this marker.")
            return
        self.status.setText("Suggestions · Left/Right: preview · Enter: keep · Right-click: add marker · Esc: close")

    def _step_page(self, delta):
        if not self.pages:
            return
        ids = [page["id"] for page in self.pages]
        current = ids.index(self.selected_page_id) if self.selected_page_id in ids else 0
        self._select_page(ids[max(0, min(len(ids) - 1, current + delta))])

    def _ensure_page_visible(self, page_id):
        row = self._rows.get(page_id)
        if row:
            self.pages_scroll.ensureWidgetVisible(row["row"])

    def _paint_selection(self):
        for page_id, row in self._rows.items():
            self._mark(row["row"], page_id == self.selected_page_id)
            for button in row["children"].findChildren(QPushButton):
                chosen = (button.property("frame"), bool(button.property("manual"))) in self._selected_keys
                parent = button.parentWidget()
                if parent is not None and parent.property("role") == "childRow":
                    self._mark(parent, chosen)

    def _mark(self, widget, selected):
        widget.setProperty("selected", "true" if selected else "false")
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _move_playhead(self, frame):
        self.playhead_frame = int(frame)
        self.last_seek = self.timecode_of(frame)
        self.playhead_label.setText(self.last_seek)
        self.ruler.set_playhead(self.playhead_frame)

    def seek_frame(self, frame):
        """Move the review playhead. Resolve's playhead stays where it is."""
        self._move_playhead(frame)

    def _on_ruler(self, frame):
        self._move_playhead(frame)

    def _refresh_center(self):
        self._refresh_ruler()
        self._refresh_thumbs()
        self._refresh_suggestions()
        self._refresh_board()

    def _span(self):
        shots = (self.analysis or {}).get("shots") or []
        if shots:
            return min(int(shot["start"]) for shot in shots), max(int(shot["end"]) for shot in shots)
        frames = [int(item["frame"]) for item in self.proposals]
        if not frames:
            return 0, 1
        return min(frames), max(frames) + 1

    def _refresh_ruler(self):
        start, end = self._span()
        markers = [(int(item["frame"]), item["color"]) for item in self.proposals]
        pages = (group_pages(self.proposals, (self.analysis or {}).get("manual_frames") or [],
                             include_leading_extras=bool(core_target(self.settings())
                                                        or self.settings().get("global_markers_enabled")))
                 if self._page_layout is not None else self.pages)
        firsts = [item_frame(page["items"][0]) for page in pages if page["items"]]
        spans = [(first, firsts[index + 1] if index + 1 < len(firsts) else end) for index, first in enumerate(firsts)]
        self.ruler.set_view(start, end, markers, self.playhead_frame, self._timebase(), spans,
                            source_key=id(self.analysis))

    def _set_filter(self, key):
        if key == self.view_filter:
            return
        self.view_filter = key
        self.filter_buttons[key].setChecked(True)
        self._refresh_thumbs()
        self._refresh_board()

    def _view_items(self):
        """What Strip and Board show: the page, its Core images only, or every page start."""
        if self.view_filter == "starts":
            starts = []
            for page in self.pages:
                greens = [item for item in page["items"] if not item["manual"] and item["proposal"]["color"] == PAGE]
                if greens:
                    starts.extend(greens)
            return starts
        page = self._page(self.selected_page_id) if self.selected_page_id is not None else None
        if page is None:
            return None
        items = list(page["items"])
        if self.view_filter == "core":
            items = [item for item in items if not item["manual"] and item["proposal"]["color"] in (PAGE, CORE)]
        return items

    def _refresh_thumbs(self):
        self._sync_review_camera_context()
        self._thumb_items = self._view_items()
        self._place_thumbs()
        self._update_panel_counts()

    def _update_panel_counts(self):
        if not hasattr(self, "board_panel_counter"):
            return
        items = self._view_items() or []
        if self.view_filter == "starts":
            all_items = [item for page in self.pages for item in page["items"]]
        else:
            page = self._page(self.selected_page_id) if self.selected_page_id is not None else None
            all_items = page["items"] if page else []
        for counter in (self.strip_panel_counter, self.board_panel_counter):
            counter.update_counts(items, all_items, self.view_filter)
            counter.move(10, 10)
            counter.raise_()

    def _fit_still(self, count):
        return self._thumb_fit_size(count)[0]

    def _thumb_size(self, count):
        """The viewed image width and the fixed number of columns."""
        fit, columns = self._thumb_fit_size(count)
        return self._thumb_zoom or fit, columns

    def _thumb_fit_size(self, count):
        """Fit the whole fixed arrangement by changing only its viewing scale."""
        gap = self.thumb_layout.spacing()
        width = max(1, self.thumb_area.viewport().width())
        height = max(1, self.thumb_area.viewport().height())
        image_height = self._thumb_image_height()
        columns = self._thumb_columns or balanced_columns(count, width, height, card_width=THUMB_W + 16,
                                                         card_height=image_height + CARD_TEXT)
        rows = max(1, (count + columns - 1) // columns)
        canvas_width = columns * (THUMB_W + 16) + (columns - 1) * gap
        canvas_height = rows * (image_height + CARD_TEXT) + (rows - 1) * gap
        scale = min(1.0, max(0.01, (width - 4) / canvas_width), max(0.01, (height - 4) / canvas_height))
        return max(1, int(THUMB_W * scale)), columns

    def _place_thumbs(self):
        """Choose the arrangement once per page/filter; selection and zoom keep it."""
        items = self._thumb_items
        count = len(items or [])
        context = (self.view_filter, None if self.view_filter == "starts" else self.selected_page_id, count)
        changed_context = context != self._thumb_grid_context
        if changed_context:
            self._thumb_columns = balanced_columns(count, self.thumb_area.viewport().width(),
                                                   self.thumb_area.viewport().height(),
                                                   card_width=THUMB_W + 16,
                                                   card_height=self._thumb_image_height() + CARD_TEXT)
            self._thumb_zoom = None
            # Analysis can arrive before the window is shown. Freeze the grid
            # only once its viewport has its real, visible dimensions.
            if self.thumb_area.isVisible():
                self._thumb_grid_context = context
        columns = self._thumb_columns or 1
        fit = ("cards", tuple((item_frame(item), item["manual"]) for item in items), columns,
               self.frame_format, self.frame_custom_width, self.frame_custom_height) if items else ("empty",)
        if fit != self._thumb_fit:
            self._thumb_fit = fit
            self._clear_layout(self.thumb_layout)
            for index in range(self.thumb_layout.columnCount() + 1):
                self.thumb_layout.setColumnStretch(index, 0)
            for index in range(self.thumb_layout.rowCount() + 1):
                self.thumb_layout.setRowStretch(index, 0)
            if not items:
                empty = "No page yet." if items is None else "No image of this kind on this page."
                self.thumb_layout.addWidget(self._muted(empty), 0, 0)
                self.thumb_area.set_content_size(300, 40)
            else:
                for index, item in enumerate(items):
                    self.thumb_layout.addWidget(self._thumb(item), index // columns, index % columns,
                                                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                rows = (count + columns - 1) // columns
                gap = self.thumb_layout.spacing()
                self.thumb_area.set_content_size(columns * (THUMB_W + 16) + (columns - 1) * gap,
                                                 rows * (self._thumb_image_height() + CARD_TEXT) + (rows - 1) * gap)
            self.thumb_layout.activate()
        if items:
            for index, item in enumerate(items):
                self._update_thumb(self.thumb_layout.itemAt(index).widget(), item)
        scale = self._thumb_size(count)[0] / THUMB_W if items else 1.0
        if (self.thumb_area.isVisible() and not self._camera_pending["strip"]
                and self._thumb_zoom is None
                and (changed_context or abs(self.thumb_area.transform().m11() - scale) > 1e-9)):
            self.thumb_area.set_scale(scale)

    def _zoom_thumbs(self, steps, anchor=None):
        items = self._thumb_items or []
        if not items or not steps:
            return
        self._prepare_camera_interaction("strip")
        fit = self._fit_still(len(items))
        current = self._thumb_zoom or fit
        wanted = min(720.0, max(1.0, current * (1.15 ** steps)))
        # Zooming back out to the fitted size returns to « everything in view ».
        self._thumb_zoom = None if steps < 0 and wanted <= fit else wanted
        self.thumb_area.set_scale((self._thumb_zoom or fit) / THUMB_W,
                                  anchor if self._thumb_zoom is not None else None)
        self._remember_review_camera("strip", dirty=True)

    def keyPressEvent(self, event):
        focus = QApplication.focusWidget()
        editing = focus is not None and any(focus.inherits(name) for name in
                                           ("QLineEdit", "QAbstractSpinBox", "QTextEdit", "QPlainTextEdit"))
        if event.key() == Qt.Key.Key_Delete and not editing:
            self._delete_selected_marker_proposals()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if (watched is getattr(self, "workspace_splitter", None)
                and event.type() == QEvent.Type.Show):
            # Set the columns before queued camera restores: a second startup
            # resize would accumulate pixel rounding in the saved Strip view.
            self._restore_workspace_widths()
        if (event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Delete
                and (watched is getattr(self, "board", None) or watched is getattr(self, "thumb_area", None)
                     or isinstance(watched, MarkerDragCard))):
            self._delete_selected_marker_proposals()
            return True
        if watched is getattr(self, "board", None) and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._queue_review_camera("board")
        area = getattr(self, "thumb_area", None)
        if area is None or not isValid(area) or watched is not area.viewport():
            return super().eventFilter(watched, event)
        kind = event.type()
        if kind in (QEvent.Type.Resize, QEvent.Type.Show):
            self._queue_review_camera("strip")
            self._place_thumbs()
        elif kind == QEvent.Type.Wheel:
            self._zoom_thumbs(event.angleDelta().y() / 120, event.position())
            return True
        elif kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.MiddleButton:
            self._prepare_camera_interaction("strip")
            self._thumb_pan = (event.globalPosition(), area.horizontalScrollBar().value(),
                               area.verticalScrollBar().value())
            area.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return True
        elif kind == QEvent.Type.MouseMove and self._thumb_pan is not None:
            start, left, top = self._thumb_pan
            moved = event.globalPosition() - start
            area.horizontalScrollBar().setValue(int(left - moved.x()))
            area.verticalScrollBar().setValue(int(top - moved.y()))
            self._remember_review_camera("strip")
            return True
        elif kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.MiddleButton:
            self._thumb_pan = None
            area.viewport().unsetCursor()
            self._remember_review_camera("strip", dirty=True)
            return True
        return super().eventFilter(watched, event)

    def _thumb(self, item, still=THUMB_W):
        frame = item_frame(item)
        high = max(1, round(still / self._preview_ratio()))
        card = MarkerDragCard(frame, manual=item["manual"])
        card.setProperty("role", "reviewCard")
        card.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        card.installEventFilter(self)
        card.setToolTip("Ctrl+click: add or remove an image · Shift+click: select a range · "
                        "Ctrl+Shift+click: add a range · Delete: remove selected proposals")
        card.setProperty("kind", "manual" if item["manual"] else item["proposal"]["color"])
        card.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        card.setFixedSize(still + 16, high + CARD_TEXT)
        column = QVBoxLayout(card)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(2)
        picture = CanvasImage()
        picture.set_preview_quality(self.preview_quality)
        picture.set_frame_format(self.frame_format, self.frame_custom_width, self.frame_custom_height)
        picture.setFixedSize(still, high)
        card.picture = picture
        column.addWidget(picture)
        timecode = QLabel(self.timecode_of(frame))
        timecode.setProperty("role", "mono")
        column.addWidget(timecode)
        text = QLabel()
        card.caption_label = text
        text.setProperty("role", "muted")
        column.addWidget(text)
        card.setObjectName(f"thumb-{frame}-{'m' if item['manual'] else 'a'}")
        card.clicked.connect(partial(self._choose_frame, frame, item["manual"]))
        card.additive_clicked.connect(partial(self._toggle_frame_selection, frame, item["manual"]))
        card.range_clicked.connect(partial(self._select_frame_range, frame, item["manual"]))
        card.opened.connect(partial(self._open_suggestions, frame, item["manual"]))
        card.drag_requested.connect(self._begin_marker_drag)
        card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        card.customContextMenuRequested.connect(partial(self._show_thumb_marker_menu, frame, item["manual"], card))
        self._update_thumb(card, item)
        return card

    def _update_thumb(self, card, item):
        """Keep the same widget under the pointer while selection or preview changes."""
        frame = item_frame(item)
        chosen = (frame, bool(item["manual"])) in self._selected_keys
        card.setProperty("multiSelected", chosen and len(self._selected_keys) > 1)
        active = frame == self.selected_frame and item["manual"] == self.selected_manual
        kind = "manual" if item["manual"] else item["proposal"]["color"]
        path = "" if item["manual"] else (item["proposal"].get("image") or "")
        caption = "Manual · kept" if item["manual"] else note_caption(item["proposal"].get("note"))
        state = ""
        if chosen and active and self._preview is not None:
            path, state, caption = self._preview_image() or path, "preview", "Preview · Enter keeps it"
        elif not item["manual"] and frame == self._flash:
            state, caption = "kept", "Kept"
        appearance = (chosen, kind, path, state, caption)
        if getattr(card, "_appearance", None) == appearance:
            return
        card._appearance = appearance
        card.setProperty("selected", "true" if chosen else "false")
        card.setProperty("kind", kind)
        card.setProperty("state", state)
        card.picture.set_source(path, MANUAL_DOT if item["manual"] else SWATCH.get(kind, MANUAL_DOT))
        card.caption_label.setText(caption)
        card.style().unpolish(card)
        card.style().polish(card)
        card.update()

    def _scaled(self, path, width, height, fallback):
        """A still at card size, kept in memory: going back to a page does not read the disk again."""
        cache = self.__dict__.setdefault("_thumb_cache", {})
        key = (path, width, height)
        if key not in cache:
            pixmap = QPixmap(path) if path and Path(path).is_file() else QPixmap()
            if pixmap.isNull():
                pixmap = QPixmap(width, height)
                pixmap.fill(QColor(fallback))
            else:
                pixmap = pixmap.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            cache[key] = pixmap
        return cache[key]

    def _refresh_suggestions(self):
        self._refresh_suggestion_panel()

    def get_suggestions_height(self):
        if self.suggestions_detached:
            return self._suggestion_height
        sizes = self.review_splitter.sizes()
        return sizes[1] if not self.suggestion_panel.isHidden() and sizes[1] > 0 else self._suggestion_height

    def set_suggestions_height(self, height):
        self._suggestion_height = max(120, min(4000, int(height)))
        if self.suggestions_detached or self.suggestion_panel.isHidden():
            return
        total = max(240, self.review_splitter.height() - self.review_splitter.handleWidth())
        wanted = min(self._suggestion_height, total - 120)
        self.review_splitter.setSizes([total - wanted, wanted])

    def _suggestions_splitter_moved(self, _position, _index):
        self._suggestion_height = self.get_suggestions_height()
        self._mark_project_dirty()

    def _resize_suggestions(self):
        self._resize_suggestion_cards()

    def _suggestion_frames(self):
        if self.selected_manual or self.selected_frame is None or not self.analysis:
            return []
        shot = None
        for candidate in self.analysis.get("shots") or []:
            if int(candidate["start"]) <= int(self.selected_frame) < int(candidate["end"]):
                shot = candidate
                break
        proposal = self._proposal(self.selected_frame)
        additions = list((proposal or {}).get("timeline_candidates") or [])
        if shot is None:
            return additions
        frames = {int(frame["frame"]): frame for frame in shot.get("frames") or []}
        frames.update({int(frame["frame"]): frame for frame in additions})
        frames = [frames[number] for number in sorted(frames)]
        rule = (proposal or {}).get("rule") or ""
        if rule.startswith("speech"):
            for line in self.analysis.get("utterances") or []:
                if int(line["start"]) <= int(self.selected_frame) < int(line["end"]):
                    inside = [frame for frame in frames
                              if int(line["start"]) <= int(frame["frame"]) < int(line["end"])]
                    if inside:
                        frames = inside
                    break
        return frames

    def _suggestion(self, frame, settings):
        card = SuggestionCard(self, frame["frame"])
        card.setProperty("role", "card")
        chosen = int(frame["frame"]) == self.selected_frame
        card.setProperty("selected", "true" if int(frame["frame"]) in self._selected_suggestion_frames else "false")
        card.setProperty("state", "preview" if int(frame["frame"]) == self._preview else "")
        self.__dict__.setdefault("_suggestion_cards", {})[int(frame["frame"])] = card
        column = QVBoxLayout(card)
        column.setContentsMargins(6, 6, 6, 6)
        column.setSpacing(2)
        picture = CanvasImage()
        picture.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        picture.set_preview_quality(self.preview_quality)
        path = frame.get("image") or ""
        card._suggestion_picture = picture
        picture.set_frame_format(self.frame_format, self.frame_custom_width, self.frame_custom_height)
        picture.set_source(path, PANEL_TITLE_BG)
        column.addWidget(picture)
        label = QLabel(("Current marker · " if chosen else "") + motif_of(frame, settings))
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("role", "muted")
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        card._suggestion_label = label
        column.addWidget(label)
        number = int(frame["frame"])
        card.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        card.customContextMenuRequested.connect(partial(self._show_suggestion_menu, number, card))
        card.setToolTip(f"{self.timecode_of(number)} · {label.text()}\n"
                        "Click to preview. Ctrl+click to select several suggestions. Right-click to add markers. "
                        "Double-click or Enter explicitly replaces the original image.")
        return card

    def _suggestion_menu(self, frame_number, parent=None):
        return self._make_suggestion_menu(frame_number, parent)

    def _marker_menu(self, frame_number, manual=False, parent=None):
        menu = QMenu(parent or self)
        if manual:
            menu.addAction("Hand-placed marker · kept").setEnabled(False)
        else:
            selected = self._selected_proposals() if (int(frame_number), False) in self._selected_keys else []
            batch = len(selected) > 1
            action = menu.addAction("Delete marker proposals" if batch else "Delete marker proposal")
            action.setEnabled(self.worker is None and self._proposal(frame_number) is not None)
            action.triggered.connect(lambda _checked=False: self._delete_selected_marker_proposals()
                                     if batch else self._delete_marker_proposal(frame_number))
            menu.addSeparator()
            proposal = self._proposal(frame_number)
            for color, label in COLOR_LABEL.items():
                swatch = QPixmap(12, 12)
                swatch.fill(QColor(SWATCH[color]))
                action = menu.addAction(QIcon(swatch), label)
                action.setCheckable(True)
                action.setChecked(all(item["color"] == color for item in selected) if batch else
                                  proposal is not None and proposal["color"] == color)
                action.setEnabled(self.worker is None and proposal is not None)
                action.triggered.connect(lambda _checked=False, color=color:
                                         self._set_marker_color(color) if batch else
                                         self._set_proposal_color(frame_number, color))
        return menu

    def _begin_marker_drag(self, frame):
        proposal = self._proposal(frame)
        if self.worker is not None or self._learning_job_busy or proposal is None:
            return
        if (int(frame), False) not in self._selected_keys:
            self._choose_frame(frame, False)
        numbers = {number for number, manual in self._selected_keys if not manual}
        frames = [item_frame(item) for page in self.pages for item in page["items"]
                  if not item["manual"] and item_frame(item) in numbers]
        if not frames:
            frames = [int(frame)]
        # Keep the source QObject alive while a successful drop rebuilds cards.
        pixmap = QPixmap(proposal.get("image") or "")
        if not pixmap.isNull():
            pixmap = pixmap.scaled(192, 128, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
        start_marker_drag(self, int(frame), self._drag_token, pixmap, frames=frames)

    def _show_thumb_marker_menu(self, frame_number, manual, card, position):
        point = card.mapTo(self.thumb_area.widget(), position)
        point = self.thumb_area.viewport().mapToGlobal(self.thumb_area.mapFromScene(QPointF(point)))
        self._show_marker_menu(frame_number, manual, point)

    def _show_marker_menu(self, frame_number, manual, position):
        if self.worker is not None:
            return
        if (int(frame_number), bool(manual)) not in self._selected_keys:
            self._choose_frame(frame_number, manual)
        menu = self._marker_menu(frame_number, manual)
        try:
            menu.exec(position)
        finally:
            menu.deleteLater()

    def _delete_marker_proposal(self, frame_number):
        self._delete_marker_proposals([frame_number])

    def _show_suggestion_menu(self, frame_number, card, position):
        menu = self._suggestion_menu(frame_number)
        try:
            menu.exec(card.mapToGlobal(position))
        finally:
            menu.deleteLater()

    def _suggestion_occupied(self, frame_number):
        number = int(frame_number)
        return (any(int(item["frame"]) == number for item in self.proposals)
                or number in ((self.analysis or {}).get("manual_frames") or [])
                or any(int(item["frame"]) == number and not item.get("automatic")
                       for item in (self.snapshot or {}).get("markers", [])))

    def _add_suggestion_marker(self, frame_number, color=EXTRA):
        return self._add_suggestion_markers([frame_number], color)

    def _browse_suggestion(self, step):
        """Left / Right: show the next suggestion in place of the selected image, without keeping it."""
        if self.selected_manual or self.selected_frame is None:
            return
        frames = [int(frame["frame"]) for frame in self._suggestion_frames()]
        if not frames:
            return
        current = self._preview if self._preview is not None else self.selected_frame
        index = frames.index(current) if current in frames else (-1 if step > 0 else len(frames))
        index = max(0, min(len(frames) - 1, index + step))
        self._preview = None if frames[index] == self.selected_frame else frames[index]
        self._selected_suggestion_frames = {frames[index]}
        self._refresh_center()
        card = getattr(self, "_suggestion_cards", {}).get(frames[index])
        if card is not None:
            self.suggestion_area.ensureWidgetVisible(card)
        if self._preview is None:
            self.status.setText("This is the image already kept.")
        else:
            self.status.setText(f"Preview {self.timecode_of(self._preview)} · Enter keeps it · Esc goes back")

    def _keep_preview(self):
        if self._preview is not None:
            number, self._preview = self._preview, None
            self._use_suggestion(number)

    def _cancel_preview(self):
        if self._preview is not None:
            self._selected_suggestion_frames.clear()
            self._preview = None
            self._refresh_center()
            self.status.setText("Back to the image already kept.")
            return
        if self._selected_suggestion_frames:
            self._selected_suggestion_frames.clear()
            self._update_suggestion_card_states()
            self.status.setText("Suggestion selection cleared.")
            return
        if self._suggestions_open:
            self._suggestions_open = False
            self._refresh_suggestions()
            self.status.setText("Suggestions closed.")

    def _end_flash(self):
        self._flash = None
        self._refresh_center()

    def _preview_image(self):
        for frame in self._suggestion_frames() if self._preview is not None else []:
            if int(frame["frame"]) == self._preview:
                return frame.get("image") or ""
        return ""

    @review_edit("Replace image")
    def _use_suggestion(self, frame_number):
        if self.worker is not None or self._learning_job_busy:
            return
        proposal = None if self.selected_manual else self._proposal(self.selected_frame)
        if proposal is None:
            return
        source = None
        for frame in self._suggestion_frames():
            if int(frame["frame"]) == int(frame_number):
                source = frame
                break
        if source is None:
            return
        if int(frame_number) != self.selected_frame and self._suggestion_occupied(frame_number):
            self.status.setText("That image already has a marker; it was kept unchanged.")
            return
        if any(item is not proposal and int(item["frame"]) == int(frame_number) for item in self.proposals):
            self.status.setText("That image is already a marker.")
            return
        proposal.setdefault("origin_frame", int(proposal["frame"]))
        proposal["frame"] = int(frame_number)
        self._excluded_frames.discard(int(frame_number))
        proposal["image"] = source.get("image") or ""
        proposal["mouth"] = round(float(source.get("open_mouth") or 0), 4)
        proposal["teeth"] = round(float(source.get("teeth") or 0), 4)
        proposal["sharpness"] = round(float(source.get("sharpness") or 0), 3)
        proposal["cavity"] = round(_cavity(source), 4)
        before = self.selected_frame
        if self._page_layout is not None:
            for group in self._page_layout:
                group["frames"] = [int(frame_number) if value == before else value for value in group["frames"]]
        self.selected_frame = int(frame_number)
        self.selected_manual = False
        self._select_single_frame(frame_number)
        self._preview = None
        self._flash = int(frame_number)
        self._fill()
        self._mark_project_dirty()
        self.status.setText(f"Image kept: {self.timecode_of(before)} → {self.timecode_of(frame_number)}.")
        QTimer.singleShot(700, self._end_flash)

    def _refresh_board(self):
        self._sync_review_camera_context()
        page = self._page(self.selected_page_id) if self.selected_page_id is not None else None
        items = self._view_items() or []
        self.board.preview = self._preview_image() if self._preview is not None else ""
        self.board.flash = self._flash
        self.board.set_page(items, self._oriented_size(), self.selected_frame, self.selected_manual,
                            selected_keys=self._selected_keys, preserve_view=self._preserving_review_camera())
        caption = self._caption(page)
        if self.view_filter == "starts":
            caption = f"Page starts · {self._count(len(items), 'page')}."
        elif self.view_filter == "core" and caption:
            caption = caption[:-1] + " · Core images."
        self.caption.setText(caption)
        self._update_panel_counts()

    def _preview_ratio(self):
        return frame_ratio(self.frame_format, self.frame_custom_width, self.frame_custom_height) or 16 / 9

    def _thumb_image_height(self):
        return max(1, round(THUMB_W / self._preview_ratio()))

    def _sync_preview_fields(self):
        controls = ((self.frame_format_box, self.frame_format),
                    (self.frame_width_box, self.frame_custom_width),
                    (self.frame_height_box, self.frame_custom_height),
                    (self.board_labels_check, self.show_board_labels))
        for widget, value in controls:
            blocked = widget.blockSignals(True)
            try:
                if isinstance(widget, QComboBox):
                    widget.setCurrentText(value)
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(value)
                else:
                    widget.setValue(value)
            finally:
                widget.blockSignals(blocked)
        self.frame_dimensions.setVisible(self.frame_format == "Custom")
        self.board.show_labels = self.show_board_labels
        self.board.image_ratio = self._preview_ratio()
        self.board.crop_images = self.frame_format != "Source"
        self._apply_preview_quality()

    def _apply_preview_quality(self):
        blocked = self.preview_quality_box.blockSignals(True)
        self.preview_quality_box.setCurrentText(self.preview_quality)
        self.preview_quality_box.blockSignals(blocked)
        self.board.preview_quality = self.preview_quality
        self.board.update()
        self.thumb_area.set_preview_quality(self.preview_quality)
        for card in getattr(self, "_suggestion_cards", {}).values():
            card._suggestion_picture.set_preview_quality(self.preview_quality)

    def _set_preview_quality(self, quality):
        if not self._ready or self.worker is not None or self._learning_job_busy:
            self._apply_preview_quality()
            return
        if quality not in PREVIEW_QUALITIES or quality == self.preview_quality:
            return
        self.preview_quality = quality
        self._apply_preview_quality()
        self._mark_project_dirty()
        self._schedule_save()

    def _preview_preferences_changed(self, *_args):
        if not self._ready or self.worker is not None:
            return
        cameras = self.get_review_cameras()
        self.frame_format = self.frame_format_box.currentText()
        self.frame_custom_width = self.frame_width_box.value()
        self.frame_custom_height = self.frame_height_box.value()
        self.show_board_labels = self.board_labels_check.isChecked()
        self._sync_preview_fields()
        self._refresh_center()
        self.set_review_cameras(cameras)
        self._mark_project_dirty()
        self._schedule_save()

    def _caption(self, page):
        if page is None:
            return ""
        width, height = self._oriented_size()
        name = f"{width} × {height} mm" if self.page_format == "Custom" else self.page_format
        return f"Page {page['number']} · {name} · {self.orientation}."

    def _oriented_size(self):
        if self.page_format == "Custom":
            return int(self.custom_width), int(self.custom_height)
        width, height = next((item[1], item[2]) for item in FORMATS if item[0] == self.page_format)
        if self.orientation == "landscape":
            return height, width
        return width, height

    def _sync_size_fields(self):
        width, height = self._oriented_size()
        custom = self.page_format == "Custom"
        for box, value in ((self.width_box, width), (self.height_box, height)):
            box.blockSignals(True)
            box.setValue(int(value))
            box.setEnabled(custom)
            box.blockSignals(False)

    def _choose_format(self, name):
        if name == self.page_format:
            return
        if name == "Custom":
            self.custom_width, self.custom_height = self._oriented_size()
        self.page_format = name
        self._mark_project_dirty()
        self._sync_size_fields()
        self._refresh_board()
        self._schedule_save()

    def _choose_orientation(self, name):
        if name == self.orientation:
            return
        if self.page_format == "Custom":
            self.custom_width, self.custom_height = self.custom_height, self.custom_width
        self.orientation = name
        self._mark_project_dirty()
        self._sync_size_fields()
        self._refresh_board()
        self._schedule_save()

    def _custom_size_edited(self):
        if self.page_format != "Custom":
            return
        self.custom_width = int(self.width_box.value())
        self.custom_height = int(self.height_box.value())
        self._mark_project_dirty()
        self._refresh_board()
        self._schedule_save()

    def _set_mode(self, mode):
        if mode == self.mode:
            return
        self._remember_review_camera(self.mode)
        self.mode = mode
        self.strip_button.setChecked(mode == "strip")
        self.board_button.setChecked(mode == "board")
        self.stack.setCurrentIndex(0 if mode == "strip" else 1)
        self.ruler.set_compact(mode == "board")
        self._queue_review_camera(mode)

    def _set_marker_color(self, color):
        self._set_proposal_colors([proposal["frame"] for proposal in self._selected_proposals()], color)

    def _set_proposal_color(self, frame, color):
        if self.worker is not None or color not in NAMES:
            return
        proposal = self._proposal(frame)
        if proposal is None or proposal["color"] == color:
            return
        self.selected_frame = int(proposal["frame"])
        self.selected_manual = False
        self._select_single_frame(frame)
        self._set_proposal_colors([frame], color)

    def _sync_swatches(self):
        proposals = self._selected_proposals()
        count = len(self._selected_keys)
        self.selection_count.setText(self._count(count, "image") + " selected" if count else "No image selected")
        manuals = sum(manual for _frame, manual in self._selected_keys)
        if manuals:
            self.selection_count.setText(self.selection_count.text() + f" · {manuals} read-only")
        for color, button in self.color_buttons.items():
            button.setEnabled(bool(proposals))
            button.setProperty("chosen", "true" if proposals and all(proposal["color"] == color for proposal in proposals)
                               else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def _show_settings(self):
        self.settings_dialog.show()
        self.settings_dialog.raise_()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setObjectName("")
                widget.setParent(None)
                widget.deleteLater()

    def _count(self, count, word):
        return f"{count} {word}" if count == 1 else f"{count} {word}s"

    def _refresh_target(self):
        if not hasattr(self, "page_target"):
            return
        data = self.settings()
        shots = len((self.analysis or {}).get("shots") or [])
        episode = int(data.get("episode_minutes") or 0)
        whole = f"{self._count(page_goal(data), 'page')} for {episode} min" if episode else ""
        if not shots:
            high = max(int(data["target_pages_min"]), int(data["target_pages_max"]))
            low = min(int(data["target_pages_min"]), int(data["target_pages_max"]))
            self.page_target.setText(f"Low: {self._count(high, 'page')} · High: {self._count(low, 'page')}"
                                     + (f" · for {episode} min" if episode else ""))
            return
        minutes = analyzed_minutes(self.analysis)
        goal = page_goal(data, minutes)
        aimed = target_pages(data, shots, minutes)
        text = f"Target: {self._count(aimed, 'page')}"
        if minutes and episode:
            text += f" for these {minutes:.1f} min ({whole})"
        if aimed < goal:
            text += f" — {self._count(goal, 'page')} asked, {self._count(shots, 'shot')}"
        average = core_target(data)
        if average:
            pages = sum(any(not item["manual"] and item["proposal"]["color"] in (PAGE, CORE)
                            for item in page["items"]) for page in self.pages)
            cores = sum(item["color"] in (PAGE, CORE) for item in self.proposals)
            text = f"Core target: {average:g} per page · {self._count(pages, 'page')} proposed"
            if pages:
                text += f" · average {cores / pages:.1f}"
            text += " · page and image limits apply"
        self.page_target.setText(text)

    def _warning_lines(self):
        lines = []
        if self.snapshot:
            lines.extend(self.snapshot.get("warnings") or [])
        if self.analysis:
            lines.extend(self.analysis.get("warnings") or [])
        if (self._page_layout is not None or self._excluded_frames
                or any(item.get("rule") == "user" or item.get("user_role") for item in self.proposals)):
            # Page counts from the automatic pass predate the user's additions.
            lines.extend(line for line in self.rule_warnings if not re.match(r"^Page at frame \d+:", line))
            settings = self.settings()
            for page in self.pages:
                items = [item["proposal"] for item in page["items"] if not item["manual"]]
                if not items:
                    continue
                cores = sum(item["color"] in (PAGE, CORE) for item in items)
                if cores < settings["core_page_min"] or len(items) < settings["total_page_min"]:
                    lines.append(f"Page at frame {page['id']}: {cores} Core images, {len(items)} in all, below the minimum.")
                elif cores > settings["core_page_max"] or len(items) > settings["total_page_max"]:
                    lines.append(f"Page at frame {page['id']}: the chosen images keep the page above the maximum.")
        else:
            lines.extend(self.rule_warnings)
        unique = []
        for line in lines:
            # Old running bridges and saved reviews may still carry Cue's track
            # naming notices. MP reads Video 1 by index, so they do not apply.
            if line and line.startswith(("No track is named CUE_SOURCE.", "CUE_SOURCE is not video 1 (track ")):
                continue
            # The live density summary already counts the final edited review.
            # Counts from the last automatic pass become stale after a deletion
            # or a manual addition, so do not repeat them in the warnings banner.
            if line and line.startswith(("Global marker minimum ", "Global marker maximum ", "Global marker target ")):
                continue
            if line and line not in unique:
                unique.append(line)
        return unique

    def _show_warnings(self):
        lines = self._warning_lines()
        text = "\n".join(fold_warnings(lines))
        self.warnings.setText(text)
        self.warnings.setToolTip("\n".join(lines) if len(lines) > 1 else "")
        self._sync_review_report()

    def _sync_header(self):
        source, fallback = self.snapshot or {}, {}
        if self.analysis:
            identity = normalize_identity(self.analysis.get("timeline_identity"))
            if identity is not None and identity == normalize_identity(source.get("timeline_identity")):
                fallback = self.analysis
            else:
                # Never show the project of a newly read source next to a
                # timeline belonging to another (or unverified) preparation.
                source = self.analysis
        self.timeline_label.set_source(source.get("project_name") or fallback.get("project_name"),
                                       source.get("timeline_name") or fallback.get("timeline_name"))

    def _resolve_wait_text(self, busy):
        """The script only needs launching when it is not already listening."""
        mailbox = self.client is None or getattr(self.client, "mailbox", False)
        if mailbox and not link_running():
            return "In Resolve, run Workspace > Scripts > VISPA_MP once."
        return busy

    def _sync_resolve(self):
        mailbox = self.client is not None and getattr(self.client, "mailbox", False)
        if self.client is not None and not mailbox:
            text, connected = "Resolve connected", True
        elif link_running():
            text, connected = "Resolve script connected", True
        elif mailbox or free_script_installed():
            text, connected = "Run VISPA_MP in Resolve", False
        else:
            text, connected = "Resolve not connected", False
        self.resolve_label.setText(text)
        self.resolve_dot.setProperty("connected", "true" if connected else "false")
        self.resolve_dot.style().unpolish(self.resolve_dot)
        self.resolve_dot.style().polish(self.resolve_dot)

    def _range_text(self):
        span = None
        if self.analysis and self.analysis.get("range"):
            span = self.analysis["range"]
        elif self.snapshot and self.snapshot.get("mark_in") is not None and self.snapshot.get("mark_out") is not None:
            span = (self.snapshot["mark_in"], self.snapshot["mark_out"])
        if not span or span[0] is None or span[1] is None:
            return ""
        return f"In/Out range  {self.timecode_of(span[0])} – {self.timecode_of(span[1])}"

    def resolve_payload(self):
        """The payload in Resolve's marker units: frames counted from the timeline start."""
        identity = normalize_identity((self.analysis or {}).get("timeline_identity"))
        if identity is None:
            raise RuntimeError(
                "This analysis has no verified timeline identity. Run VISPA_MP again in Resolve, "
                "then read the timeline and analyze it again before placing markers.")
        if identity != normalize_identity((self.snapshot or {}).get("timeline_identity")):
            raise RuntimeError(
                "The timeline read in VISPA MP is not the one analyzed. "
                "Read the intended timeline and analyze it before placing markers.")
        timebase = self.analysis.get("timebase") or {}
        if timebase.get("start_frame") is None:
            raise RuntimeError("The analysis has no timeline start. Read the timeline and analyze it again.")
        payload = self.apply_payload()
        payload["expected_timeline"] = identity
        offset = int(timebase["start_frame"])
        payload["proposals"] = [dict(item, frame=int(item["frame"]) - offset) for item in payload["proposals"]]
        for key in ("start", "end"):
            if payload[key] is not None:
                payload[key] = int(payload[key]) - offset
        return payload

    def apply_payload(self):
        start = end = None
        if self.analysis and self.analysis.get("range") and self.settings().get("use_in_out"):
            start, end = self.analysis["range"]
        proposals = [{"frame": item["frame"], "color": item["color"]} for item in self.proposals]
        return {"proposals": proposals, "start": start, "end": end}

    def _start(self, fn, done):
        if self.worker is not None:
            return
        self.worker = Worker(fn)
        self.worker.progressed.connect(self._on_progress)
        self.worker.failed.connect(self._failed)
        self.worker.done.connect(done)
        self.worker.finished.connect(self._worker_finished)
        self._set_review_busy(True)
        self._sync_selection_profile_panels()
        self.worker.start()

    def _on_progress(self, value):
        if self._learning_job_busy:
            self._update_learning_progress(value)
        if isinstance(value, dict):
            self.progress.show_step(value)
            self.playhead_label.hide()
            self.status.setText("")
        else:
            self.status.setText(str(value))

    def _worker_finished(self):
        self.worker = None
        self._set_review_busy(False)
        self._sync_selection_profile_panels()
        self.progress.hide()
        self.playhead_label.show()
        if self._stop_analysis is not None:
            self._stop_analysis = None
            self._set_analysis_button_state()

    def _failed(self, message):
        if self._handle_learning_failure(message):
            return
        self.status.setText(message)
        Message.tell(self, "VISPA MP", "Something went wrong.", message)

    def _cache_dir(self):
        return Path(__file__).resolve().parents[1] / "cache"

    def read_timeline(self):
        if self.worker is not None or not self._confirm_project_discard():
            return
        self.status.setText(self._resolve_wait_text("Reading the timeline…"))
        settings = self.settings()
        cache = self._cache_dir()

        def work(_progress):
            client = self.client or open_client()
            snapshot = normalize(client.read())
            saved = None
            try:
                saved = saved_analysis(snapshot, settings, cache)
            except Exception:
                saved = None  # a damaged save only means analyzing again
            return client, snapshot, saved

        def done(payload):
            self.client, self.snapshot, saved = payload
            identity = normalize_identity(self.snapshot.get("timeline_identity"))
            if self.analysis and (
                    identity is None
                    or identity != normalize_identity(self.analysis.get("timeline_identity"))
                    or self.analysis.get("key") != analysis_key(self.snapshot, settings)):
                self._forget_project_file()
                self.show_analysis(None)
            self.tracks_label.setText(f"{describe_rate(self.snapshot)} · Video 1 · Audio 1")
            self._sync_resolve()
            self._sync_header()
            name = self.snapshot.get("timeline_name") or "timeline"
            project = self.snapshot.get("project_name") or "Unknown Resolve project"
            self.status.setText(
                f"{project} · {name} · video 1: {len(self.snapshot.get('video_clips') or [])} clip(s) · "
                f"audio 1: {len(self.snapshot.get('audio_clips') or [])} · "
                f"{len(self.snapshot.get('markers') or [])} marker(s)"
            )
            self._show_warnings()
            current = (self.analysis or {}).get("key")
            if saved and saved.get("key") != current:
                self.show_analysis(saved)
                self.status.setText(
                    f"Previous analysis restored: {len(self.proposals)} markers proposed. "
                    "Analyze again only if the edit changed.")

        self._start(work, done)

    def run_analysis(self):
        if self._stop_analysis is not None:
            self._stop_analysis.set()
            self.status.setText("Stopping…")
            return
        if self.worker is not None:
            return
        if self.snapshot is None:
            self.status.setText("Read the timeline first.")
            return
        if not self._confirm_project_discard():
            return
        self.status.setText("Analyzing…")
        settings = self.settings()
        snapshot = dict(self.snapshot)
        cache = self._cache_dir()
        snapshot["cache"] = str(cache)
        stop = threading.Event()

        def work(progress):
            try:
                return analyze(snapshot, settings, progress=progress, cancel=stop.is_set, store=cache)
            except InterruptedError:
                return None

        def done(analysis):
            if analysis is None:
                self.status.setText(
                    "Analysis stopped. The images already recognized are kept: Analyze resumes from there.")
                return
            self.show_analysis(analysis)
            if analysis.get("restored"):
                self.status.setText(f"Analysis loaded from the cache: {len(self.proposals)} markers proposed.")
            else:
                self.status.setText(
                    f"{len(self.proposals)} markers proposed. A threshold recalculates without running the models.")

        self._start(work, done)
        if self.worker is not None:
            self._stop_analysis = stop
            self._set_analysis_button_state(running=True)
            self.analyze_button.setEnabled(True)

    def write_markers(self):
        if self.worker is not None:
            return
        if not self.proposals:
            self.status.setText("Nothing to place.")
            return
        if self.client is None and not free_script_installed():
            self.status.setText("Resolve is not connected.")
            return
        try:
            payload = self.resolve_payload()
        except RuntimeError as error:
            self.status.setText(str(error))
            Message.tell(self, "Place markers", "Markers were not placed.", str(error))
            return
        requested = len(payload["proposals"])
        limited = payload["start"] is not None and payload["end"] is not None
        outside = [item["frame"] for item in payload["proposals"]
                   if limited and not payload["start"] <= item["frame"] < payload["end"]]
        count = requested - len(outside)
        if not count:
            text = "No proposed marker is inside the In/Out range. No markers were changed."
            self.status.setText(text)
            Message.tell(self, "Place markers", "Nothing to place in the selected range.", text)
            return
        where = "in the In/Out range" if limited else "on the whole timeline"
        detail = f"VISPA MP replaces only its own markers {where}. Markers you placed by hand stay."
        if self._page_layout is not None:
            detail += (" Manual reading order is saved in the VISPA MP project. Resolve markers keep their "
                       "source timecodes; this placement does not encode the manual page order.")
        if outside:
            detail += (f" {self._count(count, 'proposal')} out of {requested} are inside the In/Out range; "
                       f"{self._count(len(outside), 'proposal')} outside the In/Out range will be left out.")
        if not Message.ask(
                self, "Place markers", f"Place {self._count(count, 'marker')} in {self.analysis.get('timeline_name') or 'the analyzed timeline'}?",
                detail,
                f"Place {self._count(count, 'marker')}"):
            return
        self.status.setText(self._resolve_wait_text("Placing markers…"))
        found = []

        def work(_progress):
            client = self.client or open_client()
            found.append(client)
            result = client.apply(payload["proposals"], payload["start"], payload["end"],
                                  expected_timeline=payload["expected_timeline"])
            if not isinstance(result, dict) or result.get("verified") is not True:
                raise RuntimeError(
                    "Resolve did not verify the marker placement. Run Workspace > Scripts > VISPA_MP "
                    "again to load the updated script, then retry. No successful placement can be confirmed.")
            return result

        def done(result):
            if found:
                self.client = found[0]
            self._sync_resolve()
            placed = len(result.get("placed") or [])
            failed = set(result.get("failed") or [])
            manual = [frame for frame in result.get("skipped") or [] if frame not in failed]
            omitted = result.get("outside") if "outside" in result else outside
            heading = (f"{self._count(placed, 'marker')} placed and verified in Resolve."
                       if placed else "No markers were placed.")
            details = []
            if failed:
                details.append(f"{self._count(len(failed), 'marker')} could not be created or verified in Resolve.")
            if manual:
                details.append(f"{self._count(len(manual), 'position')} kept: a hand-placed marker already exists there.")
            if omitted:
                verb = "was" if len(omitted) == 1 else "were"
                details.append(f"{self._count(len(omitted), 'proposal')} outside the In/Out range {verb} left out.")
            if not details:
                details.append("The markers were read back from the analyzed Resolve timeline.")
            detail = " ".join(details)
            self.status.setText(heading + " " + detail)
            Message.tell(self, "Marker placement", heading, detail)

        self._start(work, done)

    def download_models(self):
        self.status.setText("Downloading…")

        def work(progress):
            from vispa_mp.models_setup import ensure
            ensure(progress)
            return True

        def done(_result):
            self.status.setText("Models ready.")

        self._start(work, done)

    def _sync_outline(self):
        framed = not (self.isMaximized() or self.isFullScreen())
        margin = 1 if framed else 0
        if self.contentsMargins().left() != margin:
            self.setContentsMargins(margin, margin, margin, margin)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_outline()

    def closeEvent(self, event):
        if self.worker is not None:
            self.status.setText("Wait for the current operation, or cancel the analysis, before closing.")
            event.ignore()
            return
        if not self._confirm_project_discard():
            event.ignore()
            return
        self._timeline_request_id = getattr(self, "_timeline_request_id", 0) + 1
        if self._save_timer.isActive():
            self.save_settings()
        self.review_report_dialog.close()
        self._closing_suggestions = True
        if self.suggestions_window is not None:
            self.suggestions_window.close()
        self._close_profile_comparisons()
        if self.client is not None:
            self.client.close()
        super().closeEvent(event)


def run():
    from vispa_mp.resolve_link import install_resolve_script
    from vispa_mp.scrollbar_style import install_scrollbar_style
    try:
        install_resolve_script()
    except OSError:
        pass
    app = create_vispa_mp_application([])
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    install_scrollbar_style(app)
    window = MainWindow()
    window.show()
    return app.exec()

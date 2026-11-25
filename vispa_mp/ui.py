"""Review proposed markers, then write them to Resolve.

Strip and Board are two views of one selection. The orange playhead stays
inside this window: dragging the Video 1 ruler does not move Resolve.
"""

import os
import threading
from functools import partial
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QStackedWidget, QTabWidget, QToolButton, QVBoxLayout,
    QWidget, QMainWindow, QMessageBox,
)

from vispa_mp.analyze import analyze, refresh_utterances, saved_analysis
from vispa_mp.client import open_client
from vispa_mp.resolve_link import free_script_installed, link_running
from vispa_mp.markers import NAMES, PAGE
from vispa_mp.preset import load, load_user, save_user
from vispa_mp.rules import _cavity, page_goal, propose, target_pages
from vispa_mp.timebase import format_timecode
from vispa_mp.ui_tokens import (
    ACCENT, APP_BG, BAR_BG, BORDER_ROW, BORDER_STRONG, CONTROL, CONTROL_BG, HEADER_HEIGHT, MONO_FAMILY, PANEL_BG,
    PANEL_TITLE_BG, PLAYHEAD, PRIMARY_BG, RADIUS, SELECTED_ROW, TEXT_FAMILY,
    TEXT_MAIN, TEXT_MUTED, TEXT_SECONDARY, window_stylesheet,
)
from vispa_mp.window_chrome import BORDER_COLOUR, ChromeDialog, TitleBar, WindowChromeMixin

ICONS = Path(__file__).resolve().parent / "icons"
LINE = "#1F4250"  # the one-pixel line between two surfaces
SWATCH = {"Green": "#3c8c4a", "Blue": "#2f6fed", "Cyan": "#3ec2d6"}
MANUAL_DOT = "#8AA0A8"
COLOR_LABEL = {"Green": "Green", "Blue": "Blue", "Cyan": "Cyan"}
FORMATS = (("A5", 148, 210), ("A4", 210, 297), ("B5", 176, 250), ("Custom", None, None))
SLIDER_SCALE = {"compression": 100, "mouth_min": 100, "sharpness_floor": 2}
INTEGERS = {
    "min_marker_frames", "speech_min_silence_ms", "speech_min_duration_ms", "speech_pad_ms",
    "action_extras", "min_green_frames", "candidates_per_line",
    "target_pages_min", "target_pages_max", "core_page_min", "core_page_max",
    "total_page_min", "total_page_max",
}
SPINS = (
    ("end_fraction", "End of shot", 0.05, 0.9, 0.05),
    ("sharpness_ratio", "Sharpness relative to the shot", 0, 1, 0.05),
    ("motion_blur_max", "Motion blur maximum", 0, 1, 0.05),
    ("hold_ratio", "Hold, gap to neighbors", 0.5, 3, 0.05),
    ("min_marker_frames", "Minimum gap between markers", 1, 96, 1),
    ("expression_weight", "Expression weight", 0, 1, 0.05),
    ("speech_min_silence_ms", "Silence between lines (ms)", 40, 2000, 10),
    ("speech_min_duration_ms", "Minimum line (ms)", 40, 2000, 10),
    ("speech_threshold", "Speech threshold", 0.05, 0.95, 0.05),
    ("speech_pad_ms", "Padding around a line (ms)", 0, 400, 10),
    ("action_max_seconds", "Action shot, maximum length (s)", 0.2, 10, 0.1),
    ("action_motion", "Action shot, minimum motion", 0, 80, 0.5),
    ("action_extras", "Action extras", 0, 8, 1),
    ("duplicate_diff", "Images too alike", 0, 40, 0.5),
    ("scene_grey", "Scene change (gray)", 0, 120, 1),
    ("scene_colour", "Scene change (color)", 0, 1, 0.05),
    ("group_min", "Group shot", 0, 1, 0.05),
    ("min_green_frames", "Minimum gap between pages", 0, 500, 1),
    ("target_pages_min", "Target pages, minimum", 1, 400, 1),
    ("target_pages_max", "Target pages, maximum", 1, 400, 1),
    ("core_page_min", "Body images per page, floor", 0, 30, 1),
    ("core_page_max", "Body images per page, ceiling", 1, 30, 1),
    ("total_page_min", "Images per page, floor", 0, 40, 1),
    ("total_page_max", "Images per page, ceiling", 1, 40, 1),
    ("candidates_per_line", "Images examined per line", 1, 8, 1),
)

SPIN_OF = {key: (label, low, high, step) for key, label, low, high, step in SPINS}
CHECKS = {
    "require_open_mouth": "Require an open mouth",
    "keep_second_mouth": "Keep a second mouth",
    "skip_marked_shots": "Skip shots that already have markers",
    "use_in_out": "Analyze the In/Out range",
}
# Settings window: tab, then sections of (title, keys). "compression" and
# "mouth_fallback" are built apart; every other key is a spin box or a check box.
SETTINGS_TABS = (
    ("Pages", (
        ("Story length", ("compression", "target_pages_min", "target_pages_max")),
        ("Images per page", ("core_page_min", "core_page_max", "total_page_min", "total_page_max")),
        ("New page", ("min_green_frames", "scene_grey", "scene_colour", "group_min")),
    )),
    ("Images", (
        ("Choosing an image", ("end_fraction", "sharpness_ratio", "motion_blur_max", "hold_ratio",
                               "expression_weight")),
        ("Spacing", ("min_marker_frames", "duplicate_diff")),
        ("Action shots", ("action_max_seconds", "action_motion", "action_extras")),
    )),
    ("Speech", (
        ("Lines", ("speech_threshold", "speech_min_silence_ms", "speech_min_duration_ms", "speech_pad_ms")),
        ("Mouths", ("require_open_mouth", "mouth_fallback", "keep_second_mouth")),
    )),
    ("Analysis", (
        ("What is read", ("use_in_out", "skip_marked_shots")),
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


def group_pages(proposals, manual_frames):
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
    if text.startswith("Body"):
        return "Body"
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


class PagesPanel(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setObjectName("pages")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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


class Ruler(QWidget):
    """Video 1 ruler. The playhead belongs to this review, not to Resolve."""

    moved = Signal(int)

    def __init__(self):
        super().__init__()
        self.start = 0
        self.end = 1
        self.blocks = []
        self.playhead = None
        self.timebase = None
        self.compact = False
        self._drag = False
        self.setMinimumHeight(72)
        self.setMouseTracking(True)

    def set_compact(self, compact):
        self.compact = compact
        self.setFixedHeight(36 if compact else 72)
        self.update()

    def set_view(self, start, end, blocks, playhead, timebase):
        self.start = int(start)
        self.end = max(int(end), int(start) + 1)
        self.blocks = list(blocks)
        self.playhead = None if playhead is None else int(playhead)
        self.timebase = timebase
        self.update()

    def set_playhead(self, frame):
        self.playhead = None if frame is None else int(frame)
        self.update()

    def _x_of(self, frame):
        pad = 12
        width = max(1, self.width() - pad * 2)
        return pad + (int(frame) - self.start) / (self.end - self.start) * width

    def _frame_at(self, x):
        pad = 12
        width = max(1, self.width() - pad * 2)
        ratio = min(1.0, max(0.0, (x - pad) / width))
        return int(round(self.start + ratio * (self.end - self.start)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self.moved.emit(self._frame_at(event.position().x()))

    def mouseMoveEvent(self, event):
        if self._drag:
            self.moved.emit(self._frame_at(event.position().x()))

    def mouseReleaseEvent(self, _event):
        self._drag = False

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(PANEL_BG))
        painter.setPen(QColor(TEXT_MUTED))
        painter.setFont(QFont(MONO_FAMILY, 9))
        for index in range(5):
            frame = self.start + (self.end - self.start) * index / 4
            x = int(self._x_of(frame))
            painter.drawLine(x, 18 if not self.compact else 4, x, 26 if not self.compact else 10)
            if self.timebase and not self.compact:
                label = format_timecode(int(frame), self.timebase)
                painter.drawText(x + 4, 16, label)
        top = 30 if not self.compact else 14
        height = 18 if not self.compact else 10
        for start, end, color in self.blocks:
            left = int(self._x_of(start))
            right = max(left + 4, int(self._x_of(end)))
            painter.fillRect(QRect(left, top, right - left, height), QColor(SWATCH.get(color, MANUAL_DOT)))
        if self.playhead is None:
            return
        x = int(self._x_of(self.playhead))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PLAYHEAD))
        painter.drawPolygon(QPolygon([QPoint(x - 6, 2), QPoint(x + 6, 2), QPoint(x, 12)]))
        painter.setPen(QPen(QColor(PLAYHEAD), 2))
        painter.drawLine(x, 12, x, self.height() - 4)


class PageBoard(QWidget):
    """A plain reading-order preview. It does not write a VISPA layout."""

    chosen = Signal(int, bool)

    def __init__(self):
        super().__init__()
        self.items = []
        self.size_mm = (148, 210)
        self.selected = None
        self.selected_manual = False
        self._hits = []
        self._pixmaps = {}

    def set_page(self, items, size_mm, selected, selected_manual):
        self.items = list(items)
        self.size_mm = size_mm
        self.selected = selected
        self.selected_manual = selected_manual
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(APP_BG))
        self._hits = []
        if not self.items:
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Read the timeline, then analyze.")
            return
        page = self._page_rect()
        painter.fillRect(page, QColor("#f7f4ee"))
        for item, rect in self._card_rects(page):
            self._hits.append((rect, item))
            self._paint_card(painter, item, rect)

    def mousePressEvent(self, event):
        point = event.position().toPoint()
        for rect, item in self._hits:
            if rect.contains(point):
                self.chosen.emit(item_frame(item), item["manual"])
                return

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
        pad, gutter = 12, 8
        inner = page.adjusted(pad, pad, -pad, -pad)
        greens = [item for item in self.items if not item["manual"] and item["proposal"]["color"] == PAGE]
        rest = [item for item in self.items if item not in greens]
        cyans = [item for item in rest if not item["manual"] and item["proposal"]["color"] == EXTRA]
        bodies = [item for item in rest if item not in cyans]
        rects = []
        y = inner.top()
        if greens:
            height = int(inner.height() * (0.42 if rest else 0.92))
            for item in greens:
                rects.append((item, QRect(inner.left(), y, inner.width(), height)))
            y += height + gutter
        remain = max(0, inner.bottom() - y)
        if bodies and cyans:
            cyan_h = max(48, int(remain * 0.30))
            body_h = max(48, remain - cyan_h - gutter)
        elif cyans:
            cyan_h, body_h = remain, 0
        else:
            body_h, cyan_h = remain, 0
        if bodies and body_h:
            rects.extend(_grid(bodies, inner.left(), y, inner.width(), body_h, gutter))
            y += body_h + gutter
        if cyans and cyan_h:
            rects.extend(_grid(cyans, inner.left(), y, inner.width(), cyan_h, gutter))
        return rects

    def _paint_card(self, painter, item, rect):
        color = MANUAL_DOT if item["manual"] else SWATCH.get(item["proposal"]["color"], MANUAL_DOT)
        painter.fillRect(rect, QColor("#d7d0c4"))
        path = "" if item["manual"] else (item["proposal"].get("image") or "")
        pixmap = self._pixmap(path)
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(rect.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(rect, scaled, QRect(0, 0, rect.width(), rect.height()))
        else:
            painter.fillRect(rect.adjusted(8, 8, -8, -8), QColor(color))
        note = "manual · kept" if item["manual"] else short_note(item["proposal"].get("note"))
        badge = QRect(rect.left() + 6, rect.top() + 6, min(rect.width() - 12, max(48, 8 * len(note) + 16)), 18)
        painter.fillRect(badge, QColor(color))
        painter.setPen(QColor("#f7f4ee"))
        painter.setFont(QFont(TEXT_FAMILY, 8))
        painter.drawText(badge.adjusted(4, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, note)
        chosen = item_frame(item) == self.selected and item["manual"] == self.selected_manual
        if chosen:
            painter.setPen(QPen(QColor(ACCENT), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -2, -2))

    def _pixmap(self, path):
        if not path:
            return None
        cached = self._pixmaps.get(path)
        if cached is not None:
            return cached
        pixmap = QPixmap(path) if Path(path).is_file() else QPixmap()
        self._pixmaps[path] = pixmap
        return pixmap


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
    QWidget[role="pageRow"][selected="true"], QWidget[role="childRow"][selected="true"] {{ background: {SELECTED_ROW}; }}
    QToolButton[role="pageArrow"] {{ background: transparent; border: 0; padding: 0; min-width: 28px;
        max-width: 28px; min-height: 28px; max-height: 28px; }}
    QPushButton[role="choice"]:checked {{ background: {SELECTED_ROW}; border-color: {ACCENT}; color: {TEXT_MAIN}; }}
    QPushButton[role="swatch"] {{ padding: 0; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px;
        border: 2px solid transparent; border-radius: {RADIUS}px; }}
    QPushButton[role="swatch"][chosen="true"] {{ border-color: {ACCENT}; }}
    QPushButton#color-Green {{ background: {SWATCH['Green']}; }}
    QPushButton#color-Blue {{ background: {SWATCH['Blue']}; }}
    QPushButton#color-Cyan {{ background: {SWATCH['Cyan']}; }}
    QFrame[role="card"] {{ background: {BAR_BG}; border: 1px solid #1F4250; border-radius: {RADIUS}px; }}
    QFrame[role="card"][selected="true"] {{ border: 2px solid {ACCENT}; }}
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
    QToolButton#settingsButton {{ padding: 0; min-width: {CONTROL - 2}px; max-width: {CONTROL - 2}px;
        qproperty-iconSize: 16px; }}

    QDialog#chromeDialog {{ background: {BORDER_COLOUR}; }}
    QWidget#dialogBody, QWidget#settingsHost {{ background: {PANEL_BG}; }}
    QLabel[role="section"] {{ color: {ACCENT}; font-size: 12px; font-weight: 600; padding: 4px 0 2px 0; }}
    QTabWidget#settingsTabs::pane {{ border: 0; border-top: 1px solid {LINE}; }}
    QTabWidget#settingsTabs QTabBar {{ background: {BAR_BG}; }}
    QTabBar::tab {{ background: transparent; color: {TEXT_MUTED}; border: 0; border-bottom: 2px solid transparent;
        padding: 8px 16px; margin: 0; }}
    QTabBar::tab:hover {{ color: {TEXT_MAIN}; }}
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
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {BORDER_STRONG}; border-radius: 3px;
        background: {APP_BG}; }}
    QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
    QCheckBox::indicator:checked {{ background: {PRIMARY_BG}; border-color: {PRIMARY_BG};
        image: url("{_icon('check.svg')}"); }}
    """


class MainWindow(WindowChromeMixin, QMainWindow):
    def __init__(self, client=None):
        super().__init__()
        self.setWindowTitle("VISPA MP — markers")
        self.resize(1280, 800)
        self.client = client
        self.snapshot = None
        self.analysis = None
        self.proposals = []
        self.rule_warnings = []
        self.pages = []
        self.open_pages = set()
        self.selected_page_id = None
        self.selected_frame = None
        self.selected_manual = False
        self.playhead_frame = None
        self.last_seek = None
        self.worker = None
        self._stop_analysis = None
        self.mode = "strip"
        self._stored_settings, view = load_user()
        names = [name for name, _width, _height in FORMATS]
        self.page_format = view["page_format"] if view["page_format"] in names else "A5"
        self.orientation = view["orientation"] if view["orientation"] in ("portrait", "landscape") else "portrait"
        self.custom_width = min(2000, max(10, int(view["custom_width"])))
        self.custom_height = min(2000, max(10, int(view["custom_height"])))
        self._ready = False
        self.widgets = {}
        self._rows = {}
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
        layout.addWidget(self.warnings)
        layout.addWidget(self._build_modes())
        layout.addWidget(separator())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_pages())
        body.addWidget(separator(vertical=True))
        body.addWidget(self._build_center(), 1)
        body.addWidget(separator(vertical=True))
        body.addWidget(self._build_adjust())
        layout.addLayout(body, 1)
        layout.addWidget(separator())
        layout.addWidget(self._build_footer())
        self._build_settings()
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
        self._refresh_target()
        self.ruler.set_compact(False)

    def _build_header(self):
        """The toolbar: the three actions, the timeline name, Resolve and Settings."""
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(HEADER_HEIGHT)
        grid = QGridLayout(header)
        grid.setContentsMargins(12, 0, 8, 0)
        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        self.read_button = QPushButton("Read timeline")
        self.analyze_button = QPushButton("Analyze")
        self.apply_button = QPushButton("Place markers")
        self.apply_button.setProperty("primary", True)
        for button in (self.read_button, self.analyze_button, self.apply_button):
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            left.addWidget(button)
        self.timeline_label = QLabel("—")
        self.timeline_label.setObjectName("timelineName")
        self.timeline_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
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
        self.pages_panel.setFixedWidth(280)
        column = QVBoxLayout(self.pages_panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        title = QLabel("Pages")
        title.setProperty("role", "panelTitle")
        column.addWidget(title)
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
        center.setObjectName("center")
        column = QVBoxLayout(center)
        column.setContentsMargins(12, 8, 12, 8)
        column.setSpacing(8)
        video = QLabel("Video 1")
        video.setProperty("role", "muted")
        column.addWidget(video)
        self.ruler = Ruler()
        self.ruler.moved.connect(self._on_ruler)
        column.addWidget(self.ruler)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_strip())
        self.stack.addWidget(self._build_board())
        column.addWidget(self.stack, 1)
        return center

    def _build_strip(self):
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        self.thumb_area, self.thumb_layout = self._horizontal_strip(148)
        column.addWidget(self.thumb_area)
        suggestions = QLabel("Suggestions")
        suggestions.setProperty("role", "panelTitle")
        column.addWidget(suggestions)
        self.suggestion_area, self.suggestion_layout = self._horizontal_strip(128)
        column.addWidget(self.suggestion_area)
        column.addStretch(1)
        return page

    def _horizontal_strip(self, height):
        area = QScrollArea()
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidgetResizable(False)
        area.setFixedHeight(height)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        area.setWidget(host)
        return area, row

    def _build_board(self):
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        column.addWidget(self._build_format_bar())
        self.board_scroll = QScrollArea()
        self.board_scroll.setWidgetResizable(True)
        self.board_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.board = PageBoard()
        self.board.chosen.connect(self._choose_frame)
        self.board_scroll.setWidget(self.board)
        column.addWidget(self.board_scroll, 1)
        self.caption = QLabel("")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setProperty("role", "muted")
        column.addWidget(self.caption)
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
        return bar

    def _build_adjust(self):
        panel = QWidget()
        panel.setObjectName("adjust")
        panel.setFixedWidth(260)
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 8)
        column.setSpacing(8)
        title = QLabel("Adjust")
        title.setProperty("role", "panelTitle")
        column.addWidget(title)
        values = self._stored_settings
        form = QWidget()
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(12, 0, 12, 0)
        form_layout.setSpacing(10)
        self.sharpness_value = QLabel()
        sharpness = self._labeled_slider("sharpness_floor", "Sharpness", 0, 1000, values, self.sharpness_value)
        form_layout.addWidget(sharpness)
        self.mouth_value = QLabel()
        mouth = self._labeled_slider("mouth_min", "Mouth", 0, 100, values, self.mouth_value)
        form_layout.addWidget(mouth)
        self.recalculate_button = QPushButton("Recalculate")
        self.recalculate_button.setObjectName("recalculate")
        self.recalculate_button.clicked.connect(self.recompute)
        form_layout.addWidget(self.recalculate_button)
        color_title = QLabel("Marker color")
        color_title.setProperty("role", "muted")
        form_layout.addWidget(color_title)
        swatches = QHBoxLayout()
        self.color_buttons = {}
        for color, label in COLOR_LABEL.items():
            box = QVBoxLayout()
            button = QPushButton("")
            button.setObjectName(f"color-{color}")
            button.setProperty("role", "swatch")
            button.clicked.connect(partial(self._set_marker_color, color))
            caption = QLabel(label)
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setProperty("role", "muted")
            box.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
            box.addWidget(caption)
            swatches.addLayout(box)
            self.color_buttons[color] = button
        form_layout.addLayout(swatches)
        hand = QLabel("Hand-placed markers stay.")
        hand.setWordWrap(True)
        hand.setProperty("role", "muted")
        form_layout.addWidget(hand)
        column.addWidget(form)
        column.addStretch(1)
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
        tracks = QLabel("Video 1 · Audio 1")
        tracks.setProperty("role", "muted")
        row.addWidget(tracks)
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
        for title, sections in SETTINGS_TABS:
            self.settings_tabs.addTab(self._settings_page(sections, values), title)
        outer.addWidget(self.settings_tabs, 1)
        outer.addSpacing(16)
        outer.addWidget(separator())
        outer.addSpacing(14)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(16, 0, 16, 0)
        buttons.setSpacing(8)
        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Back to the shipped settings. The page format stays.")
        self.download_button = QPushButton("Download models")
        self.reset_button.clicked.connect(self.reset_settings)
        self.download_button.clicked.connect(self.download_models)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        buttons.addWidget(self.download_button)
        outer.addLayout(buttons)

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
            heading = QLabel(title)
            heading.setProperty("role", "section")
            if index:
                heading.setContentsMargins(0, 12, 0, 0)
            form.addRow(heading)
            for key in keys:
                self._settings_row(form, key, values)
        column.addLayout(form)
        column.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _settings_row(self, form, key, values):
        if key == "compression":
            story = QWidget()
            story_layout = QVBoxLayout(story)
            story_layout.setContentsMargins(0, 0, 0, 0)
            story_layout.setSpacing(2)
            self.compression = QSlider(Qt.Orientation.Horizontal)
            self.compression.setRange(0, 100)
            self.compression.setMinimumWidth(200)
            self.compression.setValue(int(round(float(values["compression"]) * 100)))
            self.compression.valueChanged.connect(self._changed)
            self.widgets["compression"] = self.compression
            ends = QHBoxLayout()
            ends.addWidget(self._muted("Low"))
            ends.addStretch(1)
            ends.addWidget(self._muted("High"))
            self.page_target = QLabel("")
            self.page_target.setProperty("role", "muted")
            self.page_target.setWordWrap(True)
            story_layout.addWidget(self.compression)
            story_layout.addLayout(ends)
            story_layout.addWidget(self.page_target)
            form.addRow("Story compression", story)
            return
        if key == "mouth_fallback":
            mouth = QComboBox()
            mouth.addItem("Sharp image", "sharp")
            mouth.addItem("Propose nothing", "none")
            mouth.setCurrentIndex(max(0, mouth.findData(values["mouth_fallback"])))
            mouth.currentIndexChanged.connect(self._changed)
            mouth.setFixedWidth(150)
            self.widgets["mouth_fallback"] = mouth
            form.addRow("If the mouth is not seen", mouth)
            return
        if key in CHECKS:
            box = QCheckBox(CHECKS[key])
            box.setChecked(bool(values[key]))
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
        widget.valueChanged.connect(self._changed)
        self.widgets[key] = widget
        form.addRow(label, widget)

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
        }
        try:
            save_user(self.settings(), view)
        except OSError as error:
            self.status.setText(f"Settings were not saved: {error}")

    def _changed(self, *_args):
        self._schedule_save()
        if getattr(self, "page_target", None) is not None:
            self._refresh_target()
        self._show_slider_value("sharpness_floor", getattr(self, "sharpness_value", None))
        self._show_slider_value("mouth_min", getattr(self, "mouth_value", None))
        if self._ready and self.analysis is not None and self.worker is None:
            self.recompute()

    def _show_slider_value(self, key, label):
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

    def reset_settings(self):
        """Back to presets/default.json. The page format is a view choice and stays."""
        self._ready = False
        shipped = load()
        self._stored_settings = dict(shipped)
        for key, value in shipped.items():
            if key in self.widgets:
                self.set_setting(key, value)
        self._ready = True
        self.save_settings()
        self._refresh_target()
        self.recompute()

    def show_analysis(self, analysis):
        self.analysis = analysis
        self.selected_frame = None
        self.selected_page_id = None
        self.open_pages = set()
        self.recompute()

    def recompute(self):
        if not self.analysis:
            self.proposals = []
            self.rule_warnings = []
            self._fill()
            return
        viewed = dict(self.analysis)
        if viewed.get("speech_tracks"):
            viewed["utterances"] = refresh_utterances(viewed, self.settings())
        result = propose(viewed, self.settings())
        self.proposals = result["proposals"]
        self.rule_warnings = result["warnings"]
        self._fill()

    def timecode_of(self, frame):
        base = self._timebase()
        if not base:
            return str(frame)
        return format_timecode(int(frame), base)

    def _timebase(self):
        if self.analysis and self.analysis.get("timebase"):
            return self.analysis["timebase"]
        if not self.snapshot:
            return None
        return {
            "fps": self.snapshot.get("fps") or 24,
            "start_frame": self.snapshot.get("start_frame") or 0,
            "start_timecode": self.snapshot.get("start_timecode") or "00:00:00:00",
            "drop": bool(self.snapshot.get("drop")),
        }

    def _fill(self):
        manuals = list((self.analysis or {}).get("manual_frames") or [])
        self.pages = group_pages(self.proposals, manuals)
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
        self._rebuild_tree()
        self._refresh_center()
        self._refresh_target()
        self._show_warnings()
        self._sync_header()
        self._sync_swatches()

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
        name.clicked.connect(partial(self._select_page, page["id"]))
        name.installEventFilter(self.pages_panel)
        line.addWidget(arrow)
        line.addWidget(name, 1)
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
        row = QWidget()
        row.setProperty("role", "childRow")
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
        button.clicked.connect(partial(self._select_child, page["id"], frame, item["manual"]))
        button.installEventFilter(self.pages_panel)
        line.addWidget(button, 1)
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
        self.selected_page_id = page_id
        self.selected_manual = item["manual"]
        self.selected_frame = item_frame(item)
        self._move_playhead(self.selected_frame)
        self._paint_selection()
        self._refresh_center()
        self._sync_swatches()
        self._ensure_page_visible(page_id)

    def _select_child(self, page_id, frame, manual):
        self.selected_page_id = page_id
        self.selected_frame = int(frame)
        self.selected_manual = bool(manual)
        self._move_playhead(frame)
        self._paint_selection()
        self._refresh_center()
        self._sync_swatches()

    def _choose_frame(self, frame, manual):
        found = self._find(frame, manual)
        if found:
            self._select_child(*found)

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
                chosen = (page_id == self.selected_page_id and button.property("frame") == self.selected_frame
                          and bool(button.property("manual")) == self.selected_manual)
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
        ordered = sorted(self.proposals, key=lambda item: int(item["frame"]))
        blocks = []
        for index, proposal in enumerate(ordered):
            frame = int(proposal["frame"])
            nxt = int(ordered[index + 1]["frame"]) if index + 1 < len(ordered) else frame + 1
            blocks.append((frame, max(nxt, frame + 1), proposal["color"]))
        self.ruler.set_view(start, end, blocks, self.playhead_frame, self._timebase())

    def _refresh_thumbs(self):
        self._clear_layout(self.thumb_layout)
        page = self._page(self.selected_page_id) if self.selected_page_id is not None else None
        if page is None:
            self.thumb_layout.addWidget(self._muted("No page yet."))
        else:
            for item in page["items"]:
                self.thumb_layout.addWidget(self._thumb(item))
        self.thumb_layout.addStretch(1)
        self.thumb_area.widget().adjustSize()

    def _thumb(self, item):
        frame = item_frame(item)
        card = QFrame()
        card.setProperty("role", "card")
        card.setFixedSize(132, 128)
        chosen = frame == self.selected_frame and item["manual"] == self.selected_manual
        card.setProperty("selected", "true" if chosen else "false")
        column = QVBoxLayout(card)
        column.setContentsMargins(6, 6, 6, 6)
        column.setSpacing(2)
        picture = QLabel()
        picture.setFixedHeight(68)
        picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = "" if item["manual"] else (item["proposal"].get("image") or "")
        pixmap = QPixmap(path) if path and Path(path).is_file() else QPixmap()
        if pixmap.isNull():
            color = MANUAL_DOT if item["manual"] else SWATCH.get(item["proposal"]["color"], MANUAL_DOT)
            blank = QPixmap(120, 68)
            blank.fill(QColor(color))
            picture.setPixmap(blank)
        else:
            picture.setPixmap(pixmap.scaled(120, 68, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
        column.addWidget(picture)
        timecode = QLabel(self.timecode_of(frame))
        timecode.setProperty("role", "mono")
        column.addWidget(timecode)
        if item["manual"]:
            caption = "manual · kept"
        else:
            caption = f"{COLOR_LABEL.get(item['proposal']['color'], '')} · {short_note(item['proposal'].get('note'))}"
        text = QLabel(caption)
        text.setProperty("role", "muted")
        column.addWidget(text)
        card.mousePressEvent = lambda _event, frame=frame, manual=item["manual"]: self._choose_frame(frame, manual)
        return card

    def _refresh_suggestions(self):
        self._clear_layout(self.suggestion_layout)
        frames = self._suggestion_frames()
        if not frames:
            self.suggestion_layout.addWidget(self._muted("No cached candidate for this marker."))
        settings = self.settings()
        for frame in frames:
            self.suggestion_layout.addWidget(self._suggestion(frame, settings))
        self.suggestion_layout.addStretch(1)
        self.suggestion_area.widget().adjustSize()

    def _suggestion_frames(self):
        if self.selected_manual or self.selected_frame is None or not self.analysis:
            return []
        shot = None
        for candidate in self.analysis.get("shots") or []:
            if int(candidate["start"]) <= int(self.selected_frame) < int(candidate["end"]):
                shot = candidate
                break
        if shot is None:
            return []
        frames = list(shot.get("frames") or [])
        proposal = self._proposal(self.selected_frame)
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
        card = QFrame()
        card.setProperty("role", "card")
        card.setFixedSize(104, 112)
        chosen = int(frame["frame"]) == self.selected_frame
        card.setProperty("selected", "true" if chosen else "false")
        column = QVBoxLayout(card)
        column.setContentsMargins(6, 6, 6, 6)
        picture = QLabel()
        picture.setFixedHeight(68)
        picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = frame.get("image") or ""
        pixmap = QPixmap(path) if path and Path(path).is_file() else QPixmap()
        if pixmap.isNull():
            blank = QPixmap(92, 68)
            blank.fill(QColor(PANEL_TITLE_BG))
            picture.setPixmap(blank)
        else:
            picture.setPixmap(pixmap.scaled(92, 68, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
        column.addWidget(picture)
        label = QLabel(motif_of(frame, settings))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("role", "muted")
        column.addWidget(label)
        number = int(frame["frame"])
        card.mousePressEvent = lambda _event, number=number: self._use_suggestion(number)
        return card

    def _use_suggestion(self, frame_number):
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
        if any(item is not proposal and int(item["frame"]) == int(frame_number) for item in self.proposals):
            self.status.setText("That image is already a marker.")
            return
        proposal["frame"] = int(frame_number)
        proposal["image"] = source.get("image") or ""
        proposal["mouth"] = round(float(source.get("open_mouth") or 0), 4)
        proposal["teeth"] = round(float(source.get("teeth") or 0), 4)
        proposal["sharpness"] = round(float(source.get("sharpness") or 0), 3)
        proposal["cavity"] = round(_cavity(source), 4)
        self.selected_frame = int(frame_number)
        self.selected_manual = False
        self._fill()

    def _refresh_board(self):
        page = self._page(self.selected_page_id) if self.selected_page_id is not None else None
        items = page["items"] if page else []
        self.board.set_page(items, self._oriented_size(), self.selected_frame, self.selected_manual)
        self.caption.setText(self._caption(page))

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
        self._sync_size_fields()
        self._refresh_board()
        self._schedule_save()

    def _choose_orientation(self, name):
        if name == self.orientation:
            return
        if self.page_format == "Custom":
            self.custom_width, self.custom_height = self.custom_height, self.custom_width
        self.orientation = name
        self._sync_size_fields()
        self._refresh_board()
        self._schedule_save()

    def _custom_size_edited(self):
        if self.page_format != "Custom":
            return
        self.custom_width = int(self.width_box.value())
        self.custom_height = int(self.height_box.value())
        self._refresh_board()
        self._schedule_save()

    def _set_mode(self, mode):
        if mode == self.mode:
            return
        self.mode = mode
        self.strip_button.setChecked(mode == "strip")
        self.board_button.setChecked(mode == "board")
        self.stack.setCurrentIndex(0 if mode == "strip" else 1)
        self.ruler.set_compact(mode == "board")

    def _set_marker_color(self, color):
        if self.selected_manual:
            return
        proposal = self._proposal(self.selected_frame) if self.selected_frame is not None else None
        if proposal is None:
            return
        proposal["color"] = color
        proposal["name"] = NAMES[color]
        self.selected_frame = int(proposal["frame"])
        self.selected_manual = False
        self._fill()

    def _sync_swatches(self):
        proposal = None if self.selected_manual or self.selected_frame is None else self._proposal(self.selected_frame)
        for color, button in self.color_buttons.items():
            button.setEnabled(proposal is not None)
            button.setProperty("chosen", "true" if proposal is not None and proposal["color"] == color else "false")
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
        goal = page_goal(data)
        shots = len((self.analysis or {}).get("shots") or [])
        if not shots:
            high = max(int(data["target_pages_min"]), int(data["target_pages_max"]))
            low = min(int(data["target_pages_min"]), int(data["target_pages_max"]))
            self.page_target.setText(f"Low: {self._count(high, 'page')} · High: {self._count(low, 'page')}")
            return
        aimed = target_pages(data, shots)
        text = f"Target: {self._count(aimed, 'page')}"
        if aimed < goal:
            text += f" — {self._count(goal, 'page')} asked, {self._count(shots, 'shot')}"
        self.page_target.setText(text)

    def _warning_lines(self):
        lines = []
        if self.snapshot:
            lines.extend(self.snapshot.get("warnings") or [])
        if self.analysis:
            lines.extend(self.analysis.get("warnings") or [])
        lines.extend(self.rule_warnings)
        unique = []
        for line in lines:
            if line and line not in unique:
                unique.append(line)
        return unique

    def _show_warnings(self):
        text = "\n".join(self._warning_lines())
        self.warnings.setText(text)
        self.warnings.setVisible(bool(text))

    def _sync_header(self):
        name = ""
        if self.analysis:
            name = self.analysis.get("timeline_name") or ""
        if not name and self.snapshot:
            name = self.snapshot.get("timeline_name") or ""
        self.timeline_label.setText(name or "—")

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
        self.worker.start()

    def _on_progress(self, value):
        if isinstance(value, dict):
            self.progress.show_step(value)
            self.playhead_label.hide()
            self.status.setText("")
        else:
            self.status.setText(str(value))

    def _worker_finished(self):
        self.worker = None
        self.progress.hide()
        self.playhead_label.show()
        if self._stop_analysis is not None:
            self._stop_analysis = None
            self.analyze_button.setText("Analyze")

    def _failed(self, message):
        self.status.setText(message)
        QMessageBox.warning(self, "VISPA MP", message)

    def _cache_dir(self):
        return Path(__file__).resolve().parents[1] / "cache"

    def read_timeline(self):
        self.status.setText(self._resolve_wait_text("Reading the timeline…"))
        settings = self.settings()
        cache = self._cache_dir()

        def work(_progress):
            client = self.client or open_client()
            snapshot = client.read()
            saved = None
            try:
                saved = saved_analysis(snapshot, settings, cache)
            except Exception:
                saved = None  # a damaged save only means analyzing again
            return client, snapshot, saved

        def done(payload):
            self.client, self.snapshot, saved = payload
            self._sync_resolve()
            self._sync_header()
            name = self.snapshot.get("timeline_name") or "timeline"
            self.status.setText(
                f"{name} · video 1: {len(self.snapshot.get('video_clips') or [])} clip(s) · "
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
            self.analyze_button.setText("Cancel")

    def write_markers(self):
        if not self.proposals:
            self.status.setText("Nothing to place.")
            return
        if self.client is None and not free_script_installed():
            self.status.setText("Resolve is not connected.")
            return
        count = len(self.proposals)
        answer = QMessageBox.question(
            self, "Markers",
            f"Place {count} markers in Resolve? Hand-placed markers stay.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        payload = self.apply_payload()
        self.status.setText(self._resolve_wait_text("Placing markers…"))
        found = []

        def work(_progress):
            client = self.client or open_client()
            found.append(client)
            return client.apply(payload["proposals"], payload["start"], payload["end"])

        def done(result):
            if found:
                self.client = found[0]
            self._sync_resolve()
            self.status.setText(
                f"{len(result.get('placed') or [])} placed, "
                f"{len(result.get('skipped') or [])} left (a hand-placed marker is already there)."
            )

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
        if self._save_timer.isActive():
            self.save_settings()
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
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    install_scrollbar_style(app)
    window = MainWindow()
    window.show()
    return app.exec()

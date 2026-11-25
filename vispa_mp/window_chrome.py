"""VISPA's 30px caption, with Windows still moving, sizing and snapping the window.

Same glyphs, height and colours as VISPA's ShellTitleBar, already used by VISPA Cue.
Windows keeps a resizable frame. Only the painted caption is ours.
"""
import sys

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton, QDialog, QFrame, QHBoxLayout, QLabel, QMenuBar, QPushButton, QVBoxLayout, QWidget,
)
from shiboken6 import isValid

# WS_CAPTION | WS_SYSMENU | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
NATIVE_FRAME = 0x00CF0000

TITLEBAR_MINIMIZE = "─"
TITLEBAR_MAXIMIZE = "⛶"
TITLEBAR_RESTORE = "❐"
TITLEBAR_CLOSE = "X"
# The window's outline: the teal of the main button. Windows 11 draws one pixel
# along the rounded corners, the window paints one more inside: two in all.
BORDER_COLOUR = "#1FB5A7"


def _colorref(colour):
    red, green, blue = (int(colour[index:index + 2], 16) for index in (1, 3, 5))
    return red | (green << 8) | (blue << 16)


def round_and_outline(widget, colour=BORDER_COLOUR):
    """Windows 11: rounded corners and a coloured one-pixel border. False elsewhere."""
    if sys.platform != "win32" or sys.getwindowsversion().build < 22000:
        return False
    from PySide6.QtWidgets import QApplication
    if QApplication.platformName() != "windows":
        return False
    import ctypes
    from ctypes import wintypes
    hwnd = wintypes.HWND(int(widget.winId()))
    rounding = ctypes.c_int(2)  # DWMWCP_ROUND
    rounded = ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rounding), ctypes.sizeof(rounding)) == 0
    border = ctypes.c_uint(_colorref(colour) if colour else 0xFFFFFFFE)  # DWMWA_BORDER_COLOR
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border), ctypes.sizeof(border))
    return rounded


class TitlebarCloseButton(QPushButton):
    """VISPA's inset rounded close hover."""

    def paintEvent(self, event):
        if self.underMouse():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#ae3643"))
            inset = self.width() * 0.075
            painter.drawRoundedRect(
                QRectF(inset, 0, self.width() - 2 * inset, self.height()).adjusted(0.5, 0.5, -0.5, -0.5),
                6, 6)
            painter.end()
        super().paintEvent(event)


class TitleBar(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.setObjectName("titlebar")
        self.setFixedHeight(30)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 0, 0)
        row.setSpacing(8)
        self.menus = QMenuBar()
        self.menus.setNativeMenuBar(False)
        self.menus.hide()
        row.addWidget(self.menus)
        row.addStretch(1)
        self.brand = QLabel("VISPA MP", self)
        self.brand.setObjectName("caption")
        self.brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.caption = "VISPA MP"
        self.controls = QWidget(self)
        self.controls.setObjectName("captionControls")
        controls = QHBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(0)
        row.addWidget(self.controls)
        for label, tip, callback in (
            (TITLEBAR_MINIMIZE, "Minimize", window.showMinimized),
            (TITLEBAR_MAXIMIZE, "Maximize", self.toggle_maximize),
            (TITLEBAR_CLOSE, "Close", window.close),
        ):
            button = TitlebarCloseButton() if label == TITLEBAR_CLOSE else QPushButton()
            button.setText(label)
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setProperty("chrome", True)
            button.setFixedSize(40 if label == TITLEBAR_CLOSE else 34, 30)
            button.setAutoDefault(False)
            button.clicked.connect(callback)
            controls.addWidget(button)
            if label == TITLEBAR_MINIMIZE:
                self.min_button = button
            if label == TITLEBAR_MAXIMIZE:
                self.max_button = button
            if label == TITLEBAR_CLOSE:
                self.close_button = button
                button.setObjectName("closeButton")
        self.sync_window_state()

    def sync_window_state(self):
        restore = self.owner.isMaximized() or self.owner.isFullScreen()
        self.max_button.setText(TITLEBAR_RESTORE if restore else TITLEBAR_MAXIMIZE)
        tip = "Restore" if restore else "Maximize"
        self.max_button.setToolTip(tip)
        self.max_button.setAccessibleName(tip)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout().activate()
        self.layout_caption()

    def set_caption(self, text):
        self.caption = text
        self.brand.setToolTip(text)
        self.layout_caption()

    def layout_caption(self):
        centre = self.width() // 2
        menu_edge = self.menus.geometry().right() + 8 if self.menus.actions() else 0
        symmetric_space = max(0, 2 * min(centre - menu_edge, self.controls.x() - centre - 8))
        width = min(
            self.brand.fontMetrics().horizontalAdvance(self.caption) + 20,
            max(0, self.width() - 240),
            symmetric_space,
        )
        self.brand.setText(self.brand.fontMetrics().elidedText(
            self.caption, Qt.TextElideMode.ElideRight, max(0, width - 16)))
        self.brand.setGeometry((self.width() - width) // 2, 0, width, self.height())
        self.brand.setVisible(width >= 20)
        self.brand.raise_()

    def draggable(self, point):
        if not self.rect().contains(point):
            return False
        child = self.childAt(point)
        while child and child is not self:
            if isinstance(child, (QAbstractButton, QMenuBar)):
                return False
            child = child.parentWidget()
        return True

    def toggle_maximize(self):
        if self.owner.isMaximized() or self.owner.isFullScreen():
            self.owner.showNormal()
        else:
            self.owner.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.draggable(event.position().toPoint()):
            handle = self.owner.windowHandle()
            if handle:
                handle.startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.draggable(event.position().toPoint()):
            self.toggle_maximize()
        super().mouseDoubleClickEvent(event)


class WindowChromeMixin:
    """Native resize and snap for a window whose caption is painted by TitleBar."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.titlebar = None
        self._native_frame_ready = False
        self._native_hwnd = None
        self._screen_window = None
        self._rounded_native = False
        self._desktop_screen = None
        if sys.platform == "win32":
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint)

    def showEvent(self, event):
        super().showEvent(event)
        self._prepare_native_frame()

    def _prepare_native_frame(self):
        if sys.platform != "win32":
            return
        if self._native_frame_ready and self._native_hwnd != int(self.winId()):
            self._native_frame_ready = False
        if not self._native_frame_ready:
            from PySide6.QtWidgets import QApplication
            if QApplication.platformName() != "windows":
                return
            import ctypes
            from ctypes import wintypes
            hwnd = wintypes.HWND(int(self.winId()))
            user32 = ctypes.windll.user32
            self._native_frame_ready = True
            self._native_hwnd = int(self.winId())
            self._add_native_frame(frame_changed=False)
            self._rounded_native = round_and_outline(self)
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0027)
            if self._screen_window is not self.windowHandle():
                self._screen_window = self.windowHandle()
                self._screen_window.screenChanged.connect(self._bound_to_screen)
        if self._native_frame_ready:
            self._ensure_native_frame()
            self._bound_to_screen(self.screen())

    def _ensure_native_frame(self, frame_changed=True):
        if sys.platform != "win32" or not self._native_frame_ready or not isValid(self):
            return False
        from PySide6.QtWidgets import QApplication
        if (not self.isVisible() or self.isFullScreen() or self.windowModality() != Qt.WindowModality.NonModal
                or QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None):
            return False
        if int(self.internalWinId() or 0) != self._native_hwnd:
            return False
        return self._add_native_frame(frame_changed)

    def _add_native_frame(self, frame_changed=True):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        get_style = user32.GetWindowLongPtrW
        get_style.restype = ctypes.c_ssize_t
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        set_style = user32.SetWindowLongPtrW
        set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        set_style.restype = ctypes.c_ssize_t
        hwnd = wintypes.HWND(self._native_hwnd)
        style = get_style(hwnd, -16)
        if style & NATIVE_FRAME == NATIVE_FRAME:
            return False
        set_style(hwnd, -16, style | NATIVE_FRAME)
        if frame_changed:
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0037)
        return True

    def _check_native_frame_later(self):
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self, self._ensure_native_frame)

    def _bound_to_screen(self, screen=None):
        if not isValid(self):
            return
        screen = screen or self.screen()
        if screen is None:
            return
        if screen is not self._desktop_screen:
            if self._desktop_screen is not None and isValid(self._desktop_screen):
                self._desktop_screen.availableGeometryChanged.disconnect(self._desktop_changed)
            self._desktop_screen = screen
            screen.availableGeometryChanged.connect(self._desktop_changed)
        area = screen.geometry() if self.isFullScreen() else screen.availableGeometry()
        self.setMaximumSize(area.size())

    def _desktop_changed(self, _rect):
        self._bound_to_screen(self._desktop_screen)

    def nativeEvent(self, event_type, message):
        if sys.platform != "win32":
            return super().nativeEvent(event_type, message)
        import ctypes
        from ctypes import wintypes
        msg = wintypes.MSG.from_address(int(message))
        user32 = ctypes.windll.user32
        hwnd = wintypes.HWND(msg.hWnd)
        if msg.message == 0x0046 and self._native_frame_ready:  # WM_WINDOWPOSCHANGING
            class WindowPos(ctypes.Structure):
                _fields_ = [("hwnd", wintypes.HWND), ("after", wintypes.HWND),
                            ("x", ctypes.c_int), ("y", ctypes.c_int),
                            ("cx", ctypes.c_int), ("cy", ctypes.c_int), ("flags", wintypes.UINT)]
            pos = WindowPos.from_address(msg.lParam)
            if not pos.flags & 0x0001:
                scale = self.devicePixelRatioF()
                limit_x = max(1, round(self.maximumWidth() * scale))
                limit_y = max(1, round(self.maximumHeight() * scale))
                corrected = False
                if pos.cx > limit_x:
                    pos.cx = max(1, min(round(self.width() * scale), limit_x))
                    corrected = True
                if pos.cy > limit_y:
                    pos.cy = max(1, min(round(self.height() * scale), limit_y))
                    corrected = True
                if corrected:
                    self._native_size_recoveries = getattr(self, "_native_size_recoveries", 0) + 1
                if (pos.cx >= round(self.minimumWidth() * scale)
                        and pos.cy >= round(self.minimumHeight() * scale)):
                    pos.flags |= 0x0100
                    return True, 0
        if msg.message == 0x0083 and msg.wParam:  # WM_NCCALCSIZE
            if user32.IsZoomed(hwnd):
                class MonitorInfo(ctypes.Structure):
                    _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                                ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
                user32.MonitorFromWindow.restype = wintypes.HANDLE
                info = MonitorInfo()
                info.size = ctypes.sizeof(info)
                monitor = user32.MonitorFromWindow(hwnd, 2)
                if user32.GetMonitorInfoW(wintypes.HANDLE(monitor), ctypes.byref(info)):
                    rect = wintypes.RECT.from_address(msg.lParam)
                    rect.left, rect.top = info.work.left, info.work.top
                    rect.right, rect.bottom = info.work.right, info.work.bottom
            return True, 0
        if msg.message == 0x007D and msg.wParam & 0xFFFFFFFF == 0xFFFFFFF0 and self.isVisible():
            self._check_native_frame_later()
        if msg.message == 0x0084 and self.titlebar:  # WM_NCHITTEST
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            x = ctypes.c_short(msg.lParam & 0xffff).value - rect.left
            y = ctypes.c_short((msg.lParam >> 16) & 0xffff).value - rect.top
            scale = self.devicePixelRatioF()
            width, height = rect.right - rect.left, rect.bottom - rect.top
            edge = round(6 * scale)
            if not self.isMaximized():
                left, right, top, bottom = x < edge, x >= width - edge, y < edge, y >= height - edge
                hit = (13 if left else 14 if right else 12) if top else (
                    (16 if left else 17 if right else 15) if bottom else (10 if left else 11 if right else 0))
                if hit:
                    return True, hit
            point = self.titlebar.mapFrom(self, QPoint(round(x / scale), round(y / scale)))
            return True, 2 if self.titlebar.draggable(point) else 1
        return super().nativeEvent(event_type, message)

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() in (QEvent.Type.ActivationChange, QEvent.Type.WindowStateChange)
                and self._native_frame_ready and self.isVisible()):
            self._check_native_frame_later()
        if getattr(self, "titlebar", None):
            self.titlebar.sync_window_state()


class DialogTitleBar(QFrame):
    """The same 30 px caption for a dialog: its title and a close button. Dragging moves it."""

    def __init__(self, dialog, title):
        super().__init__(dialog)
        self.owner = dialog
        self.setObjectName("titlebar")
        self.setFixedHeight(30)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addSpacing(40)
        self.brand = QLabel(title, self)
        self.brand.setObjectName("caption")
        self.brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self.brand, 1)
        self.close_button = TitlebarCloseButton()
        self.close_button.setText(TITLEBAR_CLOSE)
        self.close_button.setToolTip("Close")
        self.close_button.setAccessibleName("Close")
        self.close_button.setObjectName("closeButton")
        self.close_button.setProperty("chrome", True)
        self.close_button.setFixedSize(40, 30)
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(dialog.close)
        row.addWidget(self.close_button)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.childAt(event.position().toPoint()) is not self.close_button:
            handle = self.owner.windowHandle()
            if handle:
                handle.startSystemMove()
        super().mousePressEvent(event)


class ChromeDialog(QDialog):
    """A dialog with VISPA's caption instead of the Windows one. Content goes in ``body``."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.setObjectName("chromeDialog")
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)  # the inner pixel of the outline
        outer.setSpacing(0)
        self.titlebar = DialogTitleBar(self, title)
        outer.addWidget(self.titlebar)
        self.body = QWidget(self)
        self.body.setObjectName("dialogBody")
        outer.addWidget(self.body, 1)

    def showEvent(self, event):
        super().showEvent(event)
        round_and_outline(self)

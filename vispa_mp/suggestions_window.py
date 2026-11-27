"""A floating host for the review's existing suggestions panel."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow

from vispa_mp.window_chrome import TitleBar, WindowChromeMixin


class SuggestionsWindow(WindowChromeMixin, QMainWindow):
    """Move the live panel between windows without duplicating its review state.

    The review owner controls the panel and its docking. This host only handles
    its own window and forwards the familiar suggestion shortcuts; it never
    opens a Resolve connection or reads or writes preferences.
    """

    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Window)
        self.owner = owner
        self._was_maximized_before_fullscreen = False
        self._docking_on_close = False
        self.setObjectName("mainWindow")
        self.setStyleSheet(owner.styleSheet())
        self.resize(1100, 650)
        self.setMinimumSize(440, 260)
        self.setWindowTitle("Suggestions — VISPA MP")
        self.titlebar = TitleBar(self)
        self.titlebar.set_caption(self.windowTitle())
        self.titlebar.close_button.setToolTip("Dock suggestions back in the main window")
        self.titlebar.close_button.setAccessibleName("Dock suggestions")
        self.setMenuWidget(self.titlebar)
        # The same review history works on whichever review window is active.
        self.addAction(owner.undo_action)
        self.addAction(owner.redo_action)

        for key, callback in (
                (Qt.Key.Key_F11, self.toggle_fullscreen),
                (Qt.Key.Key_Escape, self._escape),
                (Qt.Key.Key_Left, lambda: self._owner_action("_browse_suggestion", -1)),
                (Qt.Key.Key_Right, lambda: self._owner_action("_browse_suggestion", 1)),
                (Qt.Key.Key_Return, lambda: self._owner_action("_keep_preview")),
                (Qt.Key.Key_Enter, lambda: self._owner_action("_keep_preview"))):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(callback)

    def set_selection_caption(self, text):
        title = "Suggestions — " + str(text) if text else "Suggestions — VISPA MP"
        self.setWindowTitle(title)
        self.titlebar.set_caption(title)

    def _owner_action(self, method, *args):
        if (getattr(self.owner, "worker", None) is not None
                or getattr(self.owner, "_learning_job_busy", False)):
            return
        getattr(self.owner, method)(*args)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self._leave_fullscreen()
        else:
            self._was_maximized_before_fullscreen = self.isMaximized()
            self.showFullScreen()

    def _leave_fullscreen(self):
        if self._was_maximized_before_fullscreen:
            self.showMaximized()
        else:
            self.showNormal()

    def _escape(self):
        if self.isFullScreen():
            self._leave_fullscreen()
        else:
            self._owner_action("_cancel_preview")

    def closeEvent(self, event):
        if getattr(self.owner, "_closing_suggestions", False) or self._docking_on_close:
            event.accept()
            return
        self._docking_on_close = True
        try:
            if self.isFullScreen():
                self._leave_fullscreen()
            self.owner._dock_suggestions()
        finally:
            self._docking_on_close = False
        event.accept()

"""A permanent, compact pair of Resolve project and timeline names."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QLabel, QSizePolicy


class ResolveSourceLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.set_source("", "")

    def set_source(self, project, timeline):
        def name(value):
            return " ".join(value.split()) if isinstance(value, str) and value.strip() else "unknown"
        self._lines = (f"Project: {name(project)}", f"Timeline: {name(timeline)}")
        full = "\n".join(self._lines)
        self.setText(full)
        self.setAccessibleName(full)
        self.setToolTip(full + "\n\nSource of the displayed preparation. Use Read timeline to refresh from Resolve.")
        self.update()

    def sizeHint(self):
        return QSize(320, self.fontMetrics().height() * 2)

    def minimumSizeHint(self):
        return QSize(0, self.fontMetrics().height() * 2)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        metrics = self.fontMetrics()
        rect = self.contentsRect()
        top = rect.y() + max(0, (rect.height() - 2 * metrics.height()) // 2)
        for index, line in enumerate(self._lines):
            text = metrics.elidedText(line, Qt.TextElideMode.ElideRight, max(0, rect.width()))
            painter.drawText(QRect(rect.x(), top + index * metrics.height(), rect.width(), metrics.height()),
                             Qt.AlignmentFlag.AlignCenter, text)

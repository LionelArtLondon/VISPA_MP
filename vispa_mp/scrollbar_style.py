"""VISPA's line-and-capsule scrollbar design on native Qt scroll controls.

Visual reference: VISPA ui/widgets/scrollbar.py (VispaQtScrollBar).
Keep QScrollBar itself for wheel, keyboard, page stepping and accessibility.
"""
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication, QAbstractScrollArea, QProxyStyle, QScrollBar, QStyle, QWidget
from shiboken6 import isValid


class VispaScrollBarStyle(QProxyStyle):
    """Apply the same scrollbar geometry and painting to every Qt widget."""

    @staticmethod
    def background_brush(option, widget):
        # Qt puts bars inside private container widgets. Use the owning
        # viewport, whose palette includes the resolved stylesheet background,
        # rather than those containers or a single app-wide surface colour.
        owner = widget
        while owner is not None:
            if isinstance(owner, QAbstractScrollArea):
                viewport = owner.viewport()
                return viewport.palette().brush(viewport.backgroundRole())
            owner = owner.parentWidget()
        parent = widget.parentWidget() if widget else None
        surface = parent or widget
        return (surface.palette().brush(surface.backgroundRole()) if surface else
                option.palette.window())

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_PanelScrollAreaCorner:
            painter.fillRect(option.rect, self.background_brush(option, widget))
            return
        super().drawPrimitive(element, option, painter, widget)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PixelMetric.PM_ScrollBarExtent:
            return 16
        if metric == QStyle.PixelMetric.PM_ScrollBarSliderMin:
            return 26
        return super().pixelMetric(metric, option, widget)

    def polish(self, target):
        # After hundreds of windows, PySide may hand over a stale wrapper (seen as a QWidgetItem, 13 Nov 2026):
        # nothing to polish then, rather than an error through every event filter.
        if not isinstance(target, (QWidget, QApplication, QPalette)):
            return
        super().polish(target)
        if isinstance(target, QScrollBar):
            target.setAttribute(Qt.WidgetAttribute.WA_Hover)
            target.setCursor(Qt.CursorShape.PointingHandCursor)

    def subControlRect(self, control, option, sub_control, widget=None):
        if control != QStyle.ComplexControl.CC_ScrollBar:
            return super().subControlRect(control, option, sub_control, widget)
        sc = QStyle.SubControl
        horizontal = option.orientation == Qt.Orientation.Horizontal
        rect = option.rect
        length = rect.width() if horizontal else rect.height()
        margin = min(6, length // 2)
        available = max(0, length - 2 * margin)
        thumb = min(26, available)
        travel = available - thumb
        upside_down = option.upsideDown ^ (
            horizontal and option.direction == Qt.LayoutDirection.RightToLeft)
        position = QStyle.sliderPositionFromValue(
            option.minimum, option.maximum, option.sliderPosition,
            travel, upside_down,
        )

        def segment(start, size):
            if horizontal:
                return QRect(rect.x() + start, rect.y(), size, rect.height())
            return QRect(rect.x(), rect.y() + start, rect.width(), size)

        if sub_control == sc.SC_ScrollBarGroove:
            return segment(margin, available)
        if sub_control == sc.SC_ScrollBarSlider:
            return segment(margin + position, thumb)
        # Include the end gutters in the native page-click targets.
        before = segment(0, margin + position)
        after_start = margin + position + thumb
        after = segment(after_start, length - after_start)
        if sub_control == sc.SC_ScrollBarSubPage:
            return after if upside_down else before
        if sub_control == sc.SC_ScrollBarAddPage:
            return before if upside_down else after
        return QRect()  # No arrow buttons.

    def hitTestComplexControl(self, control, option, point, widget=None):
        if control != QStyle.ComplexControl.CC_ScrollBar:
            return super().hitTestComplexControl(control, option, point, widget)
        for part in (QStyle.SubControl.SC_ScrollBarSlider,
                     QStyle.SubControl.SC_ScrollBarSubPage,
                     QStyle.SubControl.SC_ScrollBarAddPage):
            if self.subControlRect(control, option, part, widget).contains(point):
                return part
        return QStyle.SubControl.SC_None

    def drawComplexControl(self, control, option, painter, widget=None):
        if control != QStyle.ComplexControl.CC_ScrollBar:
            return super().drawComplexControl(control, option, painter, widget)
        horizontal = option.orientation == Qt.Orientation.Horizontal
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        active = enabled and bool(option.state & (
            QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Sunken))
        groove = self.subControlRect(
            control, option, QStyle.SubControl.SC_ScrollBarGroove, widget)
        thumb = self.subControlRect(
            control, option, QStyle.SubControl.SC_ScrollBarSlider, widget)
        painter.save()
        painter.fillRect(option.rect, self.background_brush(option, widget))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(QColor("#ffffff" if active else "#878787"), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        center = option.rect.center()
        if not groove.isEmpty():
            if horizontal:
                painter.drawLine(groove.left(), center.y(), groove.right(), center.y())
            else:
                painter.drawLine(center.x(), groove.top(), center.x(), groove.bottom())
        if enabled and option.maximum > option.minimum and not thumb.isEmpty():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pen = QPen(QColor("#00e5ff" if active else "#239ba8"), 9,
                       Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            pen.setCosmetic(True)
            painter.setPen(pen)
            inset = min(3, (thumb.width() if horizontal else thumb.height()) // 2)
            if horizontal:
                painter.drawLine(thumb.left() + inset, center.y(),
                                 thumb.right() - inset, center.y())
            else:
                painter.drawLine(center.x(), thumb.top() + inset,
                                 center.x(), thumb.bottom() - inset)
        painter.restore()


def install_scrollbar_style(app: QApplication) -> None:
    """Install once, before creating windows; later dialogs inherit it too."""
    # A stylesheet wraps app.style() in QStyleSheetStyle. Remember the owned
    # underlying proxy instead of repeatedly resetting every live widget's style.
    installed = getattr(app, '_vispa_scrollbar_style', None)
    if installed is not None and isValid(installed):
        return
    installed = app.style()
    if not isinstance(installed, VispaScrollBarStyle):
        installed = VispaScrollBarStyle(installed.objectName())
        app.setStyle(installed)
    app._vispa_scrollbar_style = installed

"""Small counters for the panels actually displayed in a review canvas."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from vispa_mp.markers import CORE, EXTRA, PAGE
from vispa_mp.ui_tokens import BORDER_ROW, TEXT_MAIN, TEXT_MUTED, px


def _role_counts(items):
    core = extras = starts = manual = 0
    for item in items:
        if item.get("manual"):
            manual += 1
            continue
        color = (item.get("proposal") or {}).get("color")
        core += color in (PAGE, CORE)
        starts += color == PAGE
        extras += color == EXTRA
    return core, extras, starts, manual


class PanelCounter(QWidget):
    """A mouse-transparent overlay; it does not participate in canvas layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("reviewPanelCounter")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("Panel counts")
        self.setStyleSheet(
            "QWidget#reviewPanelCounter { background: rgba(8, 24, 32, 220); "
            f"border: 1px solid {BORDER_ROW}; border-radius: 5px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(px(10), px(6), px(10), px(6))
        row.setSpacing(px(8))
        self.primary = QLabel(self)
        self.secondary = QLabel(self)
        for label, size, color, weight in ((self.primary, 24, TEXT_MAIN, 600),
                                           (self.secondary, 12, TEXT_MUTED, 400)):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            label.setStyleSheet(f"background: transparent; border: none; color: {color}; "
                                f"font-size: {px(size)}px; font-weight: {weight};")
            row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._counts_state = None
        self.update_counts([], [], "all")

    def update_counts(self, items, all_items, view_filter):
        """Update both totals from one consistent snapshot of the displayed page.

        For Page starts, ``all_items`` is the whole chapter rather than a page.
        Manual Resolve markers count in All but have no inferred Core/Extra role.
        """
        displayed = list(items or [])
        available = list(all_items or [])
        count, total = len(displayed), len(available)
        core, extras, starts, manual = _role_counts(available)
        if view_filter == "core":
            primary, secondary = f"{count} Core", f"{total} incl. Extras"
        elif view_filter == "starts":
            primary, secondary = f"{count} Page starts", f"{core} Core"
        else:
            primary, secondary = f"{count} panels", f"{core} Core"
        tooltip = (f"Displayed: {count}\nAll panels: {total}\n"
                   f"Core (including Page starts): {core}\nPage starts: {starts}\n"
                   f"Extras: {extras}\nManual Resolve markers: {manual}\n"
                   "Manual markers are included in All; no Core/Extra role is inferred.")
        state = primary, secondary, tooltip
        if state == self._counts_state:
            return
        self._counts_state = state
        updating = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        try:
            self.primary.setText(primary)
            self.secondary.setText(secondary)
            for widget in (self, self.primary, self.secondary):
                widget.setToolTip(tooltip)
            self.setAccessibleDescription(tooltip)
            self.adjustSize()
        finally:
            self.setUpdatesEnabled(updating)

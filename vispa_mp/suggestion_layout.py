"""Fit a chronological set of suggestions into a chosen number of rows."""

from math import ceil, floor

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLayout, QSizePolicy


def fit_geometry(count, rows, width, height, ratio, text_height):
    rows = min(max(1, rows), max(1, count))
    columns = max(1, ceil(count / rows))
    gap = min(8, max(0, (width - columns * 12) // max(1, columns - 1)),
              max(0, (height - rows * 12) // max(1, rows - 1)))
    cell_width = max(1, (width - gap * (columns - 1)) // columns)
    cell_height = max(1, (height - gap * (rows - 1)) // rows)
    # Allow compact cells in a low docked pane, instead of enforcing the old
    # one-strip image minimum and silently cutting off the requested rows.
    padding = min(18, max(6, min(cell_width, cell_height) // 3))
    margin = max(0, (padding - 6) // 2)
    caption = cell_height - padding - text_height - 2 >= 24
    image_height = max(1, cell_height - padding - (text_height + 2 if caption else 0))
    image_width = max(1, cell_width - padding)
    if image_width / ratio <= image_height:
        image_height = max(1, floor(image_width / ratio))
    else:
        image_width = max(1, floor(image_height * ratio))
    card_width = image_width + padding
    card_height = image_height + padding + (text_height + 2 if caption else 0)
    # Balanced rows honour the selected number even for 4 images / 3 rows.
    base, remainder = divmod(count, rows)
    positions = [(row, column) for row in range(rows)
                 for column in range(base + int(row < remainder))]
    return image_width, image_height, card_width, card_height, caption, margin, gap, positions


class SuggestionsLayoutMixin:
    def _set_suggestions_rows(self, rows):
        if (isinstance(rows, bool) or not isinstance(rows, int) or not 0 <= rows <= 6
                or rows == self.suggestions_rows):
            return
        self.suggestions_rows = rows
        self._sync_suggestions_rows_control()
        self._resize_suggestions()
        self._mark_project_dirty()
        self._schedule_save()

    def _sync_suggestions_rows_control(self):
        box = getattr(self, "suggestions_rows_box", None)
        if box is not None:
            blocked = box.blockSignals(True)
            box.setCurrentIndex(max(0, box.findData(self.suggestions_rows)))
            box.blockSignals(blocked)

    def _arrange_suggestion_cards(self, cards, positions):
        layout = self.suggestion_layout
        wanted = tuple((number, position) for number, position in zip(cards, positions))
        if wanted == getattr(self, "_suggestion_grid_positions", None):
            return
        while layout.count():
            layout.takeAt(0)  # Keep the widgets alive, including selected cards.
        for row in range(layout.rowCount()):
            layout.setRowStretch(row, 0)
            layout.setRowMinimumHeight(row, 0)
        for column in range(layout.columnCount()):
            layout.setColumnStretch(column, 0)
            layout.setColumnMinimumWidth(column, 0)
        for card, (row, column) in zip(cards.values(), positions):
            layout.addWidget(card, row, column)
        self._suggestion_grid_positions = wanted

    def _resize_suggestion_cards(self):
        area = getattr(self, "suggestion_area", None)
        cards = getattr(self, "_suggestion_cards", {})
        if area is None or area.isHidden():
            return
        fitted = self.suggestions_rows > 0
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if fitted else
                                          Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host, layout = area.widget(), self.suggestion_layout
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint if fitted else
                                 QLayout.SizeConstraint.SetMinimumSize)
        host.setSizePolicy(QSizePolicy.Policy.Ignored if fitted else QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Ignored if fitted else QSizePolicy.Policy.Preferred)
        if fitted:
            host.setMinimumSize(0, 0)
            area.horizontalScrollBar().setValue(0)
            area.verticalScrollBar().setValue(0)
        if not cards:
            return
        width, height = max(1, area.viewport().width()), max(1, area.viewport().height())
        text_height = max(20, max(card._suggestion_label.fontMetrics().height() + 4 for card in cards.values()))
        if fitted:
            image_width, image_height, card_width, card_height, caption, margin, gap, positions = fit_geometry(
                len(cards), self.suggestions_rows, width, height, self._preview_ratio(), text_height)
        else:
            bar = max(16, area.horizontalScrollBar().sizeHint().height())
            available = max(72, area.height() - 2 * area.frameWidth() - bar - 2)
            image_height = max(40, available - text_height - 14)
            image_width = max(1, round(image_height * self._preview_ratio()))
            if image_width > width - 12:
                image_width = max(1, width - 12)
                image_height = max(1, round(image_width / self._preview_ratio()))
            card_width, card_height = image_width + 12, image_height + text_height + 14
            caption, margin, gap = True, 6, 8
            positions = [(0, index) for index in range(len(cards))]
        layout.setSpacing(gap)
        self._arrange_suggestion_cards(cards, positions)
        for card in cards.values():
            card.layout().setContentsMargins(margin, margin, margin, margin)
            card.setFixedSize(card_width, card_height)
            picture, label = card._suggestion_picture, card._suggestion_label
            picture.setFixedSize(image_width, image_height)
            label.setVisible(caption)
            label.setFixedHeight(text_height)
        layout.invalidate()
        layout.activate()
        if fitted:
            # Old scroll-strip minimums must not survive a switch to Fit mode.
            host.setMinimumSize(0, 0)
            host.resize(area.viewport().size())

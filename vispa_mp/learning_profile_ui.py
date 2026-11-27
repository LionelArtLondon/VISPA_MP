"""Visible selection-profile controls shared by the review and Settings."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from vispa_mp.ui_tokens import (
    ACCENT, BAR_BG, BORDER_ROW, TEXT_MAIN, TEXT_MUTED, TEXT_SECONDARY, TEXT_TITLE, px,
)


class _SidebarDetailLabel(QLabel):
    """Keep the existing owner's status updates visible when action is needed."""

    def __init__(self, panel, text):
        super().__init__(text, panel)
        self._panel = panel

    def setText(self, text):
        super().setText(text)
        self._panel._sync_sidebar_detail()


class LearningProfilePanel(QFrame):
    """A profile picker whose actual state is always supplied by the owner.

    Choosing or loading a profile is deliberately separate from applying it.
    Both copies of this panel are synchronized by LearningReviewMixin, so a
    highlighted combo choice can never stand in for the active-profile label.
    """

    def __init__(self, owner, compact=False, sidebar=False):
        super().__init__(owner)
        self.compact = compact
        self.sidebar = sidebar
        self._owner = owner
        self._sidebar_expanded = False
        self.setObjectName("selectionProfilePanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.setStyleSheet(f"""
            QFrame#selectionProfilePanel {{ background: {BAR_BG};
                border: 0; border-bottom: 1px solid {BORDER_ROW}; }}
            QFrame#selectionProfilePanel QLabel[profileRole="title"] {{
                color: {TEXT_MUTED}; font-size: {TEXT_TITLE}px; font-weight: 600; }}
            QFrame#selectionProfilePanel QLabel[profileRole="active"] {{
                color: {ACCENT}; font-weight: 600; }}
            QFrame#selectionProfilePanel QLabel[profileRole="detail"] {{
                color: {TEXT_MUTED}; font-size: {TEXT_SECONDARY}px; }}
            QFrame#selectionProfilePanel QLabel[profileRole="explanation"] {{
                color: {TEXT_MAIN}; }}
        """)
        column = QVBoxLayout(self)
        column.setContentsMargins(px(12), px(7 if compact else 16), px(12), px(8 if compact else 16))
        column.setSpacing(px(5 if compact else 12))

        title = QLabel("Selection profile")
        title.setProperty("profileRole", "title")
        self.active = QLabel("Active: MP standard rules")
        self.active.setProperty("profileRole", "active")
        self.active.setWordWrap(True)
        self.active.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.active.setMinimumWidth(px(170) if compact else 0)

        self.profiles = QComboBox()
        self.profiles.setAccessibleName("Selection profile to use")
        self.profiles.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.profiles.setMinimumContentsLength(18)
        self.profiles.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.profiles.addItem("MP standard rules", "")
        self.profiles.setToolTip("Choose MP standard rules or a personal profile, then click Use selection.")
        self.profiles.currentIndexChanged.connect(lambda _index: owner._selection_profile_chosen(self))

        self.apply = QPushButton("Use selection")
        self.apply.setProperty("primary", True)
        self.apply.setEnabled(False)
        self.apply.setToolTip("Apply this choice to the current marker selection and future analyses.")
        self.apply.clicked.connect(lambda: owner._apply_selection_profile(self))
        self.load = QPushButton("Load profile…")
        self.load.setToolTip("Load a trained profile from a JSON file, then choose Use selection to activate it.")
        self.load.clicked.connect(lambda: owner._load_selection_profile(self))
        self.manage = QPushButton("Manage learning…")
        self.manage.setToolTip("Import references, train profiles and inspect their validation reports.")
        self.manage.clicked.connect(owner._show_learning)
        self.compare = QPushButton("Compare")
        self.compare.setToolTip("Compare this personal profile with MP standard rules in two read-only windows.")
        self.compare.clicked.connect(lambda: owner._show_profile_comparison(self))

        self.detail = (_SidebarDetailLabel(self, "MP standard rules are in use.") if sidebar else
                       QLabel("MP standard rules are in use."))
        self.detail.setProperty("profileRole", "detail")
        self.detail.setWordWrap(True)

        if sidebar:
            self.active.setMinimumWidth(0)
            active_policy = self.active.sizePolicy()
            active_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            self.active.setSizePolicy(active_policy)
            self.profiles.setMinimumContentsLength(1)
            self.profiles.setMinimumWidth(0)
            self.sidebar_toggle = QToolButton()
            self.sidebar_toggle.setCheckable(True)
            self.sidebar_toggle.setArrowType(Qt.ArrowType.DownArrow)
            self.sidebar_toggle.setFixedSize(px(24), px(24))
            self.sidebar_toggle.setStyleSheet(f"QToolButton {{ padding: 0; min-width: {px(22)}px; "
                                             f"max-width: {px(22)}px; min-height: {px(22)}px; "
                                             f"max-height: {px(22)}px; }}")
            self.sidebar_toggle.setAccessibleName("Show selection profile choices")
            self.sidebar_toggle.setToolTip("Choose profile…")
            self.sidebar_toggle.toggled.connect(self._set_sidebar_expanded)
            heading = QHBoxLayout()
            heading.setSpacing(px(6))
            heading.addWidget(title, 1)
            heading.addWidget(self.sidebar_toggle)
            column.addLayout(heading)
            column.addWidget(self.active)
            column.addWidget(self.detail)
            self.sidebar_controls = QWidget(self)
            choices = QVBoxLayout(self.sidebar_controls)
            choices.setContentsMargins(0, 0, 0, 0)
            choices.setSpacing(px(6))
            choices.addWidget(self.profiles)
            for button in (self.apply, self.load, self.manage, self.compare):
                choices.addWidget(button)
            column.addWidget(self.sidebar_controls)
            self.sidebar_controls.hide()
            self._sync_sidebar_detail()
        elif compact:
            row = QHBoxLayout()
            row.setSpacing(px(10))
            row.addWidget(title)
            row.addWidget(self.active, 1)
            self.profiles.setMaximumWidth(px(340))
            row.addWidget(self.profiles, 1)
            row.addWidget(self.apply)
            row.addWidget(self.load)
            row.addWidget(self.manage)
            row.addWidget(self.compare)
            column.addLayout(row)
            column.addWidget(self.detail)
        else:
            column.addWidget(title)
            column.addWidget(self.active)
            explanation = QLabel(
                "A personal profile ranks admissible Core, Extra and page-start images using your reviewed references. "
                "Your filters, marker and page limits, and manual edits remain in effect. "
                "Learned preferences take priority over standard visual ranking. "
                "Switching back to MP standard rules keeps your current settings."
            )
            explanation.setProperty("profileRole", "explanation")
            explanation.setWordWrap(True)
            column.addWidget(explanation)
            picker_label = QLabel("Profile to use")
            picker_label.setBuddy(self.profiles)
            column.addWidget(picker_label)
            column.addWidget(self.profiles)
            column.addWidget(self.detail)
            actions = QHBoxLayout()
            actions.setSpacing(px(6))
            actions.addWidget(self.apply)
            actions.addWidget(self.load)
            actions.addWidget(self.compare)
            actions.addStretch(1)
            column.addLayout(actions)
            column.addWidget(self.manage, alignment=Qt.AlignmentFlag.AlignLeft)
        self.controls = (self.profiles, self.apply, self.load, self.manage, self.compare)
        if sidebar:
            self.controls += (self.sidebar_toggle,)

    def _set_sidebar_expanded(self, expanded):
        self._sidebar_expanded = bool(expanded)
        self.sidebar_controls.setVisible(self._sidebar_expanded)
        self.sidebar_toggle.setArrowType(Qt.ArrowType.UpArrow if expanded else Qt.ArrowType.DownArrow)
        self.sidebar_toggle.setAccessibleName("Hide selection profile choices" if expanded else
                                             "Show selection profile choices")
        self.sidebar_toggle.setToolTip("Hide profile choices and actions" if expanded else "Choose profile…")
        self._sync_sidebar_detail()

    def _sync_sidebar_detail(self):
        pending = self.profiles.currentData() != self._owner._active_selection_profile_key()
        self.detail.setVisible(self._sidebar_expanded or pending)

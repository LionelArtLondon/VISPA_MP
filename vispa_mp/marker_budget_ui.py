"""Edit a whole-analysis marker budget without rerunning image analysis."""

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QGridLayout, QLabel, QSpinBox, QVBoxLayout, QWidget,
)


_BOUNDS = ("min", "target", "max")
_ENABLED = "global_markers_enabled"
_AUTOMATIC = "global_markers_auto"
_RATE_KEYS = {bound: f"global_markers_per_min_{bound}" for bound in _BOUNDS}
_TOTAL_KEYS = {bound: f"global_markers_{bound}" for bound in _BOUNDS}


def _duration_text(seconds):
    seconds = max(0, round(float(seconds or 0)))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes} min {seconds:02d} s" if minutes else f"{seconds} s"


class MarkerBudgetMixin:
    def _build_marker_budget_settings(self, form, values):
        from vispa_mp.marker_budget import BUDGET_DEFAULTS, MAX_MARKERS
        section = QWidget()
        column = QVBoxLayout(section)
        column.setContentsMargins(0, 12, 0, 0)
        column.setSpacing(8)
        heading = QLabel("Global markers")
        heading.setProperty("role", "section")
        column.addWidget(heading)
        self.marker_budget_enabled = QCheckBox("Use a global marker budget")
        self.marker_budget_enabled.setChecked(bool(values.get(_ENABLED, BUDGET_DEFAULTS[_ENABLED])))
        self.widgets[_ENABLED] = self.marker_budget_enabled
        column.addWidget(self.marker_budget_enabled)
        self.marker_budget_automatic = QCheckBox("Automatic totals from duration")
        self.marker_budget_automatic.setChecked(bool(values.get(_AUTOMATIC, BUDGET_DEFAULTS[_AUTOMATIC])))
        self.widgets[_AUTOMATIC] = self.marker_budget_automatic
        column.addWidget(self.marker_budget_automatic)
        self.marker_budget_help = QLabel("A flexible budget for the whole analyzed duration, not a quota for each minute. Page starts, Core and Extras count once per image.")
        self.marker_budget_help.setWordWrap(True)
        self.marker_budget_help.setProperty("role", "muted")
        column.addWidget(self.marker_budget_help)
        fields = QGridLayout()
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setHorizontalSpacing(8)
        fields.setVerticalSpacing(6)
        self.marker_budget_rates = {}
        self.marker_budget_totals = {}
        for index, (bound, label) in enumerate(zip(_BOUNDS, ("Minimum", "Target", "Maximum")), 1):
            title = QLabel(label)
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fields.addWidget(title, 0, index)
            rate = QDoubleSpinBox()
            rate.setRange(0, MAX_MARKERS)
            rate.setDecimals(1)
            rate.setSingleStep(1)
            rate.setFixedWidth(94)
            rate.setValue(float(values.get(_RATE_KEYS[bound], BUDGET_DEFAULTS[_RATE_KEYS[bound]])))
            rate.setToolTip(f"{label} number of markers per minute of analyzed video.")
            rate.setAccessibleName(f"Global markers {label.lower()} per minute")
            self.widgets[_RATE_KEYS[bound]] = rate
            self.marker_budget_rates[bound] = rate
            fields.addWidget(rate, 1, index)
            total = QSpinBox()
            total.setRange(0, MAX_MARKERS)
            total.setFixedWidth(94)
            total.setAccessibleName(f"Global markers {label.lower()} total")
            total.setToolTip("Calculated from the analyzed duration in automatic mode. Turn automatic mode off to edit totals.")
            self.marker_budget_totals[bound] = total
            fields.addWidget(total, 2, index)
            # Persist only the manual total. The visible spin shows the current
            # automatic calculation without changing a portable project's values.
            manual = QSpinBox(section)
            manual.setRange(0, MAX_MARKERS)
            manual.setValue(int(values.get(_TOTAL_KEYS[bound], BUDGET_DEFAULTS[_TOTAL_KEYS[bound]])))
            manual.hide()
            self.widgets[_TOTAL_KEYS[bound]] = manual
        fields.addWidget(QLabel("Per min"), 1, 0)
        fields.addWidget(QLabel("Total"), 2, 0)
        fields.setColumnStretch(0, 1)
        column.addLayout(fields)
        self.marker_budget_settings_summary = QLabel("")
        self.marker_budget_settings_summary.setWordWrap(True)
        self.marker_budget_settings_summary.setProperty("role", "muted")
        column.addWidget(self.marker_budget_settings_summary)
        form.addRow(section)
        self.marker_budget_section = section
        self._settings_row(form, "compression", values)
        for bound in _BOUNDS:
            self.marker_budget_rates[bound].valueChanged.connect(self._marker_budget_setting_changed)
            self.widgets[_TOTAL_KEYS[bound]].valueChanged.connect(self._marker_budget_setting_changed)
            self.marker_budget_totals[bound].valueChanged.connect(
                lambda value, role=bound: self._marker_budget_total_edited(role, value))
        self.marker_budget_enabled.toggled.connect(self._marker_budget_setting_changed)
        self.marker_budget_automatic.toggled.connect(self._marker_budget_automatic_toggled)
        self._refresh_marker_budget_settings()
        return section

    def _marker_budget_analysis(self):
        provider = getattr(self, "_budget_analysis", None)
        return provider() if callable(provider) else getattr(self, "analysis", None)

    def _marker_budget_setting_changed(self, *_args):
        if not getattr(self, "_ready", False):
            return
        self._sync_marker_budget_compression(clamp_target=getattr(self, "_ready", False))
        self._refresh_marker_budget_settings()
        self._changed()

    def _sync_marker_budget_compression(self, *, clamp_target=False):
        if not hasattr(self, "compression") or not self.marker_budget_enabled.isChecked():
            return
        from vispa_mp.marker_budget import compression_for_band
        keys = _RATE_KEYS if self.marker_budget_automatic.isChecked() else _TOTAL_KEYS
        low, target, high = (self.widgets[keys[bound]].value() for bound in _BOUNDS)
        if clamp_target:
            limited = max(min(low, high), min(max(low, high), target))
            if limited != target:
                widget = self.widgets[keys["target"]]
                blocker = QSignalBlocker(widget)
                widget.setValue(limited)
                del blocker
                target = widget.value()
        reference = self._marker_budget_reference_band()
        if reference is None:
            return
        position = compression_for_band((low, target, high), reference)
        blocker = QSignalBlocker(self.compression)
        self.compression.setValue(round(100 * position))
        del blocker
        if hasattr(self, "compression_percent"):
            self.compression_percent.setText(f"{self.compression.value()}%")

    def _marker_budget_compression_changed(self, *_args):
        if not getattr(self, "_ready", False):
            return
        if self.marker_budget_enabled.isChecked():
            from vispa_mp.marker_budget import band_for_compression
            automatic = self.marker_budget_automatic.isChecked()
            keys = _RATE_KEYS if automatic else _TOTAL_KEYS
            reference = self._marker_budget_reference_band()
            if reference is not None:
                band = band_for_compression([self.widgets[keys[bound]].value() for bound in _BOUNDS],
                                            self.compression.value() / 100, reference, integer=not automatic)
                for bound, value in zip(_BOUNDS, band):
                    widget = self.widgets[keys[bound]]
                    blocker = QSignalBlocker(widget)
                    widget.setValue(value)
                    del blocker
        self._refresh_marker_budget_settings()
        self._changed()

    def _marker_budget_reference_band(self):
        from vispa_mp.marker_budget import BUDGET_DEFAULTS, REFERENCE_RATES, budget_settings
        if self.marker_budget_automatic.isChecked():
            return REFERENCE_RATES
        reference = budget_settings(BUDGET_DEFAULTS, self._marker_budget_analysis())
        return tuple(reference[bound] for bound in _BOUNDS) if reference["seconds"] else None

    def _marker_budget_total_edited(self, bound, value):
        if self.marker_budget_automatic.isChecked():
            return
        self.widgets[_TOTAL_KEYS[bound]].setValue(value)

    def _marker_budget_automatic_toggled(self, automatic):
        # This initialization belongs only to an explicit user change. Settings
        # restore runs while _ready is false and must preserve saved zeroes too.
        if (not automatic and getattr(self, "_ready", False)
                and all(self.widgets[_TOTAL_KEYS[bound]].value() == 0 for bound in _BOUNDS)):
            from vispa_mp.marker_budget import budget_settings
            settings = dict(self.settings(), **{_AUTOMATIC: True})
            budget = budget_settings(settings, self._marker_budget_analysis())
            for bound in _BOUNDS:
                manual = self.widgets[_TOTAL_KEYS[bound]]
                blocker = QSignalBlocker(manual)
                manual.setValue(budget[bound])
                del blocker
        self._marker_budget_setting_changed()

    def _refresh_marker_budget_settings(self):
        if not hasattr(self, "marker_budget_totals"):
            return
        from vispa_mp.marker_budget import budget_settings
        self._sync_marker_budget_compression()
        settings = self.settings()
        budget = budget_settings(settings, self._marker_budget_analysis())
        enabled = self.marker_budget_enabled.isChecked()
        automatic = self.marker_budget_automatic.isChecked()
        self.marker_budget_automatic.setEnabled(enabled)
        for bound in _BOUNDS:
            self.marker_budget_rates[bound].setEnabled(enabled and automatic)
            total = self.marker_budget_totals[bound]
            total.setEnabled(enabled and not automatic)
            total.setReadOnly(automatic or not enabled)
            blocker = QSignalBlocker(total)
            total.setValue(budget[bound] if automatic else self.widgets[_TOTAL_KEYS[bound]].value())
            del blocker
        if not budget["seconds"] and automatic:
            text = "Analyze a timeline to calculate totals from its duration."
        else:
            text = (f"Minimum {budget['min']} · target about {budget['target']} · maximum {budget['max']} markers"
                    f" for {_duration_text(budget['seconds'])} of analyzed video.")
            if not enabled:
                text += " Global budget is off."
        warnings = budget.get("warnings") or []
        if warnings:
            text += "\n" + str(warnings[0])
        self.marker_budget_settings_summary.setText(text)
        self.marker_budget_settings_summary.setToolTip("\n".join(str(warning) for warning in warnings))

    def _build_marker_budget_review_summary(self):
        self.marker_budget_summary = QLabel("")
        self.marker_budget_summary.setWordWrap(True)
        self.marker_budget_summary.setProperty("role", "muted")
        self.marker_budget_review_warnings = []
        self._update_global_marker_budget_summary()
        return self.marker_budget_summary

    def _update_global_marker_budget_summary(self):
        self._refresh_marker_budget_settings()
        if not hasattr(self, "marker_budget_summary"):
            return
        from vispa_mp.marker_budget import budget_settings, count_markers
        analysis = self._marker_budget_analysis()
        budget = budget_settings(self.settings(), analysis)
        warnings = []
        if not analysis:
            text = "Global markers: waiting for an analyzed timeline."
        else:
            manual = analysis.get("_budget_manual_frames", analysis.get("manual_frames") or [])
            count = count_markers(getattr(self, "proposals", []), manual, span=budget.get("span"))
            text = f"Markers: {count}"
            if budget["enabled"]:
                text += f" · target about {budget['target']} ({budget['min']}–{budget['max']})"
                text += f" · {_duration_text(budget['seconds'])}"
                if count < budget["min"]:
                    warnings.append(f"{budget['min'] - count} below minimum; current constraints limit the available images.")
                elif count > budget["max"]:
                    warnings.append(f"{count - budget['max']} above maximum; review the kept markers and manual additions.")
                if not budget["seconds"] and budget["automatic"]:
                    warnings.append("Analyzed duration is unavailable; automatic totals cannot be calculated.")
                if warnings:
                    text += "\n" + warnings[0]
            else:
                text += " · global budget off"
        self.marker_budget_review_warnings = warnings
        self.marker_budget_summary.setText(text)
        self.marker_budget_summary.setProperty("role", "alert" if warnings else "muted")
        self.marker_budget_summary.setToolTip("\n".join([*warnings, *(budget.get("warnings") or [])]))
        self.marker_budget_summary.style().unpolish(self.marker_budget_summary)
        self.marker_budget_summary.style().polish(self.marker_budget_summary)
        sync_report = getattr(self, "_sync_review_report", None)
        if callable(sync_report):
            sync_report()

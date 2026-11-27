"""Budget controls retain manual values and update totals without image analysis."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QCheckBox, QFormLayout, QSlider, QVBoxLayout, QWidget

from vispa_mp.marker_budget import BUDGET_DEFAULTS
from vispa_mp.marker_budget_ui import MarkerBudgetMixin


def analysis(seconds=600, fps=25):
    return {"fps": fps, "timebase": {"fps": fps, "timecode_fps": 25},
            "shots": [{"start": 90_000, "end": 90_000 + int(seconds * fps)}],
            "manual_frames": [], "warnings": []}


class BudgetWindow(MarkerBudgetMixin, QWidget):
    def __init__(self, data=None, values=None):
        super().__init__()
        self._ready = False
        self.analysis = data
        self.proposals = []
        self.widgets = {}
        self.values = {**BUDGET_DEFAULTS, "compression": 0.35, **(values or {})}
        self.change_count = 0
        self.dirty = False
        self.recompute_count = 0
        column = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        column.addLayout(form)
        self._build_marker_budget_settings(form, self.values)
        column.addWidget(self._build_marker_budget_review_summary())
        self._ready = True

    def _settings_row(self, form, key, values):
        assert key == "compression"
        self.compression = QSlider(Qt.Orientation.Horizontal)
        self.compression.setRange(0, 100)
        self.compression.setValue(round(values["compression"] * 100))
        self.widgets["compression"] = self.compression
        self.compression.valueChanged.connect(self._marker_budget_compression_changed)
        form.addRow("Story compression", self.compression)

    def settings(self):
        result = dict(self.values)
        for key, widget in self.widgets.items():
            result[key] = widget.isChecked() if isinstance(widget, QCheckBox) else widget.value()
        result["compression"] = self.compression.value() / 100
        return result

    def _changed(self):
        if self._ready:
            self.change_count += 1
            self.dirty = True
            self.recompute_count += int(self.analysis is not None)
            self._update_global_marker_budget_summary()


@pytest.fixture(autouse=True)
def dispose_budget_windows(qapp):
    yield
    for widget in qapp.topLevelWidgets():
        if isinstance(widget, BudgetWindow):
            widget.close()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def totals(window):
    return [window.marker_budget_totals[bound].value() for bound in ("min", "target", "max")]


def test_default_rates_compute_ten_minute_totals_without_overwriting_manual_values(qapp):
    window = BudgetWindow(analysis())
    assert [window.marker_budget_rates[part].value() for part in ("min", "target", "max")] == [12, 30, 45]
    assert totals(window) == [120, 300, 450]
    assert window.compression.value() == 50
    assert [window.settings()[f"global_markers_{part}"] for part in ("min", "target", "max")] == [0, 0, 0]
    assert all(not widget.isEnabled() and widget.isReadOnly() for widget in window.marker_budget_totals.values())
    assert all(widget.isEnabled() for widget in window.marker_budget_rates.values())
    assert "Minimum 120 · target about 300 · maximum 450" in window.marker_budget_settings_summary.text()
    assert "10 min 00 s" in window.marker_budget_settings_summary.text()
    assert not window.dirty and window.change_count == 0


def test_in_out_duration_and_new_analysis_refresh_totals_without_dirtying(qapp):
    values = {"global_markers_min": 90, "global_markers_target": 160, "global_markers_max": 220}
    data = analysis()
    data["range"] = [90_000, 91_500]
    window = BudgetWindow(data, values)
    assert totals(window) == [12, 30, 45]
    original = window.settings()
    window.analysis = analysis(seconds=1200)
    window._update_global_marker_budget_summary()
    assert totals(window) == [240, 600, 900]
    assert window.settings() == original
    assert not window.dirty and window.change_count == 0


def test_interlaced_frame_rate_uses_timeline_duration_not_display_timecode_rate(qapp):
    window = BudgetWindow(analysis(seconds=600, fps=50))
    assert totals(window) == [120, 300, 450]
    assert "10 min 00 s" in window.marker_budget_settings_summary.text()


def test_first_explicit_manual_mode_seeds_current_automatic_totals_once(qapp):
    window = BudgetWindow(analysis())
    window.marker_budget_automatic.setChecked(False)
    assert totals(window) == [120, 300, 450]
    assert [window.settings()[f"global_markers_{part}"] for part in ("min", "target", "max")] == [120, 300, 450]
    assert window.change_count == 1
    assert all(widget.isEnabled() and not widget.isReadOnly() for widget in window.marker_budget_totals.values())
    assert all(not widget.isEnabled() for widget in window.marker_budget_rates.values())
    window.marker_budget_totals["target"].setValue(250)
    assert window.settings()["global_markers_target"] == 250
    assert window.change_count == 2
    window.marker_budget_automatic.setChecked(True)
    assert totals(window) == [120, 300, 450]
    window.analysis = analysis(seconds=1200)
    window._refresh_marker_budget_settings()
    assert totals(window) == [240, 600, 900]
    window.marker_budget_automatic.setChecked(False)
    assert totals(window) == [120, 250, 450]


def test_restoring_manual_mode_does_not_seed_or_dirty_saved_zero_totals(qapp):
    window = BudgetWindow(analysis())
    window._ready = False
    window.widgets["global_markers_auto"].setChecked(False)
    window._refresh_marker_budget_settings()
    assert totals(window) == [0, 0, 0]
    assert [window.settings()[f"global_markers_{part}"] for part in ("min", "target", "max")] == [0, 0, 0]
    assert window.change_count == 0 and not window.dirty


def test_manual_values_survive_settings_restore_and_are_editable(qapp):
    window = BudgetWindow(analysis(), {"global_markers_auto": False, "global_markers_min": 90,
                                      "global_markers_target": 160, "global_markers_max": 220})
    assert totals(window) == [90, 160, 220]
    window.marker_budget_totals["target"].setValue(190)
    assert window.settings()["global_markers_target"] == 190
    assert window.change_count == 1
    window._ready = False
    for bound, value in zip(("min", "target", "max"), (200, 400, 800)):
        window.widgets[f"global_markers_{bound}"].setValue(value)
    window._refresh_marker_budget_settings()
    assert totals(window) == [200, 400, 800]
    assert window.change_count == 1
    assert window.compression.value() == 16


def test_automatic_total_refresh_blocks_signals_and_keeps_persisted_settings(qapp):
    window = BudgetWindow(analysis())
    events = []
    for bound, widget in window.marker_budget_totals.items():
        widget.valueChanged.connect(lambda value, part=bound: events.append((part, value)))
    before = deepcopy(window.settings())
    window.analysis = analysis(seconds=1)
    window._refresh_marker_budget_settings()
    assert totals(window) == [1, 1, 1]
    assert events == [] and window.settings() == before
    assert not window.dirty


def test_no_analysis_has_zero_auto_totals_and_explains_why(qapp):
    window = BudgetWindow()
    assert totals(window) == [0, 0, 0]
    assert "Analyze a timeline" in window.marker_budget_settings_summary.text()
    assert "waiting for an analyzed timeline" in window.marker_budget_summary.text()
    assert window.marker_budget_review_warnings == []


@pytest.mark.parametrize("position, band", [(0, [24, 60, 90]), (50, [12, 30, 45]), (100, [6, 15, 22.5])])
def test_compression_moves_the_entire_flexible_band(qapp, position, band):
    window = BudgetWindow(analysis())
    if position == 50:
        window.compression.setValue(40)
        window.change_count = 0
    window.compression.setValue(position)
    assert [window.marker_budget_rates[bound].value() for bound in ("min", "target", "max")] == band
    assert totals(window) == [round(value * 10) for value in band]
    assert window.change_count == 1


def test_rate_and_bound_edits_update_compression_and_clamp_target_once(qapp):
    window = BudgetWindow(analysis())
    window.marker_budget_rates["target"].setValue(40)
    assert window.compression.value() == 42
    assert window.change_count == 1
    window.marker_budget_rates["max"].setValue(35)
    assert window.marker_budget_rates["target"].value() == 35
    assert window.compression.value() == 54
    assert window.change_count == 2
    window.marker_budget_rates["target"].setValue(1)
    assert window.marker_budget_rates["target"].value() == 12
    assert window.compression.value() == 78
    assert window.change_count == 3


def test_manual_compression_moves_all_total_bounds_without_touching_rates(qapp):
    window = BudgetWindow(analysis(), {"global_markers_auto": False, "global_markers_min": 100,
                                      "global_markers_target": 200, "global_markers_max": 300})
    original_rates = [window.marker_budget_rates[bound].value() for bound in ("min", "target", "max")]
    window.compression.setValue(25)
    assert totals(window) == [205, 410, 615]
    assert window.settings()["global_markers_target"] == 410
    assert [window.marker_budget_rates[bound].value() for bound in ("min", "target", "max")] == original_rates
    assert window.change_count == 1


def test_equal_bounds_can_move_together_without_division_by_zero(qapp):
    window = BudgetWindow(analysis())
    window.marker_budget_rates["min"].setValue(45)
    assert window.marker_budget_rates["target"].value() == 45
    previous = window.compression.value()
    window._refresh_marker_budget_settings()
    assert window.compression.value() == previous
    window.compression.setValue(37)
    assert len({widget.value() for widget in window.marker_budget_rates.values()}) == 1
    assert window.compression.value() == 37


def test_disabled_budget_retains_classic_page_compression_without_mutating_targets(qapp):
    window = BudgetWindow(analysis(), {"global_markers_enabled": False})
    assert window.compression.value() == 35
    before = window.settings()
    window.compression.setValue(10)
    after = window.settings()
    assert after == {**before, "compression": 0.1}
    assert all(not widget.isEnabled() for widget in window.marker_budget_rates.values())
    assert all(not widget.isEnabled() for widget in window.marker_budget_totals.values())
    assert not window.marker_budget_automatic.isEnabled()
    assert "global budget off" in window.marker_budget_summary.text()
    assert not window.marker_budget_review_warnings


def test_final_summary_counts_unique_roles_and_kept_manual_frames_in_analyzed_range(qapp):
    data = analysis(seconds=60)
    data["manual_frames"] = [90_100, 90_400, 1]
    window = BudgetWindow(data)
    window.proposals = [{"frame": 90_100, "color": "Green"}, {"frame": 90_200, "color": "Blue"},
                        {"frame": 90_200, "color": "Cyan"}, {"frame": 90_300, "color": "Cyan"},
                        {"frame": 90_350, "color": "Red"}, {"frame": 92_000, "color": "Blue"}]
    window._update_global_marker_budget_summary()
    assert window.marker_budget_summary.text().startswith("Markers: 4 · target about 30 (12–45)")
    assert "8 below minimum" in window.marker_budget_summary.text()
    assert window.marker_budget_summary.property("role") == "alert"
    window.proposals = [item for item in window.proposals if item["frame"] != 90_200]
    window.proposals.append({"frame": 90_500, "color": "Blue", "rule": "user"})
    window.proposals.append({"frame": 90_600, "color": "Cyan", "rule": "user"})
    window._update_global_marker_budget_summary()
    assert window.marker_budget_summary.text().startswith("Markers: 5")
    assert "7 below minimum" in window.marker_budget_summary.text()


def test_manual_edits_can_exceed_maximum_and_below_minimum_without_hiding_them(qapp):
    window = BudgetWindow(analysis(), {"global_markers_auto": False, "global_markers_min": 2,
                                      "global_markers_target": 4, "global_markers_max": 5})
    window.proposals = [{"frame": 90_000 + index, "color": "Blue"} for index in range(6)]
    window._update_global_marker_budget_summary()
    assert "Markers: 6" in window.marker_budget_summary.text()
    assert "1 above maximum" in window.marker_budget_summary.text()
    window.proposals.pop()
    window._update_global_marker_budget_summary()
    assert "Markers: 5" in window.marker_budget_summary.text()
    assert not window.marker_budget_review_warnings
    assert window.marker_budget_summary.property("role") == "muted"


def test_root_duration_and_manual_role_provider_is_used_for_totals_and_final_count(qapp):
    window = BudgetWindow(analysis())
    provided = {**window.analysis, "range": [90_000, 91_500], "manual_frames": [90_100, 90_200],
                "_budget_manual_frames": [90_200]}
    window._budget_analysis = lambda: provided
    original = deepcopy(provided)
    window._update_global_marker_budget_summary()
    assert totals(window) == [12, 30, 45]
    assert window.marker_budget_summary.text().startswith("Markers: 1")
    assert provided == original


def test_settings_section_fits_five_hundred_pixel_dialog_under_real_stylesheet(qapp):
    from vispa_mp.ui import _theme
    window = BudgetWindow(analysis())
    window.setStyleSheet(_theme())
    window.resize(500, 480)
    window.show()
    qapp.processEvents()
    assert window.minimumSizeHint().width() <= 500
    for spin in [*window.marker_budget_rates.values(), *window.marker_budget_totals.values()]:
        top_left = spin.mapTo(window, spin.rect().topLeft())
        assert top_left.x() >= 0 and top_left.x() + spin.width() <= window.width()
        assert spin.height() >= 20
    window.close()

"""Open isolated, read-only standard and personal reviews of one analysis."""

from copy import deepcopy

from PySide6.QtCore import Qt
from shiboken6 import isValid

from vispa_mp.preset import PREVIEW_DEFAULTS


class ComparisonReviewMixin:
    def _comparison_profile(self, panel):
        key = panel.profiles.currentData() or ""
        active_key = self._active_selection_profile_key()
        if self._learning_profile is not None and (not key or key == active_key):
            return self._learning_profile
        return self._learning_profile_choices.get(key)

    def _show_profile_comparison(self, panel):
        if self.worker is not None or self._learning_job_busy:
            return
        if not self.analysis:
            self._learning_error("Analyze a timeline before comparing selection profiles.")
            return
        profile = self._comparison_profile(panel)
        if profile is None:
            self._learning_error("Choose or load a personal profile to compare with MP standard rules. You do not need to activate it.")
            return
        analysis, settings, profile = deepcopy(self._budget_analysis()), deepcopy(self.settings()), deepcopy(profile)
        view = {key: deepcopy(getattr(self, key, default)) for key, default in PREVIEW_DEFAULTS.items()}
        view.update({key: deepcopy(getattr(self, key)) for key in
                     ("page_format", "orientation", "custom_width", "custom_height", "mode", "view_filter")})

        def work(progress):
            from vispa_mp.comparison import build_comparison
            return build_comparison(analysis, settings, profile, progress=progress)

        def done(result):
            from vispa_mp.comparison_ui import ComparisonWindow
            windows = []
            try:
                for variant in result["variants"]:
                    windows.append(ComparisonWindow(self, variant, result["analysis"], view))
            except (OSError, ValueError, RuntimeError) as error:
                for window in windows:
                    window.deleteLater()
                self._learning_error("The comparison windows could not be opened. Your current review was kept.", error)
                return
            self._close_profile_comparisons()
            self._comparison_windows = windows
            for window in windows:
                window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                window.destroyed.connect(lambda _object=None, target=window: self._forget_profile_comparison(target))
            screen = self.screen()
            area = screen.availableGeometry() if screen is not None else self.geometry()
            gap = 12
            width = max(1, (area.width() - 3 * gap) // 2)
            height = max(1, area.height() - 2 * gap)
            for index, window in enumerate(windows):
                window.setGeometry(area.x() + gap + index * (width + gap), area.y() + gap, width, height)
                window.show()
            windows[-1].raise_()
            self.status.setText("Comparison opened: standard rules and personal profile. Your current review and settings were kept.")

        self.status.setText("Comparing selections from the existing analysis…")
        try:
            self._start(work, done)
        except (OSError, ValueError, RuntimeError) as error:
            self._learning_error("The comparison could not be calculated. Your current review was kept.", error)

    def _forget_profile_comparison(self, window):
        windows = getattr(self, "_comparison_windows", [])
        if window in windows:
            windows.remove(window)

    def _close_profile_comparisons(self):
        for window in tuple(getattr(self, "_comparison_windows", [])):
            if isValid(window):
                window.close()
        self._comparison_windows = []

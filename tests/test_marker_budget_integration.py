"""Budget editing preserves review choices, old projects and cached analysis."""

from copy import deepcopy

from tests.test_project_ui import _review
from vispa_mp.analyze import analysis_key
from vispa_mp.project import load_project
from vispa_mp.ui import MainWindow


def test_budget_slider_preserves_user_image_role_and_exclusions_without_analysis(qapp, tmp_path, monkeypatch):
    window = _review(qapp, tmp_path)
    chosen = deepcopy(window.proposals[0])
    window._excluded_frames.add(22)
    monkeypatch.setattr("vispa_mp.ui.analyze", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Changing the global budget must not rerun analysis")))
    original_analysis = deepcopy(window.analysis)
    window.compression.setValue(75)
    assert next(item for item in window.proposals if item["frame"] == chosen["frame"]) == chosen
    assert all(item["frame"] != 22 for item in window.proposals)
    assert window.analysis == original_analysis


def test_legacy_project_keeps_its_compression_and_choices(qapp, tmp_path):
    original = _review(qapp, tmp_path)
    path = tmp_path / "legacy.vispamp"
    assert original.save_project_file(path)
    project = load_project(path, tmp_path / "loaded")
    project["settings"] = {key: value for key, value in project["settings"].items()
                           if not key.startswith("global_markers_")}
    project["settings"]["compression"] = 0.7
    saved = deepcopy(project["proposals"])
    window = MainWindow()
    window._restore_project(project, deepcopy(original.snapshot), None, path)
    assert not window.marker_budget_enabled.isChecked()
    assert window.compression.value() == 70
    assert window.proposals == saved
    assert not window._project_dirty


def test_portable_budget_round_trip_restores_band_and_slider_without_recalculation(qapp, tmp_path, monkeypatch):
    original = _review(qapp, tmp_path)
    original.compression.setValue(25)
    band = [widget.value() for widget in original.marker_budget_rates.values()]
    path = tmp_path / "density.vispamp"
    assert original.save_project_file(path)
    project = load_project(path, tmp_path / "loaded")
    window = MainWindow()
    monkeypatch.setattr(window, "recompute", lambda: (_ for _ in ()).throw(AssertionError("Keep the saved preparation")))
    window._restore_project(project, deepcopy(original.snapshot), None, path)
    assert [widget.value() for widget in window.marker_budget_rates.values()] == band
    assert window.compression.value() == 25
    assert window.proposals == project["proposals"]
    assert not window._project_dirty


def test_budget_context_counts_only_manual_image_roles_and_never_changes_analysis(qapp, tmp_path):
    window = _review(qapp, tmp_path)
    window.snapshot["markers"] = [{"frame": 1, "color": "Green", "automatic": False},
                                   {"frame": 2, "color": "Yellow", "automatic": False},
                                   {"frame": 3, "color": "Blue", "automatic": True}]
    before = deepcopy(window.analysis)
    context = window._budget_analysis()
    assert context["_budget_manual_frames"] == [1]
    assert context["timeline_range"] == [0, 24]
    assert window.analysis == before


def test_budget_changes_reuse_the_same_analysis_cache_key(tmp_path):
    from tests.test_analysis_cache import _snapshot
    from vispa_mp.preset import DEFAULTS
    media = tmp_path / "source.mp4"
    media.write_bytes(b"source identity")
    snapshot = _snapshot(media)
    original = analysis_key(snapshot, DEFAULTS)
    assert original is not None
    changed = dict(DEFAULTS, global_markers_per_min_min=6, global_markers_per_min_target=15,
                   global_markers_per_min_max=22.5, compression=1)
    assert analysis_key(snapshot, changed) == original

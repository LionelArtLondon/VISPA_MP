"""Long-shot controls stay explicit and portable without accepting unsafe values."""

import json

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QLabel

from vispa_mp.preset import (
    DEFAULTS, export_settings, import_settings, load, load_user, save_user,
)


def test_default_decomposition_is_enabled_at_four_point_three_seconds(tmp_path):
    settings, _view = load_user(tmp_path / "missing.json")
    assert DEFAULTS["split_long_shots"] is True
    assert settings["split_long_shots"] is True
    assert settings["long_shot_seconds"] == DEFAULTS["long_shot_seconds"] == 4.3
    assert load()["long_shot_seconds"] == 4.3


@pytest.mark.parametrize("key,invalid", [
    ("split_long_shots", 1),
    ("split_long_shots", "yes"),
    ("split_long_shots", None),
    ("long_shot_seconds", True),
    ("long_shot_seconds", "4.3"),
    ("long_shot_seconds", None),
    ("long_shot_seconds", 0.99),
    ("long_shot_seconds", 120.1),
    ("long_shot_seconds", float("nan")),
    ("long_shot_seconds", float("inf")),
    ("long_shot_seconds", float("-inf")),
    ("long_shot_seconds", 10 ** 400),
])
def test_invalid_decomposition_values_never_reach_saved_or_loaded_settings(tmp_path, key, invalid):
    path = tmp_path / "user.json"
    path.write_text(json.dumps({key: invalid}), encoding="utf-8")
    settings, _view = load_user(path)
    assert settings[key] == DEFAULTS[key]
    save_user({key: invalid}, {}, path)
    assert not path.exists()

    path = tmp_path / "portable.json"
    path.write_text(json.dumps({key: invalid, "mouth_min": 0.4}), encoding="utf-8")
    assert key not in import_settings(path)
    export_settings({key: invalid, "mouth_min": 0.4}, path)
    assert key not in json.loads(path.read_text(encoding="utf-8"))["settings"]


@pytest.mark.parametrize("seconds", [1, 4.3, 120])
def test_decomposition_settings_round_trip_in_preferences_and_portable_files(tmp_path, seconds):
    settings = {**load(), "split_long_shots": False, "long_shot_seconds": seconds}
    user = tmp_path / "user.json"
    portable = tmp_path / "selection.json"
    save_user(settings, {}, user)
    restored, _view = load_user(user)
    export_settings(settings, portable)
    imported = import_settings(portable)
    for values in (restored, imported):
        assert values["split_long_shots"] is False
        assert values["long_shot_seconds"] == seconds


def test_decomposition_controls_live_under_analysis_and_explain_reanalysis(qapp):
    from vispa_mp.ui import MainWindow

    window = MainWindow(client=None)
    try:
        tab = next(window.settings_tabs.widget(index) for index in range(window.settings_tabs.count())
                   if window.settings_tabs.tabText(index) == "Analysis")
        switch = window.widgets["split_long_shots"]
        duration = window.widgets["long_shot_seconds"]
        assert isinstance(switch, QCheckBox) and isinstance(duration, QDoubleSpinBox)
        assert switch.text() == "Decompose long shots"
        assert tab.isAncestorOf(switch) and tab.isAncestorOf(duration)
        assert duration.value() == 4.3 and duration.isEnabled()
        assert duration.minimum() == 1 and duration.maximum() == 120
        note = tab.findChild(QLabel, "longShotAnalysisNote")
        assert note is not None and note.wordWrap()
        assert "Analyze again" in note.text() and "Recalculate" in note.text()
        assert "static shots" in note.text()
        assert "end-of-shot" in switch.toolTip()
        switch.setChecked(False)
        assert not duration.isEnabled()
        switch.setChecked(True)
        assert duration.isEnabled()
    finally:
        window._project_dirty = False
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_window_remembers_decomposition_and_reenables_its_duration_on_reset(qapp, user_settings):
    from vispa_mp.ui import MainWindow

    first = MainWindow(client=None)
    second = None
    try:
        first.set_setting("long_shot_seconds", 7.2)
        first.set_setting("split_long_shots", False)
        first.close()
        second = MainWindow(client=None)
        assert second.settings()["long_shot_seconds"] == 7.2
        assert second.settings()["split_long_shots"] is False
        assert not second.widgets["long_shot_seconds"].isEnabled()
        second.reset_settings()
        assert second.settings()["long_shot_seconds"] == 4.3
        assert second.settings()["split_long_shots"] is True
        assert second.widgets["long_shot_seconds"].isEnabled()
    finally:
        for window in (first, second):
            if window is not None:
                window._project_dirty = False
                window.close()
                window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_portable_preparation_keeps_the_threshold_and_switch(tmp_path):
    from tests.test_project import _review
    from vispa_mp.project import load_project, save_project

    review = _review(tmp_path)
    review["settings"].update(split_long_shots=False, long_shot_seconds=6.7)
    path = tmp_path / "chapter.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "cache")
    assert restored["settings"]["split_long_shots"] is False
    assert restored["settings"]["long_shot_seconds"] == 6.7


@pytest.mark.parametrize("key,value", [("long_shot_seconds", 0), ("long_shot_seconds", 121),
                                      ("split_long_shots", 1)])
def test_portable_preparation_rejects_invalid_decomposition_settings(tmp_path, key, value):
    from tests.test_project import _review
    from vispa_mp.project import save_project

    review = _review(tmp_path)
    review["settings"][key] = value
    with pytest.raises(ValueError, match=key):
        save_project(tmp_path / "invalid.vispamp", **review)


def test_portable_preparation_preserves_original_shot_protection(tmp_path):
    from tests.test_project import _review
    from vispa_mp.project import load_project, save_project

    review = _review(tmp_path)
    review["analysis"]["shots"][0].update(parent_start=86300, parent_end=86500, reframed=True)
    review["analysis"]["shot_decomposition"] = {"enabled": True, "seconds": 4.3}
    path = tmp_path / "reframed.vispamp"
    save_project(path, **review)
    restored = load_project(path, tmp_path / "cache")
    assert restored["analysis"]["shot_decomposition"] == {"enabled": True, "seconds": 4.3}
    shot = restored["analysis"]["shots"][0]
    assert (shot["parent_start"], shot["parent_end"]) == (86300, 86500)


@pytest.mark.parametrize("bounds", [{"parent_start": 86300},
                                   {"parent_start": None, "parent_end": 86500},
                                   {"parent_start": True, "parent_end": 86500},
                                   {"parent_start": 86401, "parent_end": 86500},
                                   {"parent_start": 86300, "parent_end": 86423}])
def test_loading_a_project_rejects_unusable_original_shot_bounds(tmp_path, bounds):
    from tests.test_project import _review, _rewrite
    from vispa_mp.project import load_project, save_project

    path = tmp_path / "bad-bounds.vispamp"
    save_project(path, **_review(tmp_path))
    _rewrite(path, edit=lambda data: data["analysis"]["shots"][0].update(bounds))
    with pytest.raises(ValueError, match="original bounds"):
        load_project(path, tmp_path / "cache")


@pytest.mark.parametrize("metadata", [None, {"enabled": "yes", "seconds": 4.3},
                                     {"enabled": True, "seconds": float("nan")},
                                     {"enabled": True, "seconds": 0}])
def test_loading_a_project_rejects_unusable_decomposition_metadata(tmp_path, metadata):
    from tests.test_project import _review, _rewrite
    from vispa_mp.project import load_project, save_project

    path = tmp_path / "bad-decomposition.vispamp"
    save_project(path, **_review(tmp_path))
    _rewrite(path, edit=lambda data: data["analysis"].update(shot_decomposition=metadata))
    with pytest.raises(ValueError, match="shot decomposition|numeric value"):
        load_project(path, tmp_path / "cache")

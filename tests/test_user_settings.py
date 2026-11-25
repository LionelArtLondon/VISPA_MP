"""Settings and the page format come back after a restart; Reset goes back to the shipped preset."""

import json

from vispa_mp.preset import DEFAULTS, load, load_user, save_user


def test_only_changes_are_written_and_bad_values_are_skipped(user_settings):
    settings, view = load_user()
    assert settings == load() and view["page_format"] == "A5"
    settings["mouth_min"] = 0.45
    view["page_format"] = "B5"
    save_user(settings, view)
    assert json.loads(user_settings.read_text(encoding="utf-8")) == {"mouth_min": 0.45, "page_format": "B5"}
    user_settings.write_text(json.dumps({
        "mouth_min": 0.45, "use_in_out": "yes", "nonsense": 3, "page_format": "B5",
    }), encoding="utf-8")
    settings, view = load_user()
    assert settings["mouth_min"] == 0.45
    assert settings["use_in_out"] == DEFAULTS["use_in_out"]
    assert "nonsense" not in settings
    assert view["page_format"] == "B5"
    save_user(load(), {"page_format": "A5"})
    assert not user_settings.exists()


def test_a_damaged_file_does_not_stop_the_app(user_settings):
    user_settings.write_text("{ cut short", encoding="utf-8")
    settings, view = load_user()
    assert settings == load()
    assert view["orientation"] == "portrait"


def test_the_window_remembers_its_settings_across_a_restart(qapp, user_settings):
    from vispa_mp.ui import MainWindow

    window = MainWindow(client=None)
    window.set_setting("mouth_min", 0.55)
    window.format_buttons["B5"].click()
    window.orientation_buttons["landscape"].click()
    window.close()
    assert user_settings.exists()

    again = MainWindow(client=None)
    assert abs(again.settings()["mouth_min"] - 0.55) < 1e-9
    assert again.page_format == "B5" and again.orientation == "landscape"
    assert again.format_buttons["B5"].isChecked()
    assert again.orientation_buttons["landscape"].isChecked()

    again.reset_settings()
    assert again.settings()["mouth_min"] == load()["mouth_min"]
    assert again.page_format == "B5"
    third = MainWindow(client=None)
    assert third.settings()["mouth_min"] == load()["mouth_min"]
    assert json.loads(user_settings.read_text(encoding="utf-8")) == {"orientation": "landscape", "page_format": "B5"}


def test_a_saved_settings_file_loads_back(tmp_path):
    import pytest

    from vispa_mp.preset import export_settings, import_settings
    settings = load()
    settings["mouth_min"] = 0.4
    settings["target_pages_max"] = 35
    path = tmp_path / "avatar.json"
    export_settings(settings, path)
    loaded = import_settings(path)
    assert loaded["mouth_min"] == 0.4 and loaded["target_pages_max"] == 35
    assert set(loaded) == set(DEFAULTS)
    other = tmp_path / "other.json"
    other.write_text('{"use_in_out": "yes", "nonsense": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        import_settings(other)
    other.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        import_settings(other)


def test_the_window_loads_a_settings_file_and_keeps_it(qapp, tmp_path, user_settings):
    from vispa_mp.preset import export_settings
    from vispa_mp.ui import MainWindow
    settings = load()
    settings["mouth_min"] = 0.65
    settings["min_green_seconds"] = 3.0
    path = tmp_path / "prepared.json"
    export_settings(settings, path)
    window = MainWindow(client=None)
    window.format_buttons["B5"].click()
    window.load_settings_file(path)
    assert abs(window.settings()["mouth_min"] - 0.65) < 1e-9
    assert window.settings()["min_green_seconds"] == 3.0
    assert window.page_format == "B5"
    again = MainWindow(client=None)  # kept for the next launch too
    assert abs(again.settings()["mouth_min"] - 0.65) < 1e-9


def test_the_tab_bar_draws_no_base_line(qapp):
    from vispa_mp.ui import MainWindow
    assert MainWindow(client=None).settings_tabs.tabBar().drawBase() is False

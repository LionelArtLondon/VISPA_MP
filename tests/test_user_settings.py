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

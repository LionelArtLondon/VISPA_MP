import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def user_settings(tmp_path, monkeypatch):
    """Tests never read or write the real presets/user.json."""
    path = tmp_path / "user.json"
    monkeypatch.setattr("vispa_mp.preset.USER_PATH", path)
    return path

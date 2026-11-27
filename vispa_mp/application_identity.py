"""Windows application identity and shared icon for VISPA MP windows."""
from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import sys

from PySide6 import QtGui, QtWidgets

from vispa_mp.windows_taskbar import install_taskbar_identity, set_process_app_id


APP_USER_MODEL_ID = "VISPA.Suite.MP"
APPLICATION_ICON_PATH = Path(__file__).resolve().parent / "icons" / "vispa_mp.ico"


def application_relaunch_command() -> str:
    executable = Path(sys.executable)
    windowed = executable.with_name("pythonw.exe")
    if windowed.is_file():
        executable = windowed
    launcher = Path(__file__).resolve().parents[1] / "launch_vispa_mp.pyw"
    return subprocess.list2cmdline([str(executable), "-B", str(launcher)])


def create_vispa_mp_application(argv: list[str]) -> QtWidgets.QApplication:
    # Establish process identity before Qt creates any application windows.
    set_process_app_id(APP_USER_MODEL_ID)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
    app.setApplicationDisplayName("VISPA MP")
    icon = QtGui.QIcon(str(APPLICATION_ICON_PATH))
    if not icon.isNull():
        app.setWindowIcon(icon)
    else:
        logging.getLogger(__name__).warning("Could not load the VISPA MP application icon: %s", APPLICATION_ICON_PATH)
    install_taskbar_identity(
        app,
        app_id=APP_USER_MODEL_ID,
        display_name="VISPA MP",
        icon_path=APPLICATION_ICON_PATH,
        relaunch_command=application_relaunch_command(),
    )
    return app

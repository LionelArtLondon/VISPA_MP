"""Isolated Qt/Windows probes never open a project or connect to Resolve."""
import ctypes
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _windows_app_id():
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    get_app_id = shell32.GetCurrentProcessExplicitAppUserModelID
    get_app_id.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    get_app_id.restype = ctypes.c_long
    free = ctypes.WinDLL("ole32").CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    allocated = ctypes.c_void_p()
    result = get_app_id(ctypes.byref(allocated))
    try:
        if result < 0:
            raise OSError(f"GetCurrentProcessExplicitAppUserModelID failed: {result:#x}")
        return ctypes.wstring_at(allocated.value)
    finally:
        if allocated.value:
            free(allocated)


def _window_taskbar_properties(hwnd):
    from ctypes import wintypes

    class Guid(ctypes.Structure):
        _fields_ = [("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16),
                    ("data3", ctypes.c_uint16), ("data4", ctypes.c_ubyte * 8)]

    class PropertyKey(ctypes.Structure):
        _fields_ = [("format", Guid), ("pid", ctypes.c_uint32)]

    class VariantData(ctypes.Union):
        _fields_ = [("pointer", ctypes.c_void_p), ("pair", ctypes.c_void_p * 2)]

    class PropVariant(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("reserved", ctypes.c_ushort * 3), ("data", VariantData)]

    interface_id = Guid.from_buffer_copy(uuid.UUID("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99").bytes_le)
    property_id = Guid.from_buffer_copy(uuid.UUID("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3").bytes_le)
    get_store = ctypes.WinDLL("shell32", use_last_error=True).SHGetPropertyStoreForWindow
    get_store.argtypes = [wintypes.HWND, ctypes.POINTER(Guid), ctypes.POINTER(ctypes.c_void_p)]
    get_store.restype = ctypes.c_long
    store = ctypes.c_void_p()
    result = get_store(hwnd, ctypes.byref(interface_id), ctypes.byref(store))
    if result < 0:
        raise OSError(f"SHGetPropertyStoreForWindow failed: {result:#x}")
    vtable = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    get_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PropertyKey),
                                  ctypes.POINTER(PropVariant))(vtable[5])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    clear = ctypes.WinDLL("ole32").PropVariantClear
    clear.argtypes = [ctypes.POINTER(PropVariant)]
    clear.restype = ctypes.c_long
    values = {}
    try:
        for pid in (2, 3, 4, 5):
            value = PropVariant()
            key = PropertyKey(property_id, pid)
            result = get_value(store, ctypes.byref(key), ctypes.byref(value))
            try:
                assert result >= 0, (pid, result)
                assert value.vt == 31, (pid, value.vt)
                values[pid] = ctypes.wstring_at(value.data.pointer)
            finally:
                clear(ctypes.byref(value))
        return values
    finally:
        release(store)


def _qt_probe():
    from PySide6 import QtCore, QtWidgets

    sys.path.insert(0, str(ROOT))
    from vispa_mp import application_identity as identity

    app = identity.create_vispa_mp_application(["VISPA-MP-identity-probe"])
    assert app.applicationDisplayName() == "VISPA MP"
    assert not app.windowIcon().isNull()
    # Reusing an application must retain the names that address user settings.
    app.setApplicationName("VISPA-MP-probe-existing-name")
    app.setOrganizationName("VISPA-MP-probe-existing-organization")
    assert identity.create_vispa_mp_application([]) is app
    assert app.applicationName() == "VISPA-MP-probe-existing-name"
    assert app.organizationName() == "VISPA-MP-probe-existing-organization"
    native_id = _windows_app_id() if sys.platform == "win32" else None
    if sys.platform == "win32":
        assert native_id == "VISPA.Suite.MP", native_id

    main = QtWidgets.QMainWindow()
    windows = [main, QtWidgets.QDialog(main), QtWidgets.QWidget()]
    names = ["main", "dialog", "independent"]
    native_windows = []
    taskbar_windows = []
    executable = Path(sys.executable)
    windowed = executable.with_name("pythonw.exe")
    if windowed.is_file():
        executable = windowed
    expected_command = subprocess.list2cmdline([str(executable), "-B", str(ROOT / "launch_vispa_mp.pyw")])
    try:
        for name, window in zip(names, windows):
            assert window.windowIcon().cacheKey() == app.windowIcon().cacheKey(), name
            assert window.windowIcon().pixmap(32, 32).toImage() == app.windowIcon().pixmap(32, 32).toImage(), name
            window.setWindowFlag(QtCore.Qt.WindowType.WindowDoesNotAcceptFocus, True)
            window.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            window.resize(160, 80)
            window.move(-20000, -20000)
            window.show()
            app.processEvents()
            if sys.platform == "win32" and app.platformName() == "windows":
                from ctypes import wintypes

                send_message = ctypes.WinDLL("user32", use_last_error=True).SendMessageW
                send_message.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                send_message.restype = ctypes.c_ssize_t
                assert any(send_message(int(window.winId()), 0x007F, variant, 0) for variant in (1, 0, 2)), name
                native_windows.append(name)
                properties = _window_taskbar_properties(int(window.winId()))
                assert properties == {2: expected_command, 3: f"{identity.APPLICATION_ICON_PATH},0",
                                      4: "VISPA MP", 5: "VISPA.Suite.MP"}, (name, properties)
                taskbar_windows.append(name)
        return {"display_name": app.applicationDisplayName(), "native_app_id": native_id,
                "inherited_windows": names, "native_icon_windows": native_windows,
                "native_taskbar_windows": taskbar_windows, "relaunch_command": expected_command,
                "settings_names_preserved": True}
    finally:
        for window in reversed(windows):
            window.close()
        app.processEvents()


def test_existing_icon_supports_small_and_large_windows_sizes():
    from PIL import Image

    with Image.open(ROOT / "vispa_mp" / "icons" / "vispa_mp.ico") as icon:
        assert icon.format == "ICO"
        assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= icon.ico.sizes()
        for size in icon.ico.sizes():
            image = icon.ico.getimage(size).convert("RGBA")
            assert image.size == size
            assert image.getchannel("A").getbbox() is not None


def test_application_reuse_windows_identity_and_inherited_icons():
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "windows" if sys.platform == "win32" else "offscreen"
    result = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--qt-probe"],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.splitlines()[-1])
    assert report["display_name"] == "VISPA MP"
    assert report["settings_names_preserved"]
    assert report["inherited_windows"] == ["main", "dialog", "independent"]
    if sys.platform == "win32":
        assert report["native_app_id"] == "VISPA.Suite.MP"
        assert report["native_icon_windows"] == ["main", "dialog", "independent"]
        assert report["native_taskbar_windows"] == ["main", "dialog", "independent"]


def test_launcher_reloads_current_source_from_an_unrelated_working_directory(tmp_path):
    source = tmp_path / "source tree"
    source.mkdir()
    launcher = source / "launch_vispa_mp.pyw"
    shutil.copyfile(ROOT / "launch_vispa_mp.pyw", launcher)
    package = source / "vispa_mp"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    wrong_package = foreign / "vispa_mp"
    wrong_package.mkdir()
    (wrong_package / "__init__.py").write_text("", encoding="utf-8")
    (wrong_package / "__main__.py").write_text("raise RuntimeError('wrong source tree')\n", encoding="utf-8")
    main_module = package / "__main__.py"

    def write_source(version):
        main_module.write_text(
            "import json,os,sys\n"
            f"print(json.dumps({{'version': {version!r}, 'cwd': os.getcwd(), "
            "'arguments': sys.argv[1:], 'no_bytecode': sys.dont_write_bytecode, "
            "'cache_prefix': sys.pycache_prefix}))\n",
            encoding="utf-8",
        )
        os.utime(main_module, (1700000000, 1700000000))

    write_source("v1")
    py_compile.compile(str(main_module), doraise=True)
    original_cache = {path: path.read_bytes() for path in source.rglob("*.pyc")}
    assert original_cache
    for version in ("v1", "v2"):
        write_source(version)  # Same file size and mtime; the v1 cache still looks valid.
        result = subprocess.run([sys.executable, "-B", str(launcher), "--probe-argument"],
                                cwd=foreign, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout)
        assert report["version"] == version
        assert report["cwd"] == str(source)
        assert report["arguments"] == ["--probe-argument"]
        assert report["no_bytecode"]
        assert not Path(report["cache_prefix"]).exists()
    assert {path: path.read_bytes() for path in source.rglob("*.pyc")} == original_cache


def test_startup_applies_identity_before_creating_the_main_window(monkeypatch):
    from vispa_mp import resolve_link, ui

    class IdentityIntercepted(Exception):
        pass

    def intercept(argv):
        assert argv == []
        raise IdentityIntercepted

    def forbidden_window():
        pytest.fail("The main window was created before the application identity")

    # The startup's Resolve installation must never run in this test.
    monkeypatch.setattr(resolve_link, "install_resolve_script", lambda: None)
    monkeypatch.setattr(ui, "create_vispa_mp_application", intercept)
    monkeypatch.setattr(ui, "MainWindow", forbidden_window)
    with pytest.raises(IdentityIntercepted):
        ui.run()


if __name__ == "__main__" and "--qt-probe" in sys.argv:
    print(json.dumps(_qt_probe()))

"""Windows taskbar identity and source-launch metadata without extra dependencies.

Install the Qt filter before showing application windows. Window properties are
set before the explicit window ID, as required by the Windows Shell, and removed
while their native surface is still alive.
"""
from __future__ import annotations

import ctypes
from functools import lru_cache
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid
import weakref

from PySide6 import QtCore, QtGui, QtWidgets


_LOGGER = logging.getLogger(__name__)
_PROPERTY_IDS = {"relaunch_command": 2, "icon_resource": 3, "display_name": 4, "app_id": 5}


class _GUID(ctypes.Structure):
    _fields_ = [("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16),
                ("data3", ctypes.c_uint16), ("data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _CountedPointer(ctypes.Structure):
    _fields_ = [("count", ctypes.c_uint32), ("pointer", ctypes.c_void_p)]


class _VariantValue(ctypes.Union):
    # A counted array is the largest PROPVARIANT union member on Windows x64.
    _fields_ = [("pointer", ctypes.c_void_p), ("integer", ctypes.c_uint64),
                ("counted", _CountedPointer)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_uint16), ("reserved1", ctypes.c_uint16),
                ("reserved2", ctypes.c_uint16), ("reserved3", ctypes.c_uint16),
                ("value", _VariantValue)]


_APP_PROPERTY_GUID = _GUID.parse("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3")
_PROPERTY_STORE_IID = _GUID.parse("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")


def _check_result(result, operation):
    if result < 0:
        raise OSError(f"{operation} failed: HRESULT 0x{result & 0xffffffff:08x}")


@lru_cache(maxsize=1)
def _windows_api():
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32")
    get_store = shell32.SHGetPropertyStoreForWindow
    get_store.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
    get_store.restype = ctypes.c_long
    set_process_id = shell32.SetCurrentProcessExplicitAppUserModelID
    set_process_id.argtypes = [ctypes.c_wchar_p]
    set_process_id.restype = ctypes.c_long
    allocate = ole32.CoTaskMemAlloc
    allocate.argtypes = [ctypes.c_size_t]
    allocate.restype = ctypes.c_void_p
    clear = ole32.PropVariantClear
    clear.argtypes = [ctypes.POINTER(_PROPVARIANT)]
    clear.restype = ctypes.c_long
    return SimpleNamespace(get_store=get_store, set_process_id=set_process_id,
                           allocate=allocate, clear=clear)


class _WindowPropertyStore:
    def __init__(self, hwnd):
        self.pointer = ctypes.c_void_p()
        result = _windows_api().get_store(int(hwnd), ctypes.byref(_PROPERTY_STORE_IID),
                                          ctypes.byref(self.pointer))
        _check_result(result, "SHGetPropertyStoreForWindow")
        table = ctypes.cast(self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        signature = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                       ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT))
        self._get = signature(table[5])
        self._set = signature(table[6])
        self._release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])

    def close(self):
        if self.pointer:
            self._release(self.pointer)
            self.pointer = ctypes.c_void_p()

    def set(self, name, value):
        key = _PROPERTYKEY(_APP_PROPERTY_GUID, _PROPERTY_IDS[name])
        variant = _PROPVARIANT()
        if value is not None:
            buffer = ctypes.create_unicode_buffer(str(value))
            allocation = _windows_api().allocate(ctypes.sizeof(buffer))
            if not allocation:
                raise MemoryError("Could not allocate a taskbar property string")
            ctypes.memmove(allocation, buffer, ctypes.sizeof(buffer))
            variant.vt = 31  # VT_LPWSTR; allocation is owned by this PROPVARIANT.
            variant.value.pointer = allocation
        try:
            _check_result(self._set(self.pointer, ctypes.byref(key), ctypes.byref(variant)),
                          f"IPropertyStore.SetValue({name})")
        finally:
            _windows_api().clear(ctypes.byref(variant))

    def get(self, name):
        key = _PROPERTYKEY(_APP_PROPERTY_GUID, _PROPERTY_IDS[name])
        variant = _PROPVARIANT()
        try:
            _check_result(self._get(self.pointer, ctypes.byref(key), ctypes.byref(variant)),
                          f"IPropertyStore.GetValue({name})")
            if variant.vt == 0:
                return None
            if variant.vt not in (31, 8):  # VT_LPWSTR or VT_BSTR
                raise ValueError(f"Unexpected taskbar property type: {variant.vt}")
            return ctypes.wstring_at(variant.value.pointer) if variant.value.pointer else ""
        finally:
            _windows_api().clear(ctypes.byref(variant))


def _set_window_properties(hwnd, properties):
    store = _WindowPropertyStore(hwnd)
    try:
        # ID is deliberately last: setting it notifies the taskbar to refresh.
        for name in _PROPERTY_IDS:
            store.set(name, properties[name])
    finally:
        store.close()


def _clear_window_properties(hwnd):
    store = _WindowPropertyStore(hwnd)
    try:
        for name in reversed(_PROPERTY_IDS):
            store.set(name, None)  # VT_EMPTY removes a window property.
    finally:
        store.close()


def _get_window_properties(hwnd):
    """Read taskbar metadata for isolated native verification."""
    store = _WindowPropertyStore(hwnd)
    try:
        return {name: store.get(name) for name in _PROPERTY_IDS}
    finally:
        store.close()


def set_process_app_id(app_id):
    """Set Windows process identity before constructing QApplication."""
    if sys.platform != "win32":
        return False
    try:
        _check_result(_windows_api().set_process_id(str(app_id)),
                      "SetCurrentProcessExplicitAppUserModelID")
        return True
    except (OSError, AttributeError) as error:
        _LOGGER.warning("Could not set application taskbar identity: %s", error)
        return False


class _TaskbarIdentityFilter(QtCore.QObject):
    def __init__(self, app, properties):
        super().__init__(app)
        self.properties = properties
        self._widgets = weakref.WeakKeyDictionary()
        self._surfaces = weakref.WeakKeyDictionary()
        self._applying = False

    def _apply(self, widget, *, create=False):
        if self._applying or not widget.isWindow():
            return
        if widget.windowType() in (QtCore.Qt.WindowType.Popup, QtCore.Qt.WindowType.ToolTip,
                                    QtCore.Qt.WindowType.Desktop):
            return
        self._applying = True
        try:
            # effectiveWinId never creates a replacement HWND during destruction.
            hwnd = int(widget.effectiveWinId() or 0)
            if not hwnd and create:
                hwnd = int(widget.winId())
            if not hwnd or self._widgets.get(widget) == hwnd:
                return
            _set_window_properties(hwnd, self.properties)
            self._widgets[widget] = hwnd
            surface = widget.windowHandle()
            if surface is not None:
                self._surfaces[surface] = hwnd
        except (OSError, AttributeError, ValueError, RuntimeError) as error:
            _LOGGER.warning("Could not set window taskbar metadata: %s", error)
        finally:
            self._applying = False

    def _clear(self, hwnd):
        try:
            _clear_window_properties(hwnd)
        except (OSError, AttributeError, ValueError) as error:
            _LOGGER.debug("Could not clear window taskbar metadata: %s", error)
        for mapping in (self._widgets, self._surfaces):
            for owner, stored in list(mapping.items()):
                if stored == hwnd:
                    mapping.pop(owner, None)

    def clear(self):
        for hwnd in set(self._widgets.values()) | set(self._surfaces.values()):
            self._clear(hwnd)

    def eventFilter(self, watched, event):
        kind = event.type()
        if isinstance(watched, QtWidgets.QWidget) and kind in (
            QtCore.QEvent.Type.Show, QtCore.QEvent.Type.WinIdChange
        ):
            self._apply(watched, create=kind == QtCore.QEvent.Type.Show)
        elif isinstance(watched, QtGui.QWindow) and kind == QtCore.QEvent.Type.PlatformSurface:
            if event.surfaceEventType() == QtGui.QPlatformSurfaceEvent.SurfaceEventType.SurfaceAboutToBeDestroyed:
                hwnd = self._surfaces.get(watched)
                if hwnd:
                    self._clear(hwnd)
        return False


def install_taskbar_identity(app, *, app_id, display_name, icon_path, relaunch_command):
    """Configure each native Qt window for pinning; never edits user shortcuts.

    relaunch_command must already be Windows-quoted and launch the application's
    current source checkout. Install before creating or displaying its windows.
    """
    if sys.platform != "win32" or app.platformName() != "windows":
        return None
    properties = {
        "relaunch_command": str(relaunch_command),
        "icon_resource": f"{Path(icon_path).resolve()},0",
        "display_name": str(display_name),
        "app_id": str(app_id),
    }
    previous = getattr(app, "_vispa_taskbar_identity_filter", None)
    if previous is not None:
        previous.properties = properties
        for widget in list(previous._widgets):
            previous._widgets.pop(widget, None)
            previous._apply(widget)
        return previous
    listener = _TaskbarIdentityFilter(app, properties)
    app._vispa_taskbar_identity_filter = listener
    app.installEventFilter(listener)
    app.aboutToQuit.connect(listener.clear)
    return listener

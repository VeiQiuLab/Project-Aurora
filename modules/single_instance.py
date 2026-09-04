"""Windows single-instance gate and safe activation request for Aurora.

The module intentionally depends only on the Python standard library so the
gate can run before configuration, logging, stores, services, or GUI imports.
Windows owns named-object lifetime, so a crashed process cannot leave a stale
PID file or permanent lock behind.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Callable


INSTANCE_GUID = "7D38E09B-1C55-4F42-9F1E-DF41D582A771"
MUTEX_NAME = rf"Local\ProjectAurora-{INSTANCE_GUID}"
ACTIVATION_EVENT_NAME = rf"Local\ProjectAurora-Activate-{INSTANCE_GUID}"
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
INFINITE = 0xFFFFFFFF


@dataclass(frozen=True)
class MutexResult:
    handle: Any
    already_exists: bool


class Win32NamedObjectBackend:
    """Small injectable wrapper around the Win32 named-object APIs."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("Win32 named objects are unavailable on this platform.")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        self.kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel32.CreateMutexW.restype = wintypes.HANDLE
        self.kernel32.CreateEventW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        self.kernel32.CreateEventW.restype = wintypes.HANDLE
        self.kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel32.OpenEventW.restype = wintypes.HANDLE
        self.kernel32.SetEvent.argtypes = [wintypes.HANDLE]
        self.kernel32.SetEvent.restype = wintypes.BOOL
        self.kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL

    def create_mutex(self, name: str) -> MutexResult:
        ctypes.set_last_error(0)
        handle = self.kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return MutexResult(handle, ctypes.get_last_error() == ERROR_ALREADY_EXISTS)

    def create_event(self, name: str):
        handle = self.kernel32.CreateEventW(None, False, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def open_event(self, name: str):
        return self.kernel32.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, name)

    def set_event(self, handle) -> bool:
        return bool(handle and self.kernel32.SetEvent(handle))

    def wait_event(self, handle, timeout_ms: int = INFINITE) -> int:
        return int(self.kernel32.WaitForSingleObject(handle, timeout_ms))

    def close_handle(self, handle) -> None:
        if handle:
            self.kernel32.CloseHandle(handle)

    def activate_window(self, hwnd: int) -> bool:
        """Restore Aurora's own HWND and request focus/attention."""

        if not hwnd:
            return False
        GA_ROOT = 2
        SW_SHOW = 5
        SW_RESTORE = 9
        FLASHW_TRAY = 0x00000002
        FLASHW_TIMERNOFG = 0x0000000C

        self.user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user32.GetAncestor.restype = wintypes.HWND
        root = self.user32.GetAncestor(wintypes.HWND(hwnd), GA_ROOT) or wintypes.HWND(hwnd)
        self.user32.IsIconic.argtypes = [wintypes.HWND]
        self.user32.IsIconic.restype = wintypes.BOOL
        self.user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.ShowWindow.restype = wintypes.BOOL
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.SetForegroundWindow.restype = wintypes.BOOL
        self.user32.ShowWindow(root, SW_RESTORE if self.user32.IsIconic(root) else SW_SHOW)
        foreground = bool(self.user32.SetForegroundWindow(root))
        if not foreground:
            class FLASHWINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.UINT),
                    ("hwnd", wintypes.HWND),
                    ("dwFlags", wintypes.DWORD),
                    ("uCount", wintypes.UINT),
                    ("dwTimeout", wintypes.DWORD),
                ]

            self.user32.FlashWindowEx.argtypes = [ctypes.POINTER(FLASHWINFO)]
            self.user32.FlashWindowEx.restype = wintypes.BOOL
            flash = FLASHWINFO(
                ctypes.sizeof(FLASHWINFO),
                root,
                FLASHW_TRAY | FLASHW_TIMERNOFG,
                3,
                0,
            )
            self.user32.FlashWindowEx(ctypes.byref(flash))
        return foreground


class SingleInstanceGuard:
    """Own Aurora's mutex and listen for activation requests from later starts."""

    def __init__(self, backend=None):
        self.backend = backend
        self.mutex_handle = None
        self.activation_event_handle = None
        self.is_primary = False
        self.activation_requested = False
        self._closing = threading.Event()
        self._listener = None

    def claim_or_activate(self) -> bool:
        """Return True only for the primary process; notify it otherwise."""

        if os.name != "nt" and self.backend is None:
            self.is_primary = True
            return True
        backend = self.backend or Win32NamedObjectBackend()
        self.backend = backend
        result = backend.create_mutex(MUTEX_NAME)
        self.mutex_handle = result.handle
        if result.already_exists:
            self.activation_requested = self._request_existing_activation()
            backend.close_handle(self.mutex_handle)
            self.mutex_handle = None
            return False
        self.activation_event_handle = backend.create_event(ACTIVATION_EVENT_NAME)
        self.is_primary = True
        return True

    def _request_existing_activation(self) -> bool:
        # The primary creates the event immediately after the mutex.  Retry the
        # tiny creation race without allowing application initialization here.
        for _attempt in range(20):
            handle = self.backend.open_event(ACTIVATION_EVENT_NAME)
            if handle:
                try:
                    return self.backend.set_event(handle)
                finally:
                    self.backend.close_handle(handle)
            time.sleep(0.025)
        return False

    def start_activation_listener(self, callback: Callable[[], None]) -> None:
        if not self.is_primary or not self.activation_event_handle or self._listener:
            return

        def listen() -> None:
            while not self._closing.is_set():
                result = self.backend.wait_event(self.activation_event_handle)
                if self._closing.is_set():
                    return
                if result == WAIT_OBJECT_0:
                    try:
                        callback()
                    except Exception:
                        continue
                elif result != WAIT_TIMEOUT:
                    return

        self._listener = threading.Thread(
            target=listen,
            name="AuroraActivationListener",
            daemon=True,
        )
        self._listener.start()

    def activate_tk_window(self, window) -> None:
        """Schedule restoration of Aurora's known root window only."""

        def restore() -> None:
            try:
                window.deiconify()
                window.lift()
                window.update_idletasks()
                self.backend.activate_window(int(window.winfo_id()))
            except Exception:
                return

        try:
            window.after(0, restore)
        except Exception:
            return

    def close(self) -> None:
        self._closing.set()
        if self.activation_event_handle and self.backend:
            self.backend.set_event(self.activation_event_handle)
        if self._listener and self._listener.is_alive():
            self._listener.join(timeout=0.5)
        if self.backend:
            self.backend.close_handle(self.activation_event_handle)
            self.backend.close_handle(self.mutex_handle)
        self.activation_event_handle = None
        self.mutex_handle = None
        self.is_primary = False


def enforce_single_instance(guard: SingleInstanceGuard | None = None) -> SingleInstanceGuard:
    """Apply the gate and exit a duplicate before application initialization."""

    active_guard = guard or SingleInstanceGuard()
    if not active_guard.claim_or_activate():
        raise SystemExit(0)
    return active_guard

"""Operation locking and redo coordination for the existing JSON MemoryStore.

No memory schema changes. All cooperating readers/writers use the same OS lock.
The durable intent contains exact after-images, so replay is idempotent.
"""
import ctypes
import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

_registry_lock = threading.Lock()
_registry = {}


@contextmanager
def storage_lock(path):
    key = os.path.normcase(str(Path(path).resolve().parent))
    with _registry_lock:
        lock, local = _registry.setdefault(key, (threading.RLock(), threading.local()))
    with lock:
        depth = getattr(local, "depth", 0)
        local.depth = depth + 1
        handle = None
        try:
            if not depth:
                identity = hashlib.sha256(key.encode()).hexdigest()
                if os.name == "nt":
                    from ctypes import wintypes
                    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
                    kernel.CreateMutexW.restype = wintypes.HANDLE
                    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
                    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                    handle = kernel.CreateMutexW(None, False, "Local\\AuroraMemory-" + identity)
                    if not handle:
                        raise OSError("Memory lock unavailable")
                    # WAIT_ABANDONED transfers ownership: replay intent before access.
                    acquired = kernel.WaitForSingleObject(handle, 30000)
                    if acquired not in (0, 0x80):
                        kernel.CloseHandle(handle)
                        handle = None
                        raise OSError("Memory lock timeout")
                else:
                    import fcntl
                    handle = open(Path(tempfile.gettempdir()) / ("aurora-memory-" + identity + ".lock"), "a+b")
                    fcntl.flock(handle, fcntl.LOCK_EX)
            yield not depth
        finally:
            if handle is not None:
                if os.name == "nt":
                    kernel.ReleaseMutex(handle)
                    kernel.CloseHandle(handle)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)
                    handle.close()
            local.depth = depth


def operation(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with storage_lock(self.file_path) as outer:
            if outer:
                self._recover_operation()
            return method(self, *args, **kwargs)
    return run


def coordinated(method):
    @wraps(method)
    @operation
    def run(self, *args, **kwargs):
        if self._staged is not None:
            return method(self, *args, **kwargs)
        self._staged = {}
        try:
            result = method(self, *args, **kwargs)
            files = self._staged
        finally:
            self._staged = None
        self._commit_operation(files)
        return result
    return run


def fingerprint(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()

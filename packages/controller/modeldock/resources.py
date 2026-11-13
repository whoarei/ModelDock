"""Sample the worker's RSS without adding dependencies to the controller."""

import os
import sys
from pathlib import Path


def rss_mb(pid):
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                ] + [
                    (name, ctypes.c_size_t)
                    for name in (
                        "PeakWorkingSetSize",
                        "WorkingSetSize",
                        "QuotaPeakPagedPoolUsage",
                        "QuotaPagedPoolUsage",
                        "QuotaPeakNonPagedPoolUsage",
                        "QuotaNonPagedPoolUsage",
                        "PagefileUsage",
                        "PeakPagefileUsage",
                    )
                ]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(Counters),
                wintypes.DWORD,
            ]
            handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:
                return None
            try:
                info = Counters()
                info.cb = ctypes.sizeof(info)
                if psapi.GetProcessMemoryInfo(handle, ctypes.byref(info), info.cb):
                    return info.WorkingSetSize / 1024**2
            finally:
                kernel.CloseHandle(handle)
        elif sys.platform.startswith("linux"):
            values = (Path("/proc") / str(pid) / "statm").read_text(encoding="utf-8").split()
            return int(values[1]) * os.sysconf("SC_PAGE_SIZE") / 1024**2
    except (OSError, ValueError, IndexError):
        pass
    return None


def process_birth(pid):
    """A creation token prevents treating a recycled PID as our supervisor."""
    try:
        if sys.platform.startswith("linux"):
            text = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
            values = text[text.rfind(")") + 2 :].split()
            boot = (Path("/proc/sys/kernel/random/boot_id")).read_text(encoding="utf-8").strip()
            return None if values[0] == "Z" else boot + ":" + values[19]
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.GetProcessTimes.argtypes = [
                wintypes.HANDLE,
                *([ctypes.POINTER(wintypes.FILETIME)] * 4),
            ]
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return "unknown" if ctypes.get_last_error() == 5 else None
            try:
                exit_code = wintypes.DWORD()
                if (
                    kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                    and exit_code.value != 259
                ):
                    return None
                created, exited, kernel_time, user_time = [wintypes.FILETIME() for _ in range(4)]
                if not kernel.GetProcessTimes(
                    handle,
                    ctypes.byref(created),
                    ctypes.byref(exited),
                    ctypes.byref(kernel_time),
                    ctypes.byref(user_time),
                ):
                    return "unknown"
                return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
            finally:
                kernel.CloseHandle(handle)
    except FileNotFoundError:
        return None
    except (PermissionError, OSError, ValueError, IndexError):
        return "unknown"
    return "unknown"

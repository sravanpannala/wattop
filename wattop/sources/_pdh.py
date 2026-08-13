"""Minimal ctypes wrapper around pdh.dll.

Used for Windows performance counters. On the Snapdragon X Elite this is how the
SoC's energy-meter rails are exposed: `\\Energy Meter(*)\\Power` yields one
instance per rail (PSU_USB, SYS, USBC_TOTAL, CPU_CLUSTER_0..2, GPU) with the
cooked value in milliwatts. Measured cost is ~0.11 ms for all rails, so polling
at 1 Hz is free.

No pywin32 -- ctypes only, so this works on any Python including native ARM64.
"""

from __future__ import annotations

import ctypes as C
import time
from ctypes import wintypes as W

PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000
PDH_MORE_DATA = 0x800007D2 - 0x100000000  # returned as a negative c_long
PDH_CSTATUS_VALID_DATA = 0
PDH_CSTATUS_NEW_DATA = 1

_pdh = C.WinDLL("pdh")


class _CounterValue(C.Structure):
    _fields_ = [("CStatus", W.DWORD), ("doubleValue", C.c_double)]


class _CounterItemW(C.Structure):
    _fields_ = [("szName", C.c_wchar_p), ("FmtValue", _CounterValue)]


_pdh.PdhOpenQueryW.argtypes = [C.c_wchar_p, C.c_void_p, C.POINTER(W.HANDLE)]
_pdh.PdhAddEnglishCounterW.argtypes = [W.HANDLE, C.c_wchar_p, C.c_void_p, C.POINTER(W.HANDLE)]
_pdh.PdhCollectQueryData.argtypes = [W.HANDLE]
_pdh.PdhGetFormattedCounterArrayW.argtypes = [
    W.HANDLE,
    W.DWORD,
    C.POINTER(W.DWORD),
    C.POINTER(W.DWORD),
    C.c_void_p,
]
_pdh.PdhCloseQuery.argtypes = [W.HANDLE]


class PdhError(OSError):
    pass


class PdhWildcardQuery:
    """One counter path with a `(*)` instance wildcard, polled repeatedly.

    The query and counter handles are held open for the life of the object;
    each `read()` is a single collect plus a formatted-array fetch.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._query = W.HANDLE()
        rc = _pdh.PdhOpenQueryW(None, None, C.byref(self._query))
        if rc != 0:
            raise PdhError(f"PdhOpenQueryW failed: {rc & 0xFFFFFFFF:#x}")
        self._counter = W.HANDLE()
        # The English variant means the path keeps working on a localised
        # Windows, where the display names of counters are translated.
        rc = _pdh.PdhAddEnglishCounterW(self._query, path, None, C.byref(self._counter))
        if rc != 0:
            _pdh.PdhCloseQuery(self._query)
            raise PdhError(f"PdhAddEnglishCounterW({path!r}) failed: {rc & 0xFFFFFFFF:#x}")
        _pdh.PdhCollectQueryData(self._query)

    def read(self) -> dict[str, float]:
        """instance name -> cooked value. Empty until two samples exist."""
        rc = _pdh.PdhCollectQueryData(self._query)
        if rc != 0:
            return {}

        size = W.DWORD(0)
        count = W.DWORD(0)
        rc = _pdh.PdhGetFormattedCounterArrayW(
            self._counter, PDH_FMT_DOUBLE, C.byref(size), C.byref(count), None
        )
        if size.value == 0:
            return {}
        buf = C.create_string_buffer(size.value)
        rc = _pdh.PdhGetFormattedCounterArrayW(
            self._counter, PDH_FMT_DOUBLE, C.byref(size), C.byref(count), buf
        )
        if rc != 0:
            return {}

        items = C.cast(buf, C.POINTER(_CounterItemW))
        out: dict[str, float] = {}
        for i in range(count.value):
            item = items[i]
            if item.FmtValue.CStatus not in (PDH_CSTATUS_VALID_DATA, PDH_CSTATUS_NEW_DATA):
                continue
            if item.szName:
                out[item.szName] = item.FmtValue.doubleValue
        return out

    def prime(self, wait: float = 0.12) -> dict[str, float]:
        """Rate counters need two samples separated in time before they yield
        anything. Used once at startup to discover the instance names."""
        time.sleep(wait)
        return self.read()

    def close(self) -> None:
        if self._query:
            _pdh.PdhCloseQuery(self._query)
            self._query = W.HANDLE()

"""What the machine is doing, next to what it is drawing: CPU and memory.

Two separate sources rather than one, so a machine whose processor counterset
declines still gets a memory graph, and vice versa.

CPU is `% Processor Time`: the share of wall time the processors spent not idle.
That is what btop means by CPU percent, and what `/proc/stat` gives the Linux
source, so the number means the same thing on both platforms and agrees with
whatever else the user has open.

The tempting alternative is `% Processor Utility`, which scales the same figure
by the frequency actually delivered against nominal. It is what Task Manager
shows, and it tracks the OUT graph more closely -- measured here, this laptop
idles at about a third of its nominal clock, so Utility reads about a third of
Time for the same work. It is deliberately not the default: a CPU figure that
disagrees three-to-one with every other load meter on the machine costs more
than the tighter correlation buys, and the axis would spend its top half empty
on a part that never sustains nominal.

Memory is `GlobalMemoryStatusEx`, not a counter: nothing in the performance
counter tree reports installed physical RAM, and one call gives total and
available together for a few microseconds.
"""

from __future__ import annotations

import ctypes as C
import sys
from ctypes import wintypes as W

from wattop.core.channel import Channel
from wattop.core.registry import register

#: Not-idle time across the whole package. `_Total` is an instance of the
#: `Processor Information` counterset, so this is an ordinary instanced path with
#: the instance named rather than wildcarded.
TIME_PATH = r"\Processor Information(_Total)\% Processor Time"

#: The older `Processor` counterset, for a machine that somehow lacks the newer
#: one. It only covers processor group 0, so it undercounts a box with more than
#: 64 logical processors -- which is why it is the fallback and not the default.
LEGACY_TIME_PATH = r"\Processor(_Total)\% Processor Time"

GB = 1024.0**3

_kernel32 = C.WinDLL("kernel32", use_last_error=True)


@register
class CpuSource:
    name = "win_cpu"

    def __init__(self) -> None:
        self._query = None
        #: Last real reading, held across a stale tick. See `read`.
        self._held = 0.0

    def available(self) -> bool:
        if sys.platform != "win32":
            return False
        from wattop.sources._pdh import PdhWildcardQuery

        for path in (TIME_PATH, LEGACY_TIME_PATH):
            try:
                query = PdhWildcardQuery(path)
            except OSError:
                continue
            # A rate counter says nothing until it has two samples, and an
            # empty dict here means the counterset opened but never populated.
            values = query.prime()
            if values:
                self._query = query
                # Seed from the priming pair, so a single-shot `--list` shows a
                # number rather than a blank -- the same reason the energy meter
                # seeds its own.
                self._held = next(iter(values.values()))
                return True
            query.close()
        return False

    def channels(self) -> list[Channel]:
        return [
            Channel(
                key="cpu.util",
                label="Processor",
                unit="%",
                group="system",
                role="cpu",
                precision=0,
                nominal_max=100.0,
            )
        ]

    def read(self) -> dict[str, float]:
        if self._query is None:
            return {}
        raw = self._query.read()
        if not raw:
            return {"cpu.util": self._held}
        value = next(iter(raw.values()))
        # An exact zero is a stale tick, not an idle machine: something is
        # running this program, and the provider hands back 0.0 when two collects
        # land inside one of its update intervals -- which `-i 0.25` and the `+`
        # key both arrange. Measured: this counter does it, so the guard is not
        # theoretical.
        if value != 0.0:
            self._held = value
        return {"cpu.util": self._held}

    def close(self) -> None:
        if self._query is not None:
            self._query.close()
            self._query = None


class _MemoryStatusEx(C.Structure):
    _fields_ = [
        ("dwLength", W.DWORD),
        ("dwMemoryLoad", W.DWORD),
        ("ullTotalPhys", C.c_ulonglong),
        ("ullAvailPhys", C.c_ulonglong),
        ("ullTotalPageFile", C.c_ulonglong),
        ("ullAvailPageFile", C.c_ulonglong),
        ("ullTotalVirtual", C.c_ulonglong),
        ("ullAvailVirtual", C.c_ulonglong),
        ("ullAvailExtendedVirtual", C.c_ulonglong),
    ]


_kernel32.GlobalMemoryStatusEx.argtypes = [C.POINTER(_MemoryStatusEx)]
_kernel32.GlobalMemoryStatusEx.restype = W.BOOL


@register
class MemorySource:
    name = "win_memory"

    def __init__(self) -> None:
        self._total = 0.0

    def _status(self) -> _MemoryStatusEx | None:
        status = _MemoryStatusEx()
        status.dwLength = C.sizeof(_MemoryStatusEx)
        if not _kernel32.GlobalMemoryStatusEx(C.byref(status)):
            return None
        return status

    def available(self) -> bool:
        if sys.platform != "win32":
            return False
        status = self._status()
        if status is None or status.ullTotalPhys == 0:
            return False
        self._total = status.ullTotalPhys / GB
        return True

    def channels(self) -> list[Channel]:
        return [
            # The ceiling is installed RAM, so the axis reads 0 to whatever the
            # machine has and the top label says what "full" means. That is the
            # existing nominal_max path -- no new axis code.
            Channel(
                key="mem.used",
                label="In use",
                unit="GB",
                group="system",
                role="memory",
                precision=2,
                nominal_max=self._total,
            ),
            Channel(
                key="mem.total",
                label="Installed",
                unit="GB",
                group="system",
                precision=2,
                static=True,
            ),
        ]

    def read(self) -> dict[str, float]:
        status = self._status()
        if status is None:
            return {}
        return {
            "mem.used": (status.ullTotalPhys - status.ullAvailPhys) / GB,
            "mem.total": status.ullTotalPhys / GB,
        }

    def close(self) -> None:
        pass

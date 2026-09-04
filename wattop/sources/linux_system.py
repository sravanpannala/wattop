"""CPU and memory on Linux, from `/proc/stat` and `/proc/meminfo`.

The same two channels the Windows pair produces -- `cpu.util` and `mem.used` --
so the dashboard is identical on both platforms.

`/proc/stat`'s aggregate `cpu` line is a set of counters in jiffies since boot,
so utilisation is a delta between two reads: time not spent idle over time
elapsed. That is the same thing the Windows source's `% Processor Time` counter
reports, so a CPU percentage means one thing across both platforms.
"""

from __future__ import annotations

import sys
from pathlib import Path

from wattop.core.channel import Channel
from wattop.core.registry import register

STAT = Path("/proc/stat")
MEMINFO = Path("/proc/meminfo")

#: Fields of the aggregate `cpu` line that are not the machine doing work,
#: indexed from the first field after the label: user nice system idle
#: iowait ... -- so `idle` is 3 and `iowait` is 4.
IDLE_FIELDS = (3, 4)

#: /proc/meminfo is in kibibytes.
KIB_PER_GB = 1024.0**2


@register
class CpuSource:
    name = "linux_cpu"

    def __init__(self) -> None:
        self._prev: tuple[float, float] | None = None

    def available(self) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        # Keep the probe's snapshot: without it the first read has nothing to
        # difference against and a single-shot `--list` shows a blank. Held, the
        # first reading is the average since startup, which is what the Windows
        # counter's priming pair reports too.
        self._prev = self._totals()
        return self._prev is not None

    @staticmethod
    def _totals() -> tuple[float, float] | None:
        """(busy + idle, idle) in jiffies, or None if the line is unreadable."""
        try:
            first = STAT.read_text().split("\n", 1)[0]
        except OSError:
            return None
        parts = first.split()
        if not parts or parts[0] != "cpu" or len(parts) <= max(IDLE_FIELDS) + 1:
            return None
        try:
            fields = [float(p) for p in parts[1:]]
        except ValueError:
            return None
        idle = sum(fields[i] for i in IDLE_FIELDS)
        return sum(fields), idle

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
        totals = self._totals()
        if totals is None:
            return {}
        prev, self._prev = self._prev, totals
        if prev is None:
            return {}  # nothing to difference against yet
        span = totals[0] - prev[0]
        if span <= 0:
            return {}
        busy = span - (totals[1] - prev[1])
        return {"cpu.util": max(0.0, min(100.0, busy / span * 100.0))}

    def close(self) -> None:
        pass


@register
class MemorySource:
    name = "linux_memory"

    def __init__(self) -> None:
        self._total = 0.0

    def available(self) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        fields = self._fields()
        self._total = fields.get("MemTotal", 0.0) / KIB_PER_GB
        # MemAvailable is what the kernel thinks is obtainable without swapping,
        # which is the figure every other tool means by "free". It has been there
        # since 3.14; without it there is nothing honest to subtract.
        return self._total > 0 and "MemAvailable" in fields

    @staticmethod
    def _fields() -> dict[str, float]:
        try:
            text = MEMINFO.read_text()
        except OSError:
            return {}
        out: dict[str, float] = {}
        for line in text.splitlines():
            name, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                try:
                    out[name] = float(parts[0])
                except ValueError:
                    continue
        return out

    def channels(self) -> list[Channel]:
        return [
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
        fields = self._fields()
        total = fields.get("MemTotal")
        available = fields.get("MemAvailable")
        if total is None or available is None:
            return {}
        return {
            "mem.used": (total - available) / KIB_PER_GB,
            "mem.total": total / KIB_PER_GB,
        }

    def close(self) -> None:
        pass

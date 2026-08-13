"""RAPL package energy via the powercap sysfs interface.

`energy_uj` is a free-running microjoule counter, so power is the delta over the
elapsed time. It wraps at `max_energy_range_uj`, which is handled below.

This is root-only on most distributions -- since the PLATYPUS mitigation the
file is 0400 -- so the source checks readability and drops out silently rather
than nagging. On a machine where it is readable (a udev rule, or
`perf_event_paranoid` lowered and read through perf instead) it is a useful
CPU-only cross-check against the APU package figure from hwmon.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from wattop.core.channel import Channel
from wattop.core.registry import register

POWERCAP_ROOT = Path("/sys/class/powercap")


@register
class PowercapSource:
    name = "linux_powercap"

    def __init__(self, root: Path = POWERCAP_ROOT) -> None:
        self._root = root
        self._domains: list[tuple[str, Path, float]] = []  # key, energy file, wrap
        self._prev: dict[str, tuple[float, float]] = {}  # key -> (uj, monotonic)

    def available(self) -> bool:
        if sys.platform == "win32" or not self._root.is_dir():
            return False
        for node in sorted(self._root.glob("intel-rapl:*")):
            energy = node / "energy_uj"
            if _read_float(energy) is None:
                continue  # 0400 and we are not root
            name = _read_text(node / "name") or node.name
            wrap = _read_float(node / "max_energy_range_uj") or 0.0
            self._domains.append((f"rapl.{name}", energy, wrap))
        return bool(self._domains)

    def channels(self) -> list[Channel]:
        return [
            Channel(key, f"RAPL {key.split('.', 1)[1]}", "W", "rails", None, 2)
            for key, _path, _wrap in self._domains
        ]

    def read(self) -> dict[str, float]:
        now = time.monotonic()
        out: dict[str, float] = {}
        for key, path, wrap in self._domains:
            uj = _read_float(path)
            if uj is None:
                continue
            prev = self._prev.get(key)
            self._prev[key] = (uj, now)
            if prev is None:
                continue  # first sample only establishes a baseline
            prev_uj, prev_t = prev
            dt = now - prev_t
            if dt <= 0:
                continue
            duj = uj - prev_uj
            if duj < 0:
                if not wrap:
                    continue
                duj += wrap
            out[key] = duj / 1e6 / dt
        return out

    def close(self) -> None:
        pass


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return None


def _read_float(path: Path) -> float | None:
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None

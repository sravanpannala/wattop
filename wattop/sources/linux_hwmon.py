"""Linux hwmon -- the generic sensor tree under /sys/class/hwmon.

Everything is discovered, nothing is hardcoded: each hwmon node is walked for
power/temp/fan/voltage/current inputs, so a driver that starts exposing a new
rail after a kernel bump simply shows up.

On the Framework Desktop (Ryzen AI Max+ 395) the number that matters is the
`amdgpu` node's `power1_average` -- APU package power, the same PPT figure
ryzenadj reports, readable without root. That one gets the `power_out` role.
Note that this chip exposes no voltage or current at all: Zen 5 moved to SVI3
and no in-tree driver reads it, so `in*`/`curr*` will simply be absent there.

Deliberately not used: amd-smi / rocm-smi, which return N/A across the board on
gfx1151 while these raw sysfs files work fine.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from wattop.core.channel import Channel
from wattop.core.registry import register

HWMON_ROOT = Path("/sys/class/hwmon")

# filename pattern -> (unit, scale to that unit, group, precision)
_KINDS = (
    (re.compile(r"^power(\d+)_(average|input)$"), ("W", 1e-6, "out", 2)),
    (re.compile(r"^temp(\d+)_input$"), ("degC", 1e-3, "thermal", 1)),
    (re.compile(r"^fan(\d+)_input$"), ("RPM", 1.0, "thermal", 0)),
    (re.compile(r"^in(\d+)_input$"), ("V", 1e-3, "rails", 3)),
    (re.compile(r"^curr(\d+)_input$"), ("A", 1e-3, "rails", 3)),
    (re.compile(r"^freq(\d+)_input$"), ("MHz", 1e-6, "other", 0)),
)

#: Chip whose package-power reading is the best "what is this machine using"
#: number, in preference order.
_HEADLINE_CHIPS = ("amdgpu", "k10temp", "zenpower", "coretemp")


@register
class HwmonSource:
    name = "linux_hwmon"

    def __init__(self, root: Path = HWMON_ROOT) -> None:
        self._root = root
        self._entries: list[tuple[str, Path, float]] = []  # key, file, scale
        self._channels: list[Channel] = []

    def available(self) -> bool:
        if sys.platform == "win32" or not self._root.is_dir():
            return False
        self._discover()
        return bool(self._entries)

    def _discover(self) -> None:
        headline_taken = False
        candidates: list[tuple[str, Path, float, Channel]] = []

        for node in sorted(self._root.glob("hwmon*")):
            chip = _read_text(node / "name") or node.name
            present = {p.name for p in node.iterdir()}
            for path in sorted(node.iterdir()):
                kind = _classify(path.name)
                if kind is None:
                    continue
                unit, scale, group, precision = kind

                # amdgpu offers both power1_input and power1_average for the
                # same rail. The averaged one is the useful reading; showing
                # both just invites the question of which to believe.
                stem = path.name.split("_")[0]
                if path.name.endswith("_input") and f"{stem}_average" in present:
                    continue

                raw = _read_text(path)
                if raw is None:
                    continue
                try:
                    value = float(raw) * scale
                except ValueError:
                    continue

                # Voltage and current nodes that read a hard zero are declared
                # but unpopulated: amdgpu exposes vddgfx and vddnb on Strix Halo
                # and never fills them (Zen 5 moved to SVI3, which no in-tree
                # driver reads), and an idle USB-C port reports 0 V / 0 A. A
                # channel that will sit at 0.000 V forever is worse than absent.
                # Fans are exempt: 0 RPM means the fan is genuinely stopped.
                if unit in ("V", "A") and value == 0.0:
                    continue

                label = _read_text(node / f"{stem}_label")
                key = f"hwmon.{chip}.{path.name}"
                # Chips without a *_label file (acpitz, nvme controllers, the
                # NIC) fall back to the node name; "acpitz_0 temp1" reads better
                # than "acpitz_0 temp1_input" and loses nothing.
                nice = f"{chip} {label or stem}"
                candidates.append(
                    (key, path, scale, Channel(key, nice, unit, group, None, precision))
                )

        # Give the power_out role to the most meaningful package-power reading.
        def rank(item):
            key, _path, _scale, ch = item
            chip = key.split(".")[1]
            is_pkg_power = ch.unit == "W" and "_average" in key
            try:
                chip_rank = _HEADLINE_CHIPS.index(chip)
            except ValueError:
                chip_rank = len(_HEADLINE_CHIPS)
            return (not is_pkg_power, chip_rank, key)

        for key, path, scale, ch in sorted(candidates, key=rank):
            if not headline_taken and ch.unit == "W":
                ch = Channel(
                    ch.key, ch.label, ch.unit, "out", "power_out", ch.precision, nominal_max=140.0
                )
                headline_taken = True
            elif ch.unit == "W":
                ch = Channel(ch.key, ch.label, ch.unit, "rails", None, ch.precision)
            self._entries.append((key, path, scale))
            self._channels.append(ch)

    def channels(self) -> list[Channel]:
        return list(self._channels)

    def read(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, path, scale in self._entries:
            raw = _read_text(path)
            if raw is None:
                continue
            try:
                out[key] = float(raw) * scale
            except ValueError:
                continue
        return out

    def close(self) -> None:
        pass


def _classify(name: str):
    for pattern, kind in _KINDS:
        if pattern.match(name):
            return kind
    return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return None

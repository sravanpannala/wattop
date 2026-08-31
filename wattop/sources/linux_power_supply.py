"""Linux batteries and mains adapters, from /sys/class/power_supply.

Not used on the Framework Desktop (no battery), but this is what makes wattop
work unchanged on any Linux laptop -- and it is the same data mainline btop
reads for its watts display.

Some firmware exposes `power_now` directly; the rest only give current and
voltage, so power is the product. Sign convention here matches the Windows
source: positive means charging.
"""

from __future__ import annotations

import sys
from pathlib import Path

from wattop.core.channel import Channel
from wattop.core.registry import register

PS_ROOT = Path("/sys/class/power_supply")


@register
class PowerSupplySource:
    name = "linux_power_supply"

    def __init__(self, root: Path = PS_ROOT) -> None:
        self._root = root
        self._battery: Path | None = None
        self._mains: list[Path] = []
        self._full: float | None = None
        self._nominal_v: float | None = None

    def available(self) -> bool:
        if sys.platform == "win32" or not self._root.is_dir():
            return False
        for node in sorted(self._root.iterdir()):
            kind = _text(node / "type")
            if kind == "Battery" and self._battery is None:
                self._battery = node
            elif kind == "Mains":
                self._mains.append(node)
        if self._battery is not None:
            # `voltage_min_design` is what turns the charge-reporting flavour of
            # this interface into watt-hours; cached because it never moves.
            self._nominal_v = _num(self._battery / "voltage_min_design", 1e-6) or _num(
                self._battery / "voltage_now", 1e-6
            )
            self._full = self._energy(
                _num(self._battery / "energy_full", 1e-6),
                _num(self._battery / "charge_full", 1e-6),
            )
        return self._battery is not None or bool(self._mains)

    def _energy(self, energy: float | None, charge: float | None) -> float | None:
        """Watt-hours, from whichever of the two pairs this pack exposes.

        Only `energy_*` is already in watt-hours. `charge_*` is amp-hours, and
        was being reported as Wh -- harmless while it was just a gauge label,
        but the time-left estimate divides watt-hours by watts, and amp-hours
        divided by watts is not a time.
        """
        if energy is not None:
            return energy
        if charge is not None and self._nominal_v:
            return charge * self._nominal_v
        return None

    def channels(self) -> list[Channel]:
        out: list[Channel] = []
        if self._battery is not None:
            out += [
                Channel("batt.power", "Battery", "W", "battery", "battery_power", 2, signed=True),
                Channel("batt.voltage", "Voltage", "V", "battery", "battery_voltage", 3),
                Channel(
                    "batt.current", "Current", "A", "battery", "battery_current", 3, signed=True
                ),
                Channel(
                    "batt.charge",
                    "Charge",
                    "Wh",
                    "battery",
                    "battery_charge",
                    2,
                    nominal_max=self._full,
                ),
                Channel("batt.level", "Level", "%", "battery", "battery_level", 1, nominal_max=100.0),
            ]
            if self._full:
                out.append(
                    Channel("batt.full", "Full charge", "Wh", "battery", None, 2, static=True)
                )
            if (self._battery / "temp").exists():
                out.append(Channel("batt.temp", "Batt temp", "degC", "thermal", None, 1))
        if self._mains:
            out.append(Channel("batt.ac", "AC online", "", "battery", "ac_online", 0))
        return out

    def read(self) -> dict[str, float]:
        out: dict[str, float] = {}
        bat = self._battery
        if bat is not None:
            voltage = _num(bat / "voltage_now", 1e-6)
            current = _num(bat / "current_now", 1e-6)
            power = _num(bat / "power_now", 1e-6)
            if power is None and voltage is not None and current is not None:
                power = voltage * current
            status = _text(bat / "status") or ""
            if power is not None:
                # sysfs reports magnitude; the sign lives in `status`.
                power = -abs(power) if status == "Discharging" else abs(power)
                out["batt.power"] = power
            if voltage is not None:
                out["batt.voltage"] = voltage
                if power is not None and voltage:
                    out["batt.current"] = power / voltage
            charge = self._energy(
                _num(bat / "energy_now", 1e-6), _num(bat / "charge_now", 1e-6)
            )
            if charge is not None:
                out["batt.charge"] = charge
                if self._full:
                    out["batt.full"] = self._full
                    out["batt.level"] = 100.0 * charge / self._full
            level = _num(bat / "capacity", 1.0)
            if level is not None:
                out["batt.level"] = level
            temp = _num(bat / "temp", 0.1)
            if temp is not None:
                out["batt.temp"] = temp
        if self._mains:
            out["batt.ac"] = 1.0 if any(_text(m / "online") == "1" for m in self._mains) else 0.0
        return out

    def close(self) -> None:
        pass


def _text(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return None


def _num(path: Path, scale: float) -> float | None:
    raw = _text(path)
    if raw is None:
        return None
    try:
        return float(raw) * scale
    except ValueError:
        return None

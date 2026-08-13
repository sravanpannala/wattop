"""ACPI thermal zones, via the `Thermal Zone Information` performance counter.

`MSAcpi_ThermalZoneTemperature` in root\\wmi exists on this platform but returns
no instances, so the counter is the way in. Values are kelvin.

Qualcomm firmware declares a lot of zones and leaves many of them unpopulated,
reading a flat 0 K (-273 degC). Those are filtered at discovery so they do not
clutter the panel or drag an average around.
"""

from __future__ import annotations

import sys

from wattop.core.channel import Channel
from wattop.core.registry import register

COUNTER_PATH = r"\Thermal Zone Information(*)\Temperature"
KELVIN = 273.15

#: Anything outside this once converted is a zone the firmware never filled in.
PLAUSIBLE_C = (0.0, 130.0)


@register
class ThermalZoneSource:
    name = "win_thermal_zones"

    def __init__(self, counter_path: str = COUNTER_PATH) -> None:
        self._path = counter_path
        self._query = None
        self._zones: list[str] = []

    def available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            from wattop.sources._pdh import PdhWildcardQuery

            query = PdhWildcardQuery(self._path)
        except OSError:
            return False

        values = query.prime()
        self._zones = sorted(n for n, v in values.items() if _plausible(v - KELVIN))
        if not self._zones:
            query.close()
            return False
        self._query = query
        return True

    def channels(self) -> list[Channel]:
        return [
            Channel(
                key=f"tz.{_short(zone)}",
                label=_short(zone),
                unit="degC",
                group="thermal",
                precision=1,
            )
            for zone in self._zones
        ]

    def read(self) -> dict[str, float]:
        if self._query is None:
            return {}
        raw = self._query.read()
        out: dict[str, float] = {}
        for zone in self._zones:
            kelvin = raw.get(zone)
            if kelvin is None:
                continue
            celsius = kelvin - KELVIN
            if _plausible(celsius):
                out[f"tz.{_short(zone)}"] = celsius
        return out

    def close(self) -> None:
        if self._query is not None:
            self._query.close()
            self._query = None


def _plausible(celsius: float) -> bool:
    return PLAUSIBLE_C[0] <= celsius <= PLAUSIBLE_C[1]


def _short(zone: str) -> str:
    """`\\_SB.TZ31` -> `TZ31`."""
    return zone.rsplit(".", 1)[-1] or zone

"""Windows energy-meter rails, via the `Energy Meter` performance counters.

On a Snapdragon X Elite laptop this is the good stuff: Windows surfaces the
platform's EMI (Energy Meter Interface) channels as an ordinary multi-instance
perf counter, so the charger input rail is directly measurable rather than
estimated. Measured on a Yoga Slim 7 14Q8X9 while charging:

    PSU_USB       59.4 W   <- power in, from the USB-C charger
    SYS           16.6 W   <- system rail
    USBC_TOTAL     9.3 W
    CPU_CLUSTER_0  1.35 W   CPU_CLUSTER_1 0.94 W   CPU_CLUSTER_2 0.59 W   GPU 0.07 W

Values are milliwatts. `_Total` reads zero on that hardware and is skipped.

Whether any of this exists is a platform question, not a Windows-version one --
`available()` simply reports whether the counter resolved to real instances, so
on a machine with no EMI provider the source drops out and nothing else notices.
"""

from __future__ import annotations

import sys

from wattop.core.channel import Channel
from wattop.core.registry import register

COUNTER_PATH = r"\Energy Meter(*)\Power"

#: Rails whose meaning we know, so they can be headlined rather than dumped in
#: with the rest. Anything not listed here lands in "rails" and still shows up.
_KNOWN = {
    "PSU_USB": ("Charger in", "in", "power_in", 100.0),
    "SYS": ("System", "out", "power_out", 60.0),
}
_SKIP = {"_total"}


@register
class EnergyMeterSource:
    name = "win_energy_meter"

    def __init__(self, counter_path: str = COUNTER_PATH) -> None:
        self._path = counter_path
        self._query = None
        self._instances: list[str] = []
        self._held: dict[str, float] = {}

    def available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            from wattop.sources._pdh import PdhWildcardQuery

            query = PdhWildcardQuery(self._path)
        except OSError:
            return False

        # Rate counters yield nothing until a second sample exists, so this
        # also doubles as instance discovery.
        values = query.prime()
        names = [n for n in values if n.lower() not in _SKIP]
        if not names:
            query.close()
            return False
        self._query = query
        self._instances = sorted(names, key=_display_order)
        # Seed the held values from the priming pair, so the very first read()
        # has real numbers even if it lands before the counter next advances.
        # Without this, a single-shot `--list` can show blanks, and anything
        # derived from these rails cannot be computed at all.
        self._held = {f"emi.{n}": values[n] / 1000.0 for n in names}
        return True

    def channels(self) -> list[Channel]:
        out = []
        for inst in self._instances:
            label, group, role, nominal = _KNOWN.get(inst, (inst, "rails", None, None))
            out.append(
                Channel(
                    key=f"emi.{inst}",
                    label=label,
                    unit="W",
                    group=group,
                    role=role,
                    precision=2,
                    nominal_max=nominal,
                )
            )
        return out

    def read(self) -> dict[str, float]:
        if self._query is None:
            return {}
        raw = {k: v for k, v in self._query.read().items() if k.lower() not in _SKIP}
        if not raw:
            return dict(self._held)

        # The firmware advances these counters about once a second. Poll faster
        # than that and PDH divides a zero energy delta by the elapsed time and
        # hands back 0 W for every rail at once -- which would read as "the
        # charger stopped" rather than "no new data yet". A genuine all-zero is
        # not a thing on a running machine (SYS is never 0), so treat it as a
        # stale tick and hold the last real numbers.
        #
        # Cross-checked against deriving watts from the cumulative
        # `\Energy Meter(*)\Energy` counter instead: once settled the two agree
        # to 0.01 W, so the Power counter is right and only the gaps are wrong.
        if all(v == 0.0 for v in raw.values()):
            return dict(self._held)

        self._held = {f"emi.{name}": mw / 1000.0 for name, mw in raw.items()}
        return dict(self._held)

    def close(self) -> None:
        if self._query is not None:
            self._query.close()
            self._query = None


def _display_order(name: str) -> tuple[int, str]:
    """Charger first, then the system rail, then everything else."""
    order = {"PSU_USB": 0, "SYS": 1, "USBC_TOTAL": 2}
    return (order.get(name, 3), name)

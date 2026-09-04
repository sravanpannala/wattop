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
#: with the rest. Anything not listed here lands in "rails" and still shows up,
#: so an unrecognised name costs a nice label and nothing else.
#:
#: `nominal_max` is deliberately absent for everything but the two rails
#: measured on the reference laptop: the graph ladder picks a sensible axis on
#: its own, and a guessed ceiling is worse than none on hardware we have not
#: seen. Set one yourself with `[overrides."emi.<rail>"] nominal_max`.
_KNOWN = {
    # Qualcomm Snapdragon X. PSU_USB and SYS are measured on a Yoga Slim 7
    # 14Q8X9; the rest are named in Qualcomm's own libqcperf, which reads this
    # same counter path, and are labelled here on that basis.
    "PSU_USB": ("Charger in", "in", "power_in", 60.0),
    "SYS": ("System", "out", "power_out", 60.0),
    "USBC_TOTAL": ("USB-C total", "rails", None, None),
    "SOC": ("SoC", "rails", None, None),
    "NPU": ("NPU", "rails", None, None),
    "GPU": ("GPU", "rails", None, None),
    "MEMORY": ("Memory", "rails", None, None),
    "INFRA": ("Infrastructure", "rails", None, None),
    "MULTIMEDIA": ("Multimedia", "rails", None, None),
    "ROP": ("ROP", "rails", None, None),
}

#: x86 Windows 11 exposes RAPL through this same counterset, under names shaped
#: `RAPL_Package<n>_<DOMAIN>` and `RAPL_Package<n>_Core<m>_CORE`. Matching the
#: domain suffix rather than the whole string keeps this working on a two-socket
#: box without listing every index.
#:
#: UNVERIFIED: named from documentation, not measured -- the development machine
#: is ARM64 and has no RAPL. If the names are wrong the rails still appear under
#: their raw names in the `rails` group, which is what happens today, so this is
#: strictly an improvement or a no-op. Do not claim x86 support until someone
#: has run it on one.
_RAPL_DOMAINS = {
    # The whole package: the closest x86 equivalent of Snapdragon's SYS, and the
    # only one worth headlining.
    "PKG": ("CPU package", "out", "power_out", None),
    "PP0": ("CPU cores", "rails", None, None),
    "PP1": ("Integrated GPU", "rails", None, None),
    "DRAM": ("Memory", "rails", None, None),
    "PSYS": ("Platform", "rails", None, None),
    # Per-core rails (`RAPL_Package0_Core0_CORE`) are left alone deliberately:
    # any label built from the domain would repeat the index already in the
    # name, and the raw name reads perfectly well in the rails panel.
}

_SKIP = {"_total"}


def _classify(instance: str) -> tuple[str, str, str | None, float | None]:
    """Label, group, role and axis ceiling for one rail instance."""
    known = _KNOWN.get(instance)
    if known is not None:
        return known

    if instance.upper().startswith("RAPL_"):
        parts = instance.split("_")
        domain = _RAPL_DOMAINS.get(parts[-1].upper())
        if domain is not None:
            label, group, role, nominal = domain
            # Keep the package and core index in the label, so a two-socket
            # machine does not show four rails all called "CPU cores".
            qualifier = " ".join(p for p in parts[1:-1] if p)
            return (f"{label} {qualifier}".strip() if qualifier else label,
                    group, role, nominal)

    # Measured on the reference laptop: CPU_CLUSTER_0/1/2 are the three
    # Snapdragon core clusters. Matched by prefix so a chip with more of them
    # needs no change here.
    if instance.upper().startswith("CPU_CLUSTER_"):
        return (f"CPU cluster {instance.rsplit('_', 1)[-1]}", "rails", None, None)

    return (instance, "rails", None, None)


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
        taken: set[str] = set()
        for inst in self._instances:
            label, group, role, nominal = _classify(inst)
            # A two-socket machine has a PKG rail per socket. Only the first can
            # headline; the rest stay rails, which is where they belong anyway.
            if role is not None and role in taken:
                label, group, role, nominal = (label, "rails", None, None)
            elif role is not None:
                taken.add(role)
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

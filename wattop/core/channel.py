"""The two types every source speaks in.

A `Channel` is the static description of one readable value; a `Source` produces
values for the channels it declares. The UI never names a channel directly -- it
lays out by `group` and headlines whatever fills each `role`. That is what lets
one program cover a Snapdragon laptop and an AMD desktop without branching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Panels, in display order. A group with no channels is simply not drawn.
GROUPS = ("in", "out", "battery", "rails", "thermal", "other")

# Semantic slots the UI headlines. At most one channel fills each; if two
# sources claim the same role the first one registered wins.
ROLES = (
    "power_in",  # what the machine draws from the wall / charger
    "power_out",  # what the machine itself is consuming
    "battery_power",  # signed: positive charging, negative discharging
    "battery_voltage",
    "battery_current",
    "battery_charge",  # remaining energy
    "battery_level",  # percent
    "battery_eta",  # signed seconds: positive to empty, negative to full
    "ac_online",
    "temperature",  # the sensor worth watching, usually the hottest one
)


@dataclass(frozen=True)
class Channel:
    """Static description of one readable value."""

    key: str
    label: str
    unit: str  # "W" | "V" | "A" | "Wh" | "degC" | "%" | "RPM" | "Hz" | ""
    group: str = "other"
    role: str | None = None
    precision: int = 2
    #: Upper bound for gauge rendering. None means "scale to what we have seen".
    nominal_max: float | None = None
    #: Set for values that never change during a run (design capacity, cycles).
    static: bool = False
    #: Show an explicit sign. Battery power and current are the reason this
    #: exists: "+33 W" and "-12 W" are different situations, and "33 W" hides it.
    signed: bool = False

    def format(self, value: float | None) -> str:
        if value is None:
            return "--"
        spec = "+" if self.signed else ""
        return f"{value:{spec}.{self.precision}f} {self.unit}".rstrip()


@runtime_checkable
class Source(Protocol):
    """Anything that can produce readings.

    Adding a new kind of reading means writing one of these and decorating it
    with `@register`. Nothing in the UI needs to change.
    """

    name: str

    def available(self) -> bool:
        """Cheap probe. Returning False makes wattop skip this source silently."""

    def channels(self) -> list[Channel]:
        """Discovered once, after `available()` has returned True."""

    def read(self) -> dict[str, float]:
        """key -> value, already converted to the unit the Channel declares."""

    def close(self) -> None:
        ...

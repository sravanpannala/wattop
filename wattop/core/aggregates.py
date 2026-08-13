"""Built-in channels computed across whatever a machine turned out to have.

These cannot be declared up front the way a source's channels can, because they
depend on what discovery found. The hottest-sensor channel is the motivating
case: this laptop reports a dozen usable ACPI zones plus a battery pack sensor,
the Framework box reports `amdgpu` and `k10temp`, and neither list is knowable
before probing. Aggregating gives a stable series to graph either way.
"""

from __future__ import annotations

from wattop.core.channel import Channel
from wattop.core.sampler import DerivedChannel, Sampler

HOTTEST_KEY = "thermal.max"


def attach_builtin_aggregates(sampler: Sampler) -> None:
    _attach_hottest(sampler)


def _attach_hottest(sampler: Sampler) -> None:
    sources = [
        ch.key
        for ch in sampler.channels.values()
        if ch.unit == "degC" and not ch.static and ch.key != HOTTEST_KEY
    ]
    if not sources:
        return

    def hottest(sample: dict[str, float]) -> float | None:
        seen = [sample[k] for k in sources if k in sample]
        return max(seen) if seen else None

    label = "Hottest sensor" if len(sources) > 1 else sampler.channels[sources[0]].label
    sampler.add_derived(
        DerivedChannel(
            channel=Channel(
                key=HOTTEST_KEY,
                label=label,
                unit="degC",
                group="thermal",
                role="temperature",
                precision=1,
            ),
            evaluate=hottest,
        )
    )

"""The channels computed across whatever a machine turned out to have.

Mostly the battery time-left estimator, which averages watts and divides once
rather than averaging the firmware's own per-sample estimate. These tests drive
it against a fake clock, because the whole design turns on durations rather than
sample counts. The fastest-fan aggregate at the end needs no clock: it is a max
over whatever RPM channels discovery found.
"""

from __future__ import annotations

import pytest

from wattop.core import aggregates
from wattop.core.aggregates import (
    ETA_CEILING_S,
    ETA_WARMUP,
    FASTEST_FAN_KEY,
    _EtaEstimator,
    attach_builtin_aggregates,
)
from wattop.core.channel import Channel
from wattop.core.sampler import Sampler


class FakeClock:
    """monotonic and wall advance together unless a test says otherwise."""

    def __init__(self) -> None:
        self.mono = 1_000.0
        self.wall = 1_700_000_000.0

    def advance(self, seconds: float, wall_extra: float = 0.0) -> None:
        self.mono += seconds
        self.wall += seconds + wall_extra


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(aggregates.time, "monotonic", lambda: c.mono)
    monkeypatch.setattr(aggregates.time, "time", lambda: c.wall)
    return c


def make(window: float = 300.0, full: float | None = 60.0) -> _EtaEstimator:
    return _EtaEstimator(
        power_key="batt.power",
        charge_key="batt.charge",
        full=full,
        ac_key="batt.ac",
        window=window,
    )


def feed(est, clock, watts, charge, ticks, step=1.0, ac=0.0):
    out = None
    for _ in range(ticks):
        out = est({"batt.power": watts, "batt.charge": charge, "batt.ac": ac})
        clock.advance(step)
    return out


def test_returns_nothing_before_the_warmup_has_elapsed(clock):
    est = make()
    assert feed(est, clock, -30.0, 30.0, ticks=int(ETA_WARMUP) - 2) is None


def test_steady_discharge_gives_charge_over_watts(clock):
    """30 Wh left at a steady 30 W is one hour."""
    est = make()
    eta = feed(est, clock, -30.0, 30.0, ticks=40)
    assert eta == pytest.approx(3600.0, rel=0.05)


def test_discharge_is_positive_and_charge_is_negative(clock):
    """One channel carries both, the way battery power carries its direction."""
    assert feed(make(), clock, -30.0, 30.0, ticks=40) > 0
    assert feed(make(full=60.0), clock, 30.0, 30.0, ticks=40, ac=1.0) < 0


def test_time_to_full_uses_the_headroom_not_the_charge(clock):
    """30 Wh into a 60 Wh pack at 30 W is one hour to full."""
    eta = feed(make(full=60.0), clock, 30.0, 30.0, ticks=40, ac=1.0)
    assert eta == pytest.approx(-3600.0, rel=0.05)


def test_a_full_pack_reports_nothing(clock):
    assert feed(make(full=30.0), clock, 30.0, 30.0, ticks=40, ac=1.0) is None


def test_sitting_on_ac_at_idle_reports_nothing(clock):
    """Neither filling nor draining is not an ETA."""
    assert feed(make(), clock, 0.0, 30.0, ticks=40, ac=1.0) is None


def test_an_absurdly_long_estimate_is_withheld(clock):
    """A near-zero draw would otherwise read as a week of runtime."""
    eta = feed(make(), clock, -0.06, 40.0, ticks=40)
    assert eta is None or abs(eta) < ETA_CEILING_S


def test_direction_flip_discards_the_old_window(clock):
    """Plugging in mid-discharge must not leave discharge data deciding how
    fast the pack is filling."""
    est = make(full=60.0)
    feed(est, clock, -30.0, 30.0, ticks=40)
    first = est({"batt.power": 30.0, "batt.charge": 30.0, "batt.ac": 1.0})
    assert first is None  # window was reset, so it is warming up again


def test_a_charge_jump_discards_the_window(clock):
    est = make()
    feed(est, clock, -30.0, 30.0, ticks=40)
    assert est({"batt.power": -30.0, "batt.charge": 45.0, "batt.ac": 0.0}) is None


def test_a_suspend_discards_the_window(clock):
    """Wall clock outrunning monotonic is the machine having been asleep."""
    est = make()
    feed(est, clock, -30.0, 30.0, ticks=40)
    clock.advance(1.0, wall_extra=600.0)
    assert est({"batt.power": -30.0, "batt.charge": 30.0, "batt.ac": 0.0}) is None


def test_a_long_pause_discards_the_window(clock):
    """The UI stops sampling; the machine does not stop drawing."""
    est = make()
    feed(est, clock, -30.0, 30.0, ticks=40)
    clock.advance(120.0)
    assert est({"batt.power": -30.0, "batt.charge": 30.0, "batt.ac": 0.0}) is None


def test_missing_inputs_yield_nothing(clock):
    est = make()
    assert est({"batt.charge": 30.0}) is None
    assert est({"batt.power": -30.0}) is None


def test_averaging_watts_survives_a_spike_that_would_wreck_an_eta_mean(clock):
    """Time left is hyperbolic in power: one near-idle sample is an absurd ETA
    that would dominate a mean of ETAs, but is unremarkable in a mean of watts."""
    est = make()
    feed(est, clock, -30.0, 30.0, ticks=30)
    est({"batt.power": -0.2, "batt.charge": 30.0, "batt.ac": 0.0})
    clock.advance(1.0)
    eta = feed(est, clock, -30.0, 30.0, ticks=10)
    assert eta == pytest.approx(3600.0, rel=0.15)


class Fans:
    """A source with however many tachometers the test asks for.

    Modelled on hwmon, which is where these come from: RPM in the thermal group,
    no role of their own, whole numbers.
    """

    name = "fans"

    def __init__(
        self,
        rpm: dict[str, float],
        labels: dict[str, str] | None = None,
        maxima: dict[str, float] | None = None,
    ) -> None:
        self._rpm = rpm
        self._labels = labels or {}
        #: Per-fan declared top speed, as hwmon's `fanN_max` gives it. Absent for
        #: a tachometer whose driver publishes no maximum, which is most of them.
        self._maxima = maxima or {}

    def available(self) -> bool:
        return True

    def channels(self) -> list[Channel]:
        return [
            Channel(
                key,
                self._labels.get(key, key),
                "RPM",
                "thermal",
                None,
                0,
                nominal_max=self._maxima.get(key),
            )
            for key in self._rpm
        ]

    def read(self) -> dict[str, float]:
        return dict(self._rpm)

    def close(self) -> None:
        pass


def sampler_with(source) -> Sampler:
    s = Sampler(sources=[source], derived=[], history_len=60, overrides={})
    attach_builtin_aggregates(s)
    return s


def test_the_fastest_fan_reports_the_highest_reading_of_several():
    s = sampler_with(Fans({"fan1": 1200.0, "fan2": 3100.0, "fan3": 0.0}))
    assert s.sample().values[FASTEST_FAN_KEY] == 3100.0


def test_several_fans_are_labelled_as_the_fastest_rather_than_by_name():
    """Which of three EC fans is currently leading changes sample to sample; the
    channel's own name must not."""
    s = sampler_with(Fans({"fan1": 1200.0, "fan2": 3100.0, "fan3": 900.0}))
    assert s.channels[FASTEST_FAN_KEY].label == "Fastest fan"
    assert s.channels[FASTEST_FAN_KEY].role == "fan"
    assert s.channels[FASTEST_FAN_KEY].unit == "RPM"


def test_a_single_fan_keeps_its_own_label():
    """Calling it the fastest would be a fiction on a machine that has one."""
    s = sampler_with(Fans({"fan1": 1823.0}, labels={"fan1": "CPU fan"}))
    assert s.channels[FASTEST_FAN_KEY].label == "CPU fan"
    assert s.sample().values[FASTEST_FAN_KEY] == 1823.0


def test_the_declared_ceiling_is_the_highest_any_of_the_fans_can_reach():
    """The fastest fan can be any of them, so the series tops out at the fastest
    ceiling among them."""
    s = sampler_with(
        Fans(
            {"fan1": 1200.0, "fan2": 3100.0},
            maxima={"fan1": 4400.0, "fan2": 5200.0},
        )
    )
    assert s.channels[FASTEST_FAN_KEY].nominal_max == 5200.0


def test_one_fan_without_a_declared_ceiling_leaves_the_aggregate_unknown():
    """A tachometer with no published maximum could out-spin the figure, and an
    axis ceiling a reading can exceed is worse than no ceiling at all."""
    s = sampler_with(Fans({"fan1": 1200.0, "fan2": 3100.0}, maxima={"fan1": 4400.0}))
    assert s.channels[FASTEST_FAN_KEY].nominal_max is None


def test_a_fanless_machine_gets_no_fan_channel():
    """No channel means no role, and the UI draws no FAN graph."""
    s = sampler_with(Fans({}))
    assert FASTEST_FAN_KEY not in s.channels
    assert s.role("fan") is None


def test_a_stopped_fan_is_a_reading_not_an_absence():
    """0 RPM means the machine is cool enough to coast -- worth seeing, and
    distinct from having no tachometer at all."""
    s = sampler_with(Fans({"fan1": 0.0}))
    assert s.sample().values[FASTEST_FAN_KEY] == 0.0

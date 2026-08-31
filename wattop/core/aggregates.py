"""Built-in channels computed across whatever a machine turned out to have.

These cannot be declared up front the way a source's channels can, because they
depend on what discovery found. The hottest-sensor channel is the motivating
case: this laptop reports a dozen usable ACPI zones plus a battery pack sensor,
the Framework box reports `amdgpu` and `k10temp`, and neither list is knowable
before probing. Aggregating gives a stable series to graph either way.

The battery ETA is the second: it needs both a charge and a power reading, which
only some machines have, and it needs history, which no source keeps.
"""

from __future__ import annotations

import time
from collections import deque

from wattop.core.channel import Channel
from wattop.core.sampler import DerivedChannel, Sampler

HOTTEST_KEY = "thermal.max"

#: Deliberately not "battery.eta": the Windows source's raw firmware reading is
#: `batt.eta`, and a key two characters away from it would read as a typo
#: forever. This one says what it is -- the averaged one.
ETA_KEY = "batt.eta.avg"

#: How far back the rate average reaches, in seconds. The window *grows* to this
#: from the last plug/unplug and rolls afterwards, so an estimate appears within
#: seconds and steadies as the window fills. Five minutes is long enough to ride
#: out the 15-25 W breathing of an idle machine, and short enough that settling
#: into a game shows up while you are still noticing you started one.
DEFAULT_ETA_WINDOW = 300.0

#: No estimate until the buffer spans this much time. Below it the mean is only
#: a couple of samples wide and would reproduce the jitter under a new name.
ETA_WARMUP = 10.0

#: Rates inside this band count as "neither charging nor discharging" -- the same
#: threshold the battery line uses to pick its state word.
ETA_IDLE_W = 0.05

#: Wider band for deciding *direction*, because that decision throws data away.
#: A machine sitting full on AC hovers either side of zero, and classifying on
#: the bare sign would wipe minutes of accumulated window several times a minute.
#: The state word at `app.py` can flicker harmlessly at 0.05 W; this cannot.
ETA_DIRECTION_W = 0.5

#: Beyond this the answer is arithmetic, not information: at a hair above the
#: idle band a full pack "lasts" weeks. Nothing here runs unattended that long.
ETA_CEILING_S = 48 * 3600.0

#: A charge reading that moves by more than this in one sample is not drain --
#: it is a resume, a pack swap (`_refresh_tag` in the Windows source exists
#: because that happens), or a recalibration. The window before it describes a
#: different battery.
ETA_JUMP_WH = 2.0

#: How many times the recent sample gap counts as a hole rather than a tick.
#: Loose enough that `+`/`-` doubling the interval is not mistaken for one.
ETA_GAP_FACTOR = 5.0

#: Wall clock outrunning the monotonic clock by this much means the machine was
#: suspended. Needed because neither clock reports it alone: Windows'
#: GetTickCount64, which backs time.monotonic() there, stops during S3 exactly
#: like CLOCK_MONOTONIC does on Linux -- so a three-hour sleep arrives looking
#: like an ordinary one-second tick against a charge level that moved 20%.
ETA_SUSPEND_S = 5.0


def attach_builtin_aggregates(sampler: Sampler, eta_window: float = DEFAULT_ETA_WINDOW) -> None:
    _attach_hottest(sampler)
    _attach_eta(sampler, eta_window)


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


class _EtaEstimator:
    """Battery time left, from watts averaged over a growing window.

    Windows' own BatteryEstimatedTime is computed from the instantaneous rate,
    and on this machine that rate breathes between roughly 15 and 25 W while
    merely idling -- so the estimate swings by hours, once a second, and is
    unusable as a number to read.

    The fix is to average the *rate* and divide once, rather than to average the
    estimate. Time left is hyperbolic in power: one near-idle sample is an
    absurd ETA that dominates a mean of ETAs, but an unremarkable figure in a
    mean of watts. Averaging watts also keeps the answer honest when the load
    genuinely changes -- the mean moves, and the ETA moves with it.

    Rate rather than the charge delta across the window, because rate is
    reported every sample in milliwatts while capacity on many packs steps in
    whole percent. Over five minutes that is two or three steps, and the answer
    would quantise into visible jumps -- the very thing being fixed here.

    The result is signed: positive is seconds to empty, negative is seconds to
    full. One channel carries both because the situations are exclusive, and
    because battery power already carries its direction the same way.

    Two honest limits, neither of which any other OS handles either. Charging
    tapers hard once constant-current gives way to constant-voltage, so a "to
    full" figure averaged during the fast part reads optimistic near the top.
    And on a machine with charge limiting on -- a Lenovo capped at 60% is the
    case at hand -- the pack stops well short of `full`, so the countdown aims
    at a target it will never reach; the rate collapsing into the idle band is
    what eventually withdraws the estimate.
    """

    def __init__(
        self,
        power_key: str,
        charge_key: str,
        full: float | None,
        ac_key: str | None,
        window: float,
    ) -> None:
        self._power_key = power_key
        self._charge_key = charge_key
        self._full = full
        self._ac_key = ac_key
        self._window = window
        #: (timestamp, watts, seconds this sample stands for).
        self._buf: deque[tuple[float, float, float]] = deque()
        #: Last direction seen, as -1 discharging / +1 charging / 0 unknown.
        self._dir = 0
        self._ac: float | None = None
        self._charge: float | None = None
        self._mono: float | None = None
        self._wall: float | None = None
        #: Gap between the last two samples, which is how a hole gets
        #: recognised: the poll interval is whatever the user last set it to.
        self._gap: float | None = None

    def reset(self) -> None:
        self._buf.clear()

    def __call__(self, values: dict[str, float]) -> float | None:
        watts = values.get(self._power_key)
        charge = values.get(self._charge_key)
        if watts is None or charge is None:
            return None

        # Both clocks read here rather than taken from Sample.t: evaluate is
        # handed only the values dict, monotonic is the right clock for a
        # duration, and the pair of them is what detects a suspend. A window
        # counted in *samples* would be wrong anyway -- `+` and `-` rebind the
        # interval between 0.1 s and 60 s while the app runs, so the same 300
        # samples would mean anything from half a minute to five hours.
        now = time.monotonic()
        wall = time.time()

        dt = 0.0
        if self._mono is not None and self._wall is not None:
            dt = max(0.0, now - self._mono)
            slept = (wall - self._wall) - dt > ETA_SUSPEND_S
            # A pause (the UI stops sampling; the machine does not stop drawing)
            # leaves a hole that one stale sample would otherwise stand across.
            # Measured against the recent gap rather than any fixed number of
            # seconds: `-` takes the interval up to 60 s, where a flat threshold
            # would read every ordinary tick as a pause and the estimate would
            # never survive long enough to appear.
            paused = dt > max(ETA_WARMUP, ETA_GAP_FACTOR * (self._gap or dt))
            if slept or paused:
                self.reset()
                dt = 0.0
            else:
                self._gap = dt
        self._mono, self._wall = now, wall

        if self._charge is not None and abs(charge - self._charge) > ETA_JUMP_WH:
            self.reset()
            dt = 0.0
        self._charge = charge

        # Hold the previous direction inside the dead zone rather than flipping
        # on the bare sign -- see ETA_DIRECTION_W.
        direction = (
            1 if watts > ETA_DIRECTION_W else -1 if watts < -ETA_DIRECTION_W else self._dir
        )
        ac = values.get(self._ac_key) if self._ac_key else None
        # Plugging in mid-discharge would otherwise leave five minutes of
        # discharge data deciding how fast the pack is filling.
        if direction != self._dir or (ac is not None and self._ac is not None and ac != self._ac):
            self.reset()
            dt = 0.0
        self._dir = direction
        self._ac = ac

        self._buf.append((now, watts, dt))
        cutoff = now - self._window
        while self._buf and self._buf[0][0] < cutoff:
            self._buf.popleft()

        # Average whatever the buffer holds, which below the cap is everything
        # since the last reset -- the window extends rather than starting full.
        if now - self._buf[0][0] < ETA_WARMUP:
            return None
        # Weighted by the time each sample stands for, not by sample count. The
        # interval is rebindable mid-run, and a plain mean would let a stretch
        # sampled at 0.1 s outvote eight times as much wall time sampled at 1 s.
        span = sum(d for _, _, d in self._buf)
        if span <= 0:
            return None
        mean = sum(w * d for _, w, d in self._buf) / span

        if mean < -ETA_IDLE_W:
            seconds = charge / -mean * 3600.0
        elif mean > ETA_IDLE_W and self._full:
            headroom = self._full - charge
            if headroom <= 0:
                return None  # already full, or a freshly recalibrated pack
            seconds = -(headroom / mean * 3600.0)
        else:
            return None  # sitting on AC, neither filling nor draining

        return seconds if abs(seconds) < ETA_CEILING_S else None


def _attach_eta(sampler: Sampler, window: float) -> None:
    power = sampler.role("battery_power")
    charge = sampler.role("battery_charge")
    # Packs reporting BATTERY_CAPACITY_RELATIVE give percentages with no unit
    # behind them, so the Windows source drops both of these and there is
    # nothing to divide. Desktops have neither. Either way: no channel, and the
    # battery line falls back to whatever the firmware says.
    if power is None or charge is None:
        return

    ac = sampler.role("ac_online")
    # Both battery sources already hand the charge channel its full capacity as
    # the gauge ceiling, so "to full" needs no extra reading and no new role.
    # On a machine with two packs this describes the first one only, as every
    # other role lookup here does.
    estimator = _EtaEstimator(
        power_key=power.key,
        charge_key=charge.key,
        full=charge.nominal_max,
        ac_key=ac.key if ac else None,
        window=window,
    )
    sampler.add_derived(
        DerivedChannel(
            channel=Channel(
                key=ETA_KEY,
                label="Time left",
                unit="s",
                group="battery",
                # The raw `batt.eta` is deliberately role-less, so this one owns
                # the slot -- source channels register before derived ones and
                # `role()` returns the first match, which would otherwise
                # permanently shadow the smoothed value with the jumpy one.
                role="battery_eta",
                precision=0,
                signed=True,
            ),
            evaluate=estimator,
        )
    )

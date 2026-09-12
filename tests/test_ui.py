"""The dashboard, driven headlessly.

These build the real app against a fake source, so they run identically on a
machine with no sensors at all -- which is also the case CI runs in.
"""

from __future__ import annotations

import pytest

from wattop.core.channel import Channel
from wattop.core.sampler import Sampler
from wattop.ui.app import DETAIL_GROUPS, WattopApp

pytest_plugins = ("pytest_asyncio",)


class FakeSource:
    """Enough channels to fill every headline role plus both detail groups."""

    name = "fake"

    def __init__(self) -> None:
        self._t = 0.0

    def available(self) -> bool:
        return True

    def channels(self) -> list[Channel]:
        return [
            Channel("in.psu", "Charger", "W", "in", "power_in", 2, nominal_max=60.0),
            Channel("out.sys", "System", "W", "out", "power_out", 2, nominal_max=60.0),
            Channel("batt.power", "Battery", "W", "battery", "battery_power", 2, signed=True),
            Channel("batt.level", "Level", "%", "battery", "battery_level", 1),
            Channel("cpu.util", "Processor", "%", "system", "cpu", 0, nominal_max=100.0),
            Channel("mem.used", "In use", "GB", "system", "memory", 2, nominal_max=16.0),
            Channel("rail.gpu", "GPU rail", "W", "rails", None, 2),
            Channel("rail.npu", "NPU rail", "W", "rails", None, 2),
            Channel("temp.soc", "SoC", "degC", "thermal", "temperature", 1),
        ]

    def read(self) -> dict[str, float]:
        self._t += 1.0
        return {
            "in.psu": 50.0, "out.sys": 14.0 + self._t % 5, "batt.power": -12.0,
            "batt.level": 47.0, "cpu.util": 15.0 + self._t % 10, "mem.used": 9.0,
            "rail.gpu": 2.5, "rail.npu": 0.4, "temp.soc": 61.0,
        }

    def close(self) -> None:
        pass


@pytest.fixture
def sampler() -> Sampler:
    return Sampler(sources=[FakeSource()], derived=[], history_len=60, overrides={})


def make_app(sampler, **kw) -> WattopApp:
    return WattopApp(sampler=sampler, interval=0.1, **kw)


@pytest.mark.asyncio
async def test_dashboard_starts_and_draws_every_headline(sampler):
    app = make_app(sampler)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        roles = {g.role for g in app._graphs}
        assert roles == {"power_in", "power_out", "battery_power", "cpu", "memory", "temperature"}


@pytest.mark.asyncio
async def test_detail_panels_start_closed_and_cost_no_rows(sampler):
    app = make_app(sampler)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        assert set(app._detail_rows) == set(DETAIL_GROUPS) & set(app._panels)
        for heading, panel in app._detail_rows.values():
            assert heading.region.height == 0
            assert panel.region.height == 0


@pytest.mark.asyncio
async def test_s_opens_and_closes_the_detail_panels(sampler):
    app = make_app(sampler)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        assert all(p.region.height > 0 for _, p in app._detail_rows.values())
        assert "rails" in app._visible_panels()

        await pilot.press("s")
        await pilot.pause()
        assert all(p.region.height == 0 for _, p in app._detail_rows.values())
        assert "rails" not in app._visible_panels()


@pytest.mark.asyncio
async def test_show_details_starts_them_open(sampler):
    app = make_app(sampler, show_details=True)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        assert all(p.region.height > 0 for _, p in app._detail_rows.values())


@pytest.mark.asyncio
async def test_pause_stops_sampling_and_resumes(sampler):
    app = make_app(sampler)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert app.paused is True
        await pilot.press("p")
        await pilot.pause()
        assert app.paused is False


@pytest.mark.asyncio
async def test_plus_and_minus_rebind_the_interval(sampler):
    app = WattopApp(sampler=sampler, interval=1.0)   # not the 0.1 floor
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        start = app.interval
        await pilot.press("+")
        await pilot.pause()
        assert app.interval < start
        await pilot.press("-")
        await pilot.press("-")
        await pilot.pause()
        assert app.interval > start


@pytest.mark.asyncio
async def test_a_narrow_window_stacks_into_one_column(sampler):
    app = make_app(sampler)
    async with app.run_test(size=(60, 50)) as pilot:
        await pilot.pause()
        assert app._columns() == 1


@pytest.mark.asyncio
async def test_a_wide_window_uses_two_columns(sampler):
    app = make_app(sampler)
    async with app.run_test(size=(160, 44)) as pilot:
        await pilot.pause()
        assert app._columns() == 2


@pytest.mark.asyncio
async def test_graphs_sharing_a_row_end_at_the_same_line():
    """Bottom borders must line up across a grid row.

    Four roles are the case the heaviest-first sort cannot fix on its own: the
    weights pair 0.30 with 0.22 and 0.22 with 0.16, so each row has a shorter
    member, and `grid-rows: auto` content-sizes it into a ragged gap.
    """

    class FourRoles(FakeSource):
        def channels(self):
            return [
                Channel("out.sys", "System", "W", "out", "power_out", 2, nominal_max=60.0),
                Channel("cpu.util", "Processor", "%", "system", "cpu", 0, nominal_max=100.0),
                Channel("mem.used", "In use", "GB", "system", "memory", 2, nominal_max=16.0),
                Channel("temp.soc", "SoC", "degC", "thermal", "temperature", 1),
            ]

        def read(self):
            return {"out.sys": 14.0, "cpu.util": 15.0, "mem.used": 9.0, "temp.soc": 61.0}

    four = Sampler(sources=[FourRoles()], derived=[], history_len=60, overrides={})
    app = WattopApp(sampler=four, interval=0.1)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        assert app._columns() == 2
        rows = app._graph_rows()
        assert len(rows) == 2                       # two full pairs, no odd one out
        for row in rows:
            assert len({g.region.height for g in row}) == 1


@pytest.mark.asyncio
async def test_fan_channels_earn_a_headline_graph_of_the_fastest_one():
    """The FAN graph is the fastest-fan aggregate, so it exists only on a machine
    that reports tachometers -- and once it does, the aggregate belongs to the
    headline, while the individual fans keep their rows in the thermal panel."""
    from wattop.core.aggregates import FASTEST_FAN_KEY, attach_builtin_aggregates
    from wattop.ui.app import GroupPanel

    class Fans(FakeSource):
        def channels(self):
            return [
                *super().channels(),
                Channel("fan.cpu", "fan1", "RPM", "thermal", None, 0),
                Channel("fan.gpu", "fan2", "RPM", "thermal", None, 0),
            ]

        def read(self):
            return {**super().read(), "fan.cpu": 1823.0, "fan.gpu": 2400.0}

    fanned = Sampler(sources=[Fans()], derived=[], history_len=60, overrides={})
    attach_builtin_aggregates(fanned)
    app = WattopApp(sampler=fanned, interval=0.1)
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.pause()
        assert "fan" in {g.role for g in app._graphs}
        assert app.query_one("#graph-fan")

        rows = {ch.key for ch in GroupPanel.members(fanned, "thermal")}
        assert FASTEST_FAN_KEY not in rows      # consumed by the headline
        assert {"fan.cpu", "fan.gpu"} <= rows   # still listed behind `s`


@pytest.mark.asyncio
async def test_graph_height_pins_every_graph(sampler):
    app = make_app(sampler, graph_height=5)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        assert set(app._graph_heights().values()) == {5}


@pytest.mark.asyncio
async def test_a_machine_with_only_one_reading_still_runs(sampler):
    """A desktop with no battery and no charger rail must not be a crash."""

    class Sparse(FakeSource):
        def channels(self):
            return [Channel("out.sys", "System", "W", "out", "power_out", 2)]

        def read(self):
            return {"out.sys": 30.0}

    thin = Sampler(sources=[Sparse()], derived=[], history_len=60, overrides={})
    app = WattopApp(sampler=thin, interval=0.1)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert [g.role for g in app._graphs] == ["power_out"]


@pytest.mark.asyncio
async def test_quitting_does_not_leave_the_poll_timer_running(sampler):
    """A tick landing mid-teardown used to look for #battery, miss, and throw
    the exception out of the timer as a traceback on quit."""
    app = make_app(sampler)
    async with app.run_test(size=(120, 44)) as pilot:
        await pilot.pause()
        assert app._timer is not None
    assert app._timer is None          # stopped by on_unmount
    app.refresh_panels()               # a late repaint is a no-op, not a crash


@pytest.mark.asyncio
async def test_repeated_start_and_stop_is_clean(sampler):
    for _ in range(5):
        app = make_app(sampler)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()


def test_a_group_panel_fits_the_width_it_was_sized_to():
    """A cros_ec-length label in a narrow window drives every clamp at once.

    The columns are fixed-width, so a budget computed against the wrong width
    puts them past the edge and Rich tears each row onto a second line.
    """
    import io

    from rich.console import Console

    from wattop.ui.app import GroupPanel

    class LongLabels(FakeSource):
        def channels(self):
            return [
                Channel("out.sys", "System", "W", "out", "power_out", 2),
                Channel("rail.mem", "mainboard_memory@4d", "W", "rails", None, 2),
                Channel("rail.gpu", "GPU rail", "W", "rails", None, 2),
            ]

        def read(self):
            return {"out.sys": 14.0, "rail.mem": 1.25, "rail.gpu": 2.5}

    wide_labels = Sampler(sources=[LongLabels()], derived=[], history_len=60, overrides={})
    wide_labels.sample()
    panel = GroupPanel("rails")
    for width in (24, 34, 48, 60, 120):
        console = Console(file=io.StringIO(), width=width, legacy_windows=False)
        console.print(panel.render_content(wide_labels, width))
        lines = console.file.getvalue().splitlines()
        assert lines
        assert max(len(line) for line in lines) <= width


def test_a_five_figure_axis_label_does_not_widen_the_top_row():
    """`hi` gets a 6-cell field; 10000.0 needs 7 and used to push row 0 one cell
    past the crop, costing the top row its newest sample."""
    from wattop.ui.app import Graph

    pinned = Sampler(
        sources=[FakeSource()],
        derived=[],
        history_len=60,
        overrides={"out.sys": {"nominal_max": 12000.0}},
    )
    pinned.sample()
    panel = Graph("OUT", "power_out").render_content(pinned, width=40, height=6)
    lines = panel.renderable.plain.split("\n")
    assert len(lines) == 6
    assert len({len(line) for line in lines}) == 1


class TestAxisLadder:
    """The power rungs were measured on a 60 W laptop. They must not clip a
    desktop."""

    def graph(self):
        from wattop.ui.app import Graph

        return Graph("OUT", "power_out")

    def test_idle_laptop_sits_on_the_short_rung(self):
        assert self.graph()._rung(18.0) == 25.0

    def test_a_burst_takes_the_tall_rung(self):
        assert self.graph()._rung(40.0) == 60.0

    def test_a_desktop_gets_a_real_axis_not_a_clipped_one(self):
        g = self.graph()
        assert g._rung(120.0) >= 120.0
        assert g._rung(250.0) >= 250.0

    def test_above_the_ladder_the_axis_is_still_a_round_number(self):
        assert self.graph()._rung(120.0) == 125.0

    def test_a_hair_over_a_round_cruise_costs_one_step_not_a_doubling(self):
        """The 1-2-5 grid gave a box cruising at 100 W a 200 W axis for the rest
        of the run on the strength of one 100.06 W sample."""
        assert self.graph()._rung(100.06) == 125.0

    def test_a_declared_ceiling_is_the_rung(self):
        """A machine held at its cap should fill the panel, not 80% of it."""
        assert self.graph()._rung(100.06, cap=120.0) == 120.0

    def test_a_reading_past_the_declared_ceiling_steps_rather_than_clips(self):
        """A cap is a setting, not a law of physics, and drivers do report
        excursions past it."""
        assert self.graph()._rung(130.0, cap=120.0) == 150.0

    def test_hysteresis_holds_the_taller_axis_just_below_a_rung(self):
        g = self.graph()
        g._rung(40.0)                       # up to 60
        assert g._rung(24.0) == 60.0        # inside the dead band, hold
        assert g._rung(10.0) == 25.0        # clear of it, drop back

    def test_hysteresis_works_the_same_across_the_steps_above_the_ladder(self):
        g = self.graph()
        g._rung(100.06)                     # up to 125
        assert g._rung(99.0) == 125.0       # inside the dead band, hold
        assert g._rung(85.0) == 100.0       # clear of it, drop a step


class TestFanAxisSteps:
    """The fan climbs the thousands, not the 1-2-5 grid: that grid's 2000-5000
    gap left a cruising fan in the bottom half of the panel after one burst."""

    def graph(self):
        from wattop.ui.app import Graph

        return Graph("FAN", "fan")

    def test_a_cruising_fan_gets_the_next_thousand(self):
        assert self.graph()._rung(1764.0) == 2000.0

    def test_a_burst_past_a_rung_takes_the_next_one_not_5000(self):
        assert self.graph()._rung(2100.0) == 3000.0

    def test_a_stopped_fan_still_has_an_axis(self):
        assert self.graph()._rung(0.0) == 1000.0

    def test_a_declared_fan_max_is_the_top_rung(self):
        """An EC that publishes fanN_max knows the blower better than the
        thousands do."""
        assert self.graph()._rung(1764.0, cap=2400.0) == 2400.0

    def test_the_axis_relaxes_once_the_burst_scrolls_off(self):
        g = self.graph()
        g._rung(2100.0)                     # up to 3000
        assert g._rung(1900.0) == 3000.0    # inside the dead band, hold
        assert g._rung(1700.0) == 2000.0    # clear of it, drop back

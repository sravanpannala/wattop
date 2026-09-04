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

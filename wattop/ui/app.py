"""The live dashboard.

Panels are generic renderers over `group` and `role` -- no panel knows the name
of any sensor. That is what lets the same screen describe a Snapdragon laptop
(charger rail, battery volts and amps, per-cluster SoC power) and an AMD desktop
(one package-power number, no battery at all) without a branch anywhere here.
"""

from __future__ import annotations

import platform

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widgets import Footer, Static

from wattop.core.sampler import Sampler
from wattop.render import bar, format_eta, group_title, sparkline, value_style

HEADLINE_ROLES = (
    ("IN", "power_in"),
    ("OUT", "power_out"),
    ("BATT", "battery_power"),
)

#: Roles already shown by the headline or the battery line. The group panels
#: skip them so nothing appears on screen twice.
CONSUMED_ROLES = frozenset(
    {
        "power_in",
        "power_out",
        "battery_power",
        "battery_voltage",
        "battery_current",
        "battery_charge",
        "battery_level",
        "ac_online",
    }
)
CONSUMED_KEYS = frozenset({"batt.eta", "batt.full"})


class Headline(Static):
    """The three numbers the whole tool exists for, plus their history."""

    def render_content(self, sampler: Sampler, width: int) -> Table:
        values = sampler.latest.values
        spark_width = max(8, min(48, width - 46))

        table = Table.grid(padding=(0, 1))
        table.add_column(justify="left", width=5)
        table.add_column(justify="left", width=14)
        table.add_column(justify="right", width=12)
        table.add_column(justify="left", width=spark_width)
        table.add_column(justify="left")

        drawn = False
        for tag, role in HEADLINE_ROLES:
            ch = sampler.role(role)
            if ch is None or ch.key not in values:
                continue
            drawn = True
            v = values[ch.key]
            history = sampler.history[ch.key]
            # Only bar against a bound that means something. Scaling to the
            # running maximum would peg the bar at full forever and say nothing.
            gauge = bar(abs(v), ch.nominal_max, 12) if ch.nominal_max else ""
            table.add_row(
                Text(tag, style="bold"),
                Text(ch.label, style="dim"),
                Text(ch.format(v), style=value_style(ch, v)),
                Text(
                    sparkline(history, spark_width, anchor_zero=ch.unit in ("W", "A")),
                    style=value_style(ch, v),
                ),
                Text(gauge, style="dim"),
            )

        if not drawn:
            table.add_row(Text("--", style="dim"), Text("no headline channels"), "", "", "")
        return table


class BatteryLine(Static):
    """Volts, amps, charge and state -- only drawn if a battery exists."""

    def render_content(self, sampler: Sampler) -> Table | Text:
        values = sampler.latest.values
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left")

        parts: list[Text] = []
        for role in ("battery_voltage", "battery_current"):
            ch = sampler.role(role)
            if ch and ch.key in values:
                parts.append(Text(f"{ch.label} {ch.format(values[ch.key])}", style="bold"))

        level = sampler.role("battery_level")
        charge = sampler.role("battery_charge")
        if level and level.key in values:
            pct = values[level.key]
            full = values.get("batt.full")
            suffix = ""
            if charge and charge.key in values:
                suffix = f"  {values[charge.key]:.1f}" + (f"/{full:.1f} Wh" if full else " Wh")
            parts.append(Text(f"{bar(pct, 100.0, 18)} {pct:5.1f}%{suffix}"))

        ac = sampler.role("ac_online")
        power = sampler.role("battery_power")
        if ac and ac.key in values:
            online = values[ac.key] >= 0.5
            state = "AC" if online else "on battery"
            if power and power.key in values:
                p = values[power.key]
                state = "charging" if p > 0.05 else "discharging" if p < -0.05 else state
            parts.append(Text(state, style="green" if online else "yellow"))

        eta = sampler.channels.get("batt.eta")
        if eta and eta.key in values:
            pretty = format_eta(values[eta.key])
            if pretty != "--":
                parts.append(Text(f"{pretty} left", style="dim"))

        if not parts:
            return Text("")
        line = Text("  ").join(parts)
        table.add_row(line)
        return table


class GroupPanel(Static):
    """One panel per group, with a sparkline beside every channel."""

    def __init__(self, group: str) -> None:
        super().__init__(id=f"group-{group}")
        self.group = group

    @staticmethod
    def members(sampler: Sampler, group: str) -> list:
        return [
            ch
            for ch in sampler.by_group(group)
            if ch.role not in CONSUMED_ROLES and ch.key not in CONSUMED_KEYS
        ]

    def render_content(self, sampler: Sampler, width: int) -> Table:
        values = sampler.latest.values
        spark_width = max(8, min(40, width - 40))

        table = Table.grid(padding=(0, 1))
        table.add_column(justify="left", width=20)
        table.add_column(justify="right", width=12)
        table.add_column(justify="left", width=spark_width)

        for ch in self.members(sampler, self.group):
            if ch.key not in values:
                continue
            v = values[ch.key]
            spark = (
                ""
                if ch.static
                else sparkline(
                    sampler.history[ch.key], spark_width, anchor_zero=ch.unit in ("W", "A")
                )
            )
            table.add_row(
                Text(ch.label, style="dim"),
                Text(ch.format(v), style=value_style(ch, v)),
                Text(spark, style="cyan" if ch.unit == "W" else "dim"),
            )
        return table


class WattopApp(App):
    CSS = """
    Screen { background: $surface; }
    #headline { padding: 1 2 0 2; }
    #battery  { padding: 0 2 1 2; }
    .panel    { padding: 0 2 1 2; }
    .heading  { color: $accent; text-style: bold; padding: 0 2; }
    #status   { color: $text-muted; padding: 0 2; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("p", "toggle_pause", "Pause"),
        ("+", "faster", "Faster"),
        ("-", "slower", "Slower"),
    ]

    paused = reactive(False)

    def __init__(self, sampler: Sampler, interval: float = 1.0) -> None:
        super().__init__()
        self.sampler = sampler
        self.interval = interval
        self._timer = None
        self._panels: dict[str, GroupPanel] = {}

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Headline(id="headline")
            yield BatteryLine(id="battery")
            for group in self.sampler.groups():
                # A group whose channels are all headlined needs no panel.
                if not GroupPanel.members(self.sampler, group):
                    continue
                heading = Static(group_title(group), classes="heading", id=f"h-{group}")
                panel = GroupPanel(group)
                panel.add_class("panel")
                self._panels[group] = panel
                yield heading
                yield panel
            yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "wattop"
        self.sub_title = platform.node()
        self.sampler.sample()  # prime the rate counters
        self._timer = self.set_interval(self.interval, self.tick)
        self.refresh_panels()

    def tick(self) -> None:
        if self.paused:
            return
        self.sampler.sample()
        self.refresh_panels()

    def refresh_panels(self) -> None:
        width = self.size.width or 100
        self.query_one("#headline", Headline).update(
            self.query_one("#headline", Headline).render_content(self.sampler, width)
        )
        battery = self.query_one("#battery", BatteryLine)
        battery.update(battery.render_content(self.sampler))
        for group, panel in self._panels.items():
            panel.update(panel.render_content(self.sampler, width))

        bits = [f"{self.interval:g}s"]
        if self.paused:
            bits.append("PAUSED")
        for name, err in self.sampler.failed.items():
            bits.append(f"!{name}: {err}")
        self.query_one("#status", Static).update("  ".join(bits))

    def on_resize(self) -> None:
        self.refresh_panels()

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        self.refresh_panels()

    def action_faster(self) -> None:
        self._set_interval(max(0.1, self.interval / 2))

    def action_slower(self) -> None:
        self._set_interval(min(60.0, self.interval * 2))

    def _set_interval(self, value: float) -> None:
        self.interval = value
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_interval(self.interval, self.tick)
        self.refresh_panels()

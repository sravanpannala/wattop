"""The live dashboard.

Panels are generic renderers over `group` and `role` -- no panel knows the name
of any sensor. That is what lets the same screen describe a Snapdragon laptop
(charger rail, battery volts and amps, per-cluster SoC power) and an AMD desktop
(one package-power number, no battery at all) without a branch anywhere here.
"""

from __future__ import annotations

import platform

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widgets import Footer, Static

from wattop.core.sampler import Sampler
from wattop.render import (
    bar,
    block_graph,
    format_eta,
    graph_bounds,
    group_title,
    ramp_color,
    sparkline,
    value_style,
)

HEADLINE_ROLES = (
    ("IN", "power_in"),
    ("OUT", "power_out"),
    ("BATT", "battery_power"),
    ("TEMP", "temperature"),
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
        "temperature",
    }
)
CONSUMED_KEYS = frozenset({"batt.eta", "batt.full"})


#: Fraction of the window each headline graph gets. The two that actually move
#: -- what the machine is drawing, and which way the battery is going -- take
#: 40% of the screen each; the charger rail and the hottest sensor get a quarter.
#: That deliberately adds up to more than one screen: the graphs live in a scroll
#: container, and scrolling for the last one is the price of being able to read
#: the first two. Override per role in config.toml:
#:
#:     [graphs]
#:     power_out = 0.3
#:     battery_power = 0.3
#:     power_in = 0.15
#:     temperature = 0.15
DEFAULT_GRAPH_WEIGHTS = {
    "power_out": 0.4,
    "battery_power": 0.4,
    "power_in": 0.25,
    "temperature": 0.25,
}

#: Every panel costs a top and bottom border on top of its plot rows.
BORDER_ROWS = 2

#: Which colour ramp each headline graph uses.
RAMP_FOR_ROLE = {
    "power_in": "power_in",
    "power_out": "power_out",
    "battery_power": "battery",
    "temperature": "temperature",
}


class Graph(Static):
    """One headline channel as a full-height btop-style area graph."""

    def __init__(self, tag: str, role: str) -> None:
        super().__init__(id=f"graph-{role}")
        self.tag = tag
        self.role = role

    def render_content(self, sampler: Sampler, width: int, height: int) -> Panel:
        ch = sampler.role(self.role)
        values = sampler.latest.values
        if ch is None:
            return Panel(Text(""), title=self.tag)

        history = list(sampler.history[ch.key]) or [values.get(ch.key, 0.0)]
        anchor = ch.unit in ("W", "A")
        lo, hi = graph_bounds(history, anchor_zero=anchor)

        label_w = 8
        inner = max(10, width - label_w - 4)
        rows = block_graph(history, inner, height, lo, hi, anchor_zero=anchor)
        ramp = RAMP_FOR_ROLE.get(self.role, "default")

        body = Text()
        for i, row in enumerate(rows):
            if i == 0:
                axis = f"{hi:>{label_w - 2}.1f} "
            elif i == height - 1:
                axis = f"{lo:>{label_w - 2}.1f} "
            else:
                axis = " " * (label_w - 1)
            body.append(axis, style="dim")
            for glyph, level in row:
                body.append(glyph, style=ramp_color(ramp, level, height))
            if i < height - 1:
                body.append("\n")

        current = values.get(ch.key)
        title = Text.assemble((self.tag, "bold"), (f"  {ch.label}", "dim"))
        subtitle = Text(ch.format(current), style=value_style(ch, current or 0.0))
        if ch.nominal_max and current is not None:
            subtitle.append(" " + bar(abs(current), ch.nominal_max, 10), style="dim")
        return Panel(
            body,
            title=title,
            title_align="left",
            subtitle=subtitle,
            subtitle_align="right",
            border_style=ramp_color(ramp, height - 1, height),
            padding=(0, 0),
        )


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
        members = self.members(sampler, self.group)
        # Sized to the content: cros_ec labels like "mainboard_memory@4d" run
        # well past any fixed width and tear the columns apart.
        label_w = max(12, min(34, max((len(c.label) for c in members), default=12)))
        spark_width = max(8, min(40, width - label_w - 20))

        table = Table.grid(padding=(0, 1))
        table.add_column(justify="left", width=label_w)
        table.add_column(justify="right", width=12)
        table.add_column(justify="left", width=spark_width)

        for ch in members:
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
    .graph    { padding: 0 2; }
    #battery  { padding: 1 2 1 2; }
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

    def __init__(
        self,
        sampler: Sampler,
        interval: float = 1.0,
        graph_height: int | None = None,
        graph_weights: dict[str, float] | None = None,
    ) -> None:
        super().__init__()
        self.sampler = sampler
        self.interval = interval
        self.graph_height = graph_height
        self.graph_weights = (
            DEFAULT_GRAPH_WEIGHTS if graph_weights is None else dict(graph_weights)
        )
        self._timer = None
        self._panels: dict[str, GroupPanel] = {}
        self._graphs: list[Graph] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            for tag, role in HEADLINE_ROLES:
                if self.sampler.role(role) is None:
                    continue
                graph = Graph(tag, role)
                graph.add_class("graph")
                self._graphs.append(graph)
                yield graph
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

    def _graph_heights(self) -> dict[str, int]:
        """Plot rows for each headline graph.

        Weighted roles get a fixed share of the *window*, so "a quarter of the
        screen" stays a quarter regardless of how many rails the machine turns
        out to have. Everything else splits whatever the panels below don't
        need. If the total overshoots -- a short window, or a lot of rails --
        the tallest graph gives up rows until it fits.
        """
        if not self._graphs:
            return {}
        if self.graph_height:
            return {g.role: max(2, self.graph_height) for g in self._graphs}

        total = self.size.height or 40
        rows_below = 1 + 1  # battery line + footer
        for group in self._panels:
            rows_below += 1 + len(GroupPanel.members(self.sampler, group))
        spare = max(len(self._graphs) * (2 + BORDER_ROWS), total - rows_below - 1)

        heights: dict[str, int] = {}
        for graph in self._graphs:
            weight = self.graph_weights.get(graph.role)
            if weight is not None:
                heights[graph.role] = max(2, round(total * weight) - BORDER_ROWS)

        unweighted = [g.role for g in self._graphs if g.role not in heights]
        used = sum(h + BORDER_ROWS for h in heights.values())
        if unweighted:
            each = max(2, (spare - used) // len(unweighted) - BORDER_ROWS)
            for role in unweighted:
                heights[role] = each
            used += sum(heights[r] + BORDER_ROWS for r in unweighted)

        # An explicit weight is taken at its word even when the total overflows
        # the window -- the container scrolls. Only unweighted graphs, which are
        # merely filling leftover space, give rows back to make things fit.
        while used > spare and unweighted and max(heights[r] for r in unweighted) > 2:
            tallest = max(unweighted, key=lambda r: heights[r])
            heights[tallest] -= 1
            used -= 1
        return heights

    def refresh_panels(self) -> None:
        width = self.size.width or 100
        heights = self._graph_heights()
        for graph in self._graphs:
            graph.update(graph.render_content(self.sampler, width, heights[graph.role]))
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

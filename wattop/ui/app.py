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
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Grid, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Footer, Static

from wattop.core.aggregates import ETA_KEY
from wattop.core.sampler import Sampler
from wattop.render import (
    bar,
    braille_graph,
    format_eta,
    group_title,
    nice_ceil,
    ramp_color,
    sparkline,
    value_style,
)

HEADLINE_ROLES = (
    ("IN", "power_in"),
    ("OUT", "power_out"),
    ("BATT", "battery_power"),
    ("TEMP", "temperature"),
    ("CPU", "cpu"),
    ("MEM", "memory"),
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
        "battery_eta",
        "ac_online",
        "temperature",
        "cpu",
        "memory",
    }
)
#: Keys a headline already accounts for. `mem.total` is the memory graph's own
#: axis ceiling, printed on it -- a panel row repeating it says nothing new.
CONSUMED_KEYS = frozenset({"batt.eta", ETA_KEY, "batt.full", "mem.total"})

#: Groups whose panels start closed. Every rail and every thermal zone is still
#: read, still listed by `--list`, and still logged by `--log`; they simply do
#: not hold rows under the graphs until asked for, because on most machines they
#: are a screenful of numbers that rarely move and the hottest zone already
#: survives on screen as TEMP. `s` opens them, and `show_details` in the config
#: starts them open -- which is what you want on a machine whose per-rail power
#: is the reason you are running this at all.
DETAIL_GROUPS = frozenset({"rails", "thermal"})


#: Fraction of the window each headline graph gets, as *height*. In a landscape
#: window the graphs sit two to a row, heaviest first, so equal weights share a
#: row and a row is as tall as the taller of its pair. Three rows, in the order
#: the weights put them: what the machine is drawing and which way the battery is
#: going, then what it is doing to earn that -- processor and memory -- then the
#: charger rail and the hottest sensor, both of which mostly sit still and are
#: read as a number rather than as a shape. A portrait window stacks all six in
#: one column instead, where the weights overflow the screen and it scrolls.
#: Override per role in config.toml:
#:
#:     [graphs]
#:     power_out = 0.3
#:     battery_power = 0.3
#:     cpu = 0.2
#:     memory = 0.2
DEFAULT_GRAPH_WEIGHTS = {
    "power_out": 0.30,
    "battery_power": 0.30,
    "cpu": 0.22,
    "memory": 0.22,
    "power_in": 0.16,
    "temperature": 0.16,
}

#: Every panel costs a top and bottom border on top of its plot rows.
BORDER_ROWS = 2

#: Which colour ramp each headline graph uses. Battery is the discharge colour;
#: while charging the graph switches to the green power_in ramp instead.
RAMP_FOR_ROLE = {
    "power_in": "power_in",
    "power_out": "power_out",
    "battery_power": "battery",
    "temperature": "temperature",
    "cpu": "cpu",
    "memory": "memory",
}

#: The power graphs live on a two-rung ladder. 0-25 W covers ordinary
#: idle-to-light-load draw at full vertical resolution -- the range the machine
#: actually sits in most of the time, which on a single tall axis is squashed
#: into the bottom third. 0-60 W opens up only while a burst needs the headroom.
#: The rungs are absolute rather than derived, so OUT and BATT stay directly
#: comparable while each still picks its own.
#:
#: The short rung sits above the idle band rather than inside it: measured idle
#: on this machine runs 15-19 W with the odd excursion to ~22, so a 20 W rung
#: would be crossed every few seconds and the graph would live on 60 W for the
#: sake of a blip. A rung is only useful where the data is not.
POWER_STEPS = (25.0, 60.0)

#: Roles on that ladder. IN keeps whatever nominal_max its source declares and
#: TEMP keeps its own fixed span.
STEPPED_ROLES = frozenset({"power_out", "battery_power"})

#: The TEMP graph's fixed span. Unlike the power ladder this never moves -- it is
#: a scale, not a rung. Watts are floored at zero because zero watts is a real
#: reading; the hottest sensor in a running machine is never anywhere near zero
#: degC, so the bottom two fifths of a 0-100 axis is dead space. Measured idle
#: here sits around 47 degC, so 40 clears the idle band from below, and silicon
#: throttles just under 100 -- between them the full panel height maps onto the
#: range that actually varies, and the top of the graph still means too hot.
TEMP_RANGE = (40.0, 100.0)

#: Step back down only once the window max has cleared 10% below the lower rung,
#: so a series parked right at a rung does not flip the axis on alternate frames.
STEP_HYSTERESIS = 0.9


class Graph(Static):
    """One headline channel as a full-height btop-style area graph."""

    def __init__(self, tag: str, role: str) -> None:
        super().__init__(id=f"graph-{role}")
        self.tag = tag
        self.role = role
        #: Highest value seen this run -- the fixed axis ceiling. Ratchets up,
        #: never down, so the scale stays put instead of rescaling every frame.
        self.peak = 0.0
        #: The rung currently held, for the roles on POWER_STEPS. Carried across
        #: frames purely so the hysteresis band has something to compare to.
        self.rung = POWER_STEPS[0]

    def _rung(self, peak: float) -> float:
        """Smallest rung at or above `peak`, capped at the tallest one.

        Steps up the instant the window clears the current rung. Steps back down
        only once the peak has fallen clear of the band below the shorter rung --
        a series hovering right at a rung would otherwise flip the axis on
        alternate frames, which reads as a glitch rather than as a scale change.
        """
        target = next((s for s in POWER_STEPS if peak <= s), POWER_STEPS[-1])
        if target < self.rung and peak > target * STEP_HYSTERESIS:
            return self.rung  # inside the dead band -- hold the taller axis
        self.rung = target
        return target

    def render_content(self, sampler: Sampler, width: int, height: int) -> Panel:
        ch = sampler.role(self.role)
        values = sampler.latest.values
        if ch is None:
            return Panel(Text(""), title=self.tag)

        label_w = 8
        # `width` is this widget's content width (padding and scrollbar already
        # excluded); only the Panel border and the axis column remain. Getting
        # this wrong is worse than it looks: a row even one cell too wide folds,
        # every panel doubles in height, and the layout smears -- and only once
        # history has grown past the panel width, so it reads as decay.
        inner = max(10, width - 2 - (label_w - 1))

        # Braille packs two samples into each cell, so the window is twice the
        # panel's inner width.
        history = list(sampler.history[ch.key])[-inner * 2 :] or [values.get(ch.key, 0.0)]
        current = values.get(ch.key)

        # Battery power plots as magnitude: the graph shows how hard the battery
        # is working, and the colour -- not the direction of the bars -- says
        # which way the energy is flowing.
        charging = None
        if self.role == "battery_power":
            ref = current if current is not None else history[-1]
            charging = ref >= 0
            history = [abs(v) for v in history]

        # Fixed axis, floor at zero, resolved in four steps.
        #
        # A ceiling pinned in config.toml with [overrides."<key>"] nominal_max
        # wins outright -- it is the one ceiling the user asked for by name, so
        # nothing below gets to second-guess it.
        #
        # OUT and BATT then take a rung off POWER_STEPS, chosen from the window
        # on screen rather than from the run: the tall axis is there for the
        # burst being drawn, and once that burst has scrolled off, holding 0-60
        # only buys back the empty two thirds it was opened to avoid. Each graph
        # reads its own window, so a spike on one leaves the other alone.
        #
        # Otherwise a channel that declares nominal_max gets exactly that,
        # forever, and temperature falls back to TEMP_RANGE -- the one graph that
        # does not start at zero, since it is the only one whose floor is not a
        # reading it can take. Failing all of those, the ceiling is the run's peak
        # snapped up to the 1/2/5 grid: it jumps to a round number early (25, 50,
        # 100) and then holds, rather than creeping upward every time a sample
        # sets a new record.
        lo = TEMP_RANGE[0] if self.role == "temperature" else 0.0
        pinned = sampler.overrides.get(ch.key, {}).get("nominal_max")
        if pinned:
            hi = float(pinned)
        elif self.role in STEPPED_ROLES:
            # After the magnitude pass above, so BATT picks its rung on how hard
            # the battery is working rather than on which way it is flowing.
            hi = self._rung(max(history))
        else:
            ceiling = ch.nominal_max
            if not ceiling and self.role == "temperature":
                ceiling = TEMP_RANGE[1]
            if ceiling:
                hi = ceiling
            else:
                self.peak = max(self.peak, max(history))
                hi = nice_ceil(self.peak)

        rows = braille_graph(history, inner, height, lo, hi)
        ramp = RAMP_FOR_ROLE.get(self.role, "default")
        if charging is not None:
            ramp = "power_in" if charging else "battery"

        # no_wrap: an overwide row must crop, never fold onto a second line.
        body = Text(no_wrap=True)
        for i, row in enumerate(rows):
            if i == 0:
                axis = f"{hi:>{label_w - 2}.1f} "
            elif i == height - 1:
                axis = f"{lo:>{label_w - 2}.1f} "
            else:
                axis = " " * (label_w - 1)
            body.append(axis, style="dim")
            # One span for the whole row: the ramp is keyed on row height, so
            # every cell here is the same colour.
            body.append(row, style=ramp_color(ramp, height - 1 - i, height))
            if i < height - 1:
                body.append("\n")

        title = Text.assemble((self.tag, "bold"), (f"  {ch.label}", "dim"))
        subtitle = Text(ch.format(current), style=value_style(ch, current or 0.0))
        if current is not None:
            # Gauge across the axis span, whatever resolved it -- so the
            # battery's borrowed scale gets the same bar OUT has, and TEMP's bar
            # agrees with its own trace instead of measuring from a zero that is
            # not on the axis.
            subtitle.append(" " + bar(abs(current) - lo, hi - lo, 10), style="dim")
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

    #: Last time-left figure actually put on screen. See `_hold`.
    _shown_eta: float | None = None

    def _hold(self, seconds: float) -> float:
        """Keep the shown figure still until it has really moved.

        Averaging fixes the estimate; it does not freeze it. A five-minute mean
        still wanders a percent or so a tick, and `format_eta` truncating to
        whole minutes is not a wide enough deadband to hide that -- one minute
        is 0.3% of a five-hour estimate, so the last digit would still crawl.
        Hold the last value until the new one is a displayed minute away, or 2%
        away, whichever is larger.

        Because the underlying figure trends one way, every breach steps in that
        direction: it reads as a countdown, not as flicker. This lives here and
        not in the estimator because it is a fact about eyes, not about
        batteries -- `--log` and `--json` keep the full-resolution series, the
        way `Graph.peak` keeps the axis steady without touching the data.
        """
        shown = self._shown_eta
        if shown is None or (shown < 0) != (seconds < 0):
            self._shown_eta = seconds  # first reading, or charging flipped to not
        elif abs(seconds - shown) >= max(60.0, 0.02 * abs(shown)):
            self._shown_eta = seconds
        return self._shown_eta

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

        # The averaged estimate owns the `battery_eta` role; falling back to the
        # firmware's own key keeps the line populated on hardware where the
        # aggregate could not attach (a pack that reports only percentages).
        smoothed = sampler.role("battery_eta")
        seconds = values.get(smoothed.key if smoothed else "batt.eta")
        if seconds is None:
            # Forget the held figure, so the next estimate is not measured
            # against one belonging to the other side of a plug/unplug.
            self._shown_eta = None
        else:
            if smoothed is not None:
                seconds = self._hold(seconds)
            pretty = format_eta(abs(seconds))
            if pretty != "--":
                # Negative is time to full -- see the estimator.
                suffix = "to full" if seconds < 0 else "left"
                parts.append(Text(f"{pretty} {suffix}", style="dim"))

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
    #graphs   { grid-size: 2; grid-columns: 1fr; grid-rows: auto; height: auto; }
    .graph    { padding: 0 2; }
    #battery  { padding: 0 2 1 2; }
    .panel    { padding: 0 2 1 2; }
    .heading  { color: $accent; text-style: bold; padding: 0 2; }
    #status   { color: $text-muted; padding: 0 2; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("p", "toggle_pause", "Pause"),
        ("s", "toggle_details", "Sensors"),
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
        show_details: bool = False,
    ) -> None:
        super().__init__()
        self.sampler = sampler
        self.interval = interval
        self.graph_height = graph_height
        self.graph_weights = (
            DEFAULT_GRAPH_WEIGHTS if graph_weights is None else dict(graph_weights)
        )
        self._timer = None
        self.show_details = show_details
        self._panels: dict[str, GroupPanel] = {}
        #: Heading + panel per detail group, so the toggle can hide both.
        self._detail_rows: dict[str, tuple[Static, GroupPanel]] = {}
        self._graphs: list[Graph] = []
        #: Size from the latest Resize event. `self.size` still reports the old
        #: window inside on_resize, which left the column count one resize
        #: behind the terminal.
        self._viewport = None

    def compose(self) -> ComposeResult:
        # Heaviest first, so that in the two-column layout equal weights end up
        # sharing a row -- pairing a 40% graph with a 25% one would leave a
        # ragged gap under the short one.
        self._graphs = [
            Graph(tag, role)
            for tag, role in HEADLINE_ROLES
            if self.sampler.role(role) is not None
        ]
        self._graphs.sort(key=lambda g: -self.graph_weights.get(g.role, 0.0))
        with VerticalScroll():
            yield BatteryLine(id="battery")
            with Grid(id="graphs"):
                for graph in self._graphs:
                    graph.add_class("graph")
                    yield graph
            for group in self.sampler.groups():
                # A group whose channels are all headlined needs no panel.
                if not GroupPanel.members(self.sampler, group):
                    continue
                heading = Static(group_title(group), classes="heading", id=f"h-{group}")
                panel = GroupPanel(group)
                panel.add_class("panel")
                self._panels[group] = panel
                if group in DETAIL_GROUPS:
                    # Built either way so the toggle is instant and the height
                    # allocator has something to measure; just not shown yet.
                    self._detail_rows[group] = (heading, panel)
                    heading.display = panel.display = self.show_details
                yield heading
                yield panel
        # Outside the scroll container: the graphs deliberately overflow the
        # window, so anything inside it below them -- like this line was once --
        # is never seen. Poll rate and source failures must stay on screen.
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "wattop"
        self.sub_title = platform.node()
        self._set_terminal_title("wattop")
        self.sampler.sample()  # prime the rate counters
        self._timer = self.set_interval(self.interval, self.tick)
        self._apply_columns()
        self.refresh_panels()

    def on_unmount(self) -> None:
        # An empty title makes the terminal fall back to naming the tab after
        # the foreground process, i.e. the shell we are returning to.
        self._set_terminal_title("")

    def _set_terminal_title(self, title: str) -> None:
        """Textual's `title` only reaches the in-app header, not the terminal,
        so tabs otherwise show the process name: python.exe."""
        try:
            self._driver.write(f"\x1b]0;{title}\x07")
        except Exception:
            pass  # no driver in headless tests, or already torn down on exit

    def tick(self) -> None:
        if self.paused:
            return
        self.sampler.sample()
        self.refresh_panels()

    def _window(self) -> tuple[int, int]:
        size = self._viewport or self.size
        return size.width or 100, size.height or 40

    def _columns(self) -> int:
        """Two columns in a landscape window, one in portrait.

        A terminal cell is a bit more than twice as tall as it is wide, so a
        window snapped to the left half of a landscape monitor -- the classic
        portrait shape -- still measures just over 2:1 in cells. The cutoff
        sits at 2.5 so that shape stays a single column, while a full-screen
        terminal (3.5:1 and up) comfortably clears it. The width floor keeps
        two columns from ever being two unreadably narrow plots.
        """
        width, height = self._window()
        return 2 if width >= max(100, 2.5 * height) else 1

    def _graph_rows(self) -> list[list[Graph]]:
        cols = self._columns()
        return [self._graphs[i : i + cols] for i in range(0, len(self._graphs), cols)]

    def _apply_columns(self) -> None:
        """Point the grid at the current orientation."""
        if not self._graphs:
            return
        cols = self._columns()
        self.query_one("#graphs", Grid).styles.grid_size_columns = cols
        for graph in self._graphs:
            graph.styles.column_span = 1
        # An odd graph out takes the whole last row rather than half of it.
        if cols == 2 and len(self._graphs) % 2:
            self._graphs[-1].styles.column_span = 2

    def _graph_heights(self) -> dict[str, int]:
        """Plot rows for each headline graph.

        Weighted roles get a fixed share of the *window*, so "a quarter of the
        screen" stays a quarter regardless of how many rails the machine turns
        out to have. Everything else splits whatever the panels below don't
        need. Graphs sit two to a row in landscape, so a row costs the taller
        of its pair. If the total overshoots -- a short window, or a lot of
        rails -- the tallest graph gives up rows until it fits.
        """
        if not self._graphs:
            return {}
        if self.graph_height:
            return {g.role: max(2, self.graph_height) for g in self._graphs}

        rows = self._graph_rows()
        total = self._window()[1]
        rows_below = 1 + 2  # battery line + status line + footer
        for group in self._visible_panels():
            rows_below += 1 + len(GroupPanel.members(self.sampler, group))
        spare = max(len(rows) * (2 + BORDER_ROWS), total - rows_below - 1)

        heights: dict[str, int] = {}
        for graph in self._graphs:
            weight = self.graph_weights.get(graph.role)
            if weight is not None:
                heights[graph.role] = max(2, round(total * weight) - BORDER_ROWS)

        unweighted = [g.role for g in self._graphs if g.role not in heights]
        if unweighted:
            # Rows with a weighted member are spoken for; rows made entirely of
            # unweighted graphs split whatever window is left.
            claimed = sum(
                max(heights[g.role] for g in row if g.role in heights) + BORDER_ROWS
                for row in rows
                if any(g.role in heights for g in row)
            )
            free_rows = sum(1 for row in rows if not any(g.role in heights for g in row))
            each = max(2, (spare - claimed) // max(1, free_rows) - BORDER_ROWS)
            for role in unweighted:
                heights[role] = each

        def used() -> int:
            return sum(max(heights[g.role] for g in row) + BORDER_ROWS for row in rows)

        # An explicit weight is taken at its word even when the total overflows
        # the window -- the container scrolls. Only unweighted graphs, which are
        # merely filling leftover space, give rows back to make things fit.
        while used() > spare and unweighted and max(heights[r] for r in unweighted) > 2:
            tallest = max(unweighted, key=lambda r: heights[r])
            heights[tallest] -= 1
        return heights

    def refresh_panels(self) -> None:
        width = self.size.width or 100
        heights = self._graph_heights()
        for graph in self._graphs:
            # The widget's own content region, not the app width: the graph
            # cannot know what chrome (scrollbar, padding) sits around it.
            # Fallback for the on_mount refresh that runs before first layout.
            gw = graph.content_size.width or (width - 6)
            graph.update(graph.render_content(self.sampler, gw, heights[graph.role]))
        battery = self.query_one("#battery", BatteryLine)
        battery.update(battery.render_content(self.sampler))
        for group in self._visible_panels():
            panel = self._panels[group]
            panel.update(panel.render_content(self.sampler, width))

        bits = [f"poll {self.interval:g}s"]
        if self.paused:
            bits.append("PAUSED")
        for name, err in self.sampler.failed.items():
            bits.append(f"!{name}: {err}")
        self.query_one("#status", Static).update("  ".join(bits))

    def on_resize(self, event: events.Resize) -> None:
        self._viewport = event.size
        self._apply_columns()
        self.refresh_panels()

    def _visible_panels(self) -> list[str]:
        """Groups currently holding rows. A closed detail group costs nothing,
        so the graphs get its height back rather than merely its blank space."""
        return [
            group
            for group in self._panels
            if group not in self._detail_rows or self.show_details
        ]

    def action_toggle_details(self) -> None:
        self.show_details = not self.show_details
        for heading, panel in self._detail_rows.values():
            heading.display = panel.display = self.show_details
        # The graphs are sized against what sits below them, so they have to be
        # remeasured here and not merely redrawn.
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

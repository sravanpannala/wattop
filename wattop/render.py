"""Plain-text rendering shared by --list, --once and (via Rich) the TUI."""

from __future__ import annotations

from wattop.core.channel import Channel
from wattop.core.sampler import Sampler

# No leading space: every sample must leave a mark, otherwise a quiet rail
# renders as blank and looks like a dead sensor.
BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(
    values,
    width: int = 24,
    lo: float | None = None,
    hi: float | None = None,
    anchor_zero: bool = False,
) -> str:
    """Unicode block sparkline.

    Power and current anchor at zero, because scaling watts to their own min
    turns a rock-steady 59 W rail into dramatic-looking noise. Temperatures and
    speeds scale to the window instead -- anchoring 35 degC against zero would
    peg every block to full. A series that does not move renders flat rather
    than maxed out, so "not changing" and "at the ceiling" look different.
    """
    data = list(values)[-width:]
    if not data:
        return ""
    if lo is None:
        lo = 0.0 if (anchor_zero and min(data) >= 0) else min(data)
    hi = max(data) if hi is None else hi
    if hi - lo <= abs(hi) * 1e-9 + 1e-12:
        return BLOCKS[len(BLOCKS) // 2 - 1] * len(data)
    out = []
    for v in data:
        frac = (v - lo) / (hi - lo)
        idx = max(0, min(len(BLOCKS) - 1, round(frac * (len(BLOCKS) - 1))))
        out.append(BLOCKS[idx])
    return "".join(out)


#: Partial cells growing upward from the floor of the cell, and the two glyphs
#: Unicode gives us for growing downward from the ceiling.
UP_EIGHTHS = " ▁▂▃▄▅▆▇█"
DOWN_HALF, DOWN_EIGHTH = "▀", "▔"

#: Bottom-of-graph to top-of-graph colour ramps, btop style.
GRADIENTS = {
    "power_in": ["#1b5e20", "#2e7d32", "#388e3c", "#43a047", "#4caf50", "#66bb6a", "#81c784"],
    "power_out": ["#01579b", "#0277bd", "#0288d1", "#039be5", "#03a9f4", "#29b6f6", "#4fc3f7"],
    "battery": ["#f57f17", "#f9a825", "#fbc02d", "#fdd835", "#ffee58", "#fff176", "#fff59d"],
    # Cool at the floor, hot at the ceiling -- the ramp reads as a temperature
    # even before you look at the axis.
    "temperature": ["#1b5e20", "#558b2f", "#9e9d24", "#f9a825", "#ef6c00", "#e64a19", "#c62828"],
    "default": ["#37474f", "#455a64", "#546e7a", "#607d8b", "#78909c", "#90a4ae", "#b0bec5"],
}


def graph_bounds(data, anchor_zero: bool = False) -> tuple[float, float]:
    """Pick the vertical span for a tall graph.

    Deliberately *not* zero-anchored, unlike the one-line sparklines. A charger
    rail pinned at 59.5 W plotted from zero fills every cell and tells you
    nothing; the whole point of giving it eight rows is to see the shape. The
    graph prints its own upper and lower bound, so a window-scaled plot is still
    honest about what it is showing.

    Flat series get a span centred on the value, so they render as a steady band
    across the middle rather than a solid wall. Series that cross zero keep zero
    inside the span so the baseline stays meaningful.
    """
    lo, hi = min(data), max(data)
    span, ref = hi - lo, max(abs(lo), abs(hi))

    if ref == 0:
        return 0.0, 1.0  # nothing to draw; an empty plot says so plainly

    if lo < 0 <= hi:  # crosses zero, so keep the baseline visible on both sides
        pad = span * 0.08
        return lo - pad, hi + pad

    # Only treat a series as flat when it really is. The charger rail wanders
    # about 0.3 W around 59.5; that is 0.5% and worth seeing, so the cutoff sits
    # below it. Anything tighter than 0.2% is float noise and gets a flat band.
    if span <= ref * 0.002 + 1e-12:
        pad = max(ref * 0.05, 1e-6)
        return lo - pad, hi + pad

    if hi <= 0:
        # Entirely negative -- a battery that has been discharging the whole
        # window. Zero sits above the plot, so bars hang from the top edge;
        # scale to the window as for positive series rather than stretching the
        # span up to zero, which would peg every column at full depth.
        return lo - span * 0.10, min(0.0, hi + span * 0.15)
    return max(0.0, lo - span * 0.15), hi + span * 0.10


def block_graph(
    values,
    width: int,
    height: int,
    lo: float | None = None,
    hi: float | None = None,
    anchor_zero: bool = False,
) -> list[list[tuple[str, int]]]:
    """A btop-style area graph, `height` rows tall.

    Returns rows top-first; each row is a list of (glyph, ramp index) pairs so
    the caller can colour by height without this module importing Rich.

    Bars grow from the zero line when the series crosses zero and from the floor
    otherwise. Downward bars are coarser than upward ones -- Unicode has eight
    upward partial blocks but only two downward -- which is fine, since the
    interesting precision on a discharging battery is the depth, not the eighth.
    """
    data = list(values)[-width:]
    if not data or height < 1:
        return [[] for _ in range(height)]

    if lo is None or hi is None:
        auto_lo, auto_hi = graph_bounds(data, anchor_zero)
        lo = auto_lo if lo is None else lo
        hi = auto_hi if hi is None else hi
    if hi <= lo:
        hi = lo + 1e-9

    span = hi - lo
    # Where the zero line sits, in eighth-cells above the graph floor.
    zero_e = max(0.0, min(height * 8.0, (0.0 - lo) / span * height * 8)) if lo < 0 else 0.0

    rows: list[list[tuple[str, int]]] = [[] for _ in range(height)]
    for value in data:
        v_e = (value - lo) / span * height * 8
        top_e, bottom_e = (max(v_e, zero_e), min(v_e, zero_e))
        for row in range(height):  # row 0 is the floor
            cell_lo, cell_hi = row * 8.0, row * 8.0 + 8.0
            ramp = row
            if bottom_e >= cell_hi or top_e <= cell_lo:
                rows[height - 1 - row].append((" ", ramp))
                continue
            filled_lo = max(bottom_e, cell_lo)
            filled_hi = min(top_e, cell_hi)
            filled = filled_hi - filled_lo
            if filled >= 7.5:
                rows[height - 1 - row].append(("█", ramp))
            elif filled_lo <= cell_lo + 1e-9:
                # anchored to the floor of the cell: grows upward
                rows[height - 1 - row].append((UP_EIGHTHS[max(1, round(filled))], ramp))
            else:
                # hanging from the ceiling of the cell: only two glyphs exist
                rows[height - 1 - row].append((DOWN_HALF if filled >= 3 else DOWN_EIGHTH, ramp))
    return rows


def ramp_color(kind: str, index: int, height: int) -> str:
    ramp = GRADIENTS.get(kind, GRADIENTS["default"])
    if height <= 1:
        return ramp[-1]
    pos = round(index / (height - 1) * (len(ramp) - 1))
    return ramp[max(0, min(len(ramp) - 1, pos))]


def bar(value: float, maximum: float, width: int = 20) -> str:
    if maximum <= 0:
        return " " * width
    filled = max(0, min(width, round(width * value / maximum)))
    return "█" * filled + "░" * (width - filled)


def render_list(sampler: Sampler) -> str:
    rows = [("KEY", "LABEL", "UNIT", "GROUP", "ROLE", "VALUE")]
    for ch in sampler.channels.values():
        value = sampler.latest.values.get(ch.key)
        rows.append(
            (
                ch.key,
                ch.label,
                ch.unit or "-",
                ch.group,
                ch.role or "-",
                "--" if value is None else f"{value:.{ch.precision}f}",
            )
        )
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = []
    for n, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))

    sources = ", ".join(sorted({s.name for s in sampler.sources})) or "none"
    lines.append("")
    lines.append(f"{len(sampler.channels)} channels from {len(sampler.sources)} sources: {sources}")
    if sampler.failed:
        for name, err in sampler.failed.items():
            lines.append(f"  ! {name}: {err}")
    return "\n".join(lines)


def render_table(sampler: Sampler) -> str:
    """Human-readable snapshot, grouped the same way the TUI groups things."""
    values = sampler.latest.values
    lines: list[str] = []

    headline = [
        ("IN ", "power_in"),
        ("OUT", "power_out"),
        ("BAT", "battery_power"),
    ]
    for prefix, role in headline:
        ch = sampler.role(role)
        if ch is None or ch.key not in values:
            continue
        lines.append(f"{prefix}  {ch.label:<14} {ch.format(values[ch.key]):>12}")

    volts = sampler.role("battery_voltage")
    amps = sampler.role("battery_current")
    if volts and amps and volts.key in values and amps.key in values:
        lines.append(
            f"     {'V / I':<14} "
            f"{volts.format(values[volts.key]):>12}  {amps.format(values[amps.key]):>12}"
        )

    # One label width for the whole table. Fixed at 20 the columns tore apart on
    # the Framework box, whose cros_ec labels run to "mainboard_memory@4d".
    shown = [c for c in sampler.channels.values() if c.key in values]
    label_w = max((len(c.label) for c in shown), default=12)

    for group in sampler.groups():
        members = [c for c in sampler.by_group(group) if c.key in values]
        if not members:
            continue
        lines.append("")
        lines.append(f"[{group}]")
        for ch in members:
            lines.append(f"  {ch.label:<{label_w}} {ch.format(values[ch.key]):>12}   {ch.key}")

    if sampler.failed:
        lines.append("")
        for name, err in sampler.failed.items():
            lines.append(f"  ! {name}: {err}")
    return "\n".join(lines)


def group_title(group: str) -> str:
    return {
        "in": "POWER IN",
        "out": "POWER OUT",
        "battery": "BATTERY",
        "rails": "RAILS",
        "thermal": "THERMAL",
        "other": "OTHER",
    }.get(group, group.upper())


def format_eta(seconds: float) -> str:
    seconds = int(seconds)
    if seconds <= 0 or seconds >= 0xFFFFFFF:
        return "--"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def value_style(ch: Channel, value: float) -> str:
    """Colour by meaning, not by magnitude: drawing power is warm, charging is
    green, everything else stays neutral."""
    if ch.role == "power_in":
        return "bold green"
    if ch.role == "battery_power":
        return "bold green" if value >= 0 else "bold yellow"
    if ch.role == "power_out":
        return "bold cyan"
    if ch.unit == "degC":
        return "red" if value >= 80 else "yellow" if value >= 60 else "default"
    return "default"

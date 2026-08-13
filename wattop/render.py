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

    for group in sampler.groups():
        members = [c for c in sampler.by_group(group) if c.key in values]
        if not members:
            continue
        lines.append("")
        lines.append(f"[{group}]")
        for ch in members:
            lines.append(f"  {ch.label:<20} {ch.format(values[ch.key]):>12}   {ch.key}")

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

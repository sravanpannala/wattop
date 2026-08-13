"""Loading config.toml -- the "add a reading without writing code" path.

Three things can be declared here:

* `[[sensor]]`  - a reading from one of the generic sources (sysfs / exec /
                  http_json / pdh)
* `[[derived]]` - a channel computed from other channels
* `[overrides."key"]` - relabel, regroup or re-role a built-in channel
"""

from __future__ import annotations

import logging
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wattop.core.channel import Channel, Source
from wattop.core.derived import ExprError, compile_expr
from wattop.core.sampler import DerivedChannel

log = logging.getLogger(__name__)


@dataclass
class Config:
    interval: float = 1.0
    history: int = 240
    path: Path | None = None
    sensors: list[Source] = field(default_factory=list)
    derived: list[DerivedChannel] = field(default_factory=list)
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)


def default_paths() -> list[Path]:
    paths = [Path.cwd() / "config.toml"]
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            paths.append(Path(appdata) / "wattop" / "config.toml")
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    paths.append(base / "wattop" / "config.toml")
    return paths


def load(explicit: str | os.PathLike[str] | None = None) -> Config:
    if explicit is not None:
        path = Path(explicit)
        if not path.exists():
            raise FileNotFoundError(f"config not found: {path}")
    else:
        path = next((p for p in default_paths() if p.exists()), None)
        if path is None:
            return Config()

    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    cfg = Config(path=path)
    general = raw.get("general", {})
    cfg.interval = float(general.get("interval", cfg.interval))
    cfg.history = int(general.get("history", cfg.history))
    cfg.overrides = raw.get("overrides", {}) or {}

    # Imported here so the generic sources can import Config-adjacent helpers
    # without a cycle.
    from wattop.sources.generic import build_generic_source

    for entry in raw.get("sensor", []) or []:
        try:
            cfg.sensors.append(build_generic_source(entry))
        except Exception as exc:  # noqa: BLE001 - one bad stanza is not fatal
            log.warning("skipping [[sensor]] %s: %s", entry.get("key", "?"), exc)

    for entry in raw.get("derived", []) or []:
        try:
            cfg.derived.append(_build_derived(entry))
        except (ExprError, KeyError, ValueError) as exc:
            log.warning("skipping [[derived]] %s: %s", entry.get("key", "?"), exc)

    return cfg


def _build_derived(entry: dict[str, Any]) -> DerivedChannel:
    key = entry["key"]
    channel = Channel(
        key=key,
        label=entry.get("label", key),
        unit=entry.get("unit", ""),
        group=entry.get("group", "other"),
        role=entry.get("role"),
        precision=int(entry.get("precision", 2)),
        nominal_max=entry.get("nominal_max"),
    )
    return DerivedChannel(channel=channel, evaluate=compile_expr(entry["expr"]))


def apply_override(channel: Channel, override: dict[str, Any]) -> Channel:
    """Return `channel` with config-supplied fields replaced."""
    from dataclasses import replace

    allowed = {"label", "unit", "group", "role", "precision", "nominal_max"}
    fields = {k: v for k, v in override.items() if k in allowed}
    return replace(channel, **fields) if fields else channel

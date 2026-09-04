"""Polls every live source, merges the readings, keeps a little history."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field

from wattop.core.channel import Channel, Source

log = logging.getLogger(__name__)


@dataclass
class DerivedChannel:
    channel: Channel
    evaluate: object  # callable(sample) -> float | None


@dataclass
class Sample:
    t: float
    values: dict[str, float]


@dataclass
class Sampler:
    sources: list[Source]
    derived: list[DerivedChannel] = field(default_factory=list)
    history_len: int = 240
    #: `[overrides."key"]` from config.toml -- relabel/regroup built-in channels.
    overrides: dict[str, dict] = field(default_factory=dict)

    channels: dict[str, Channel] = field(init=False, default_factory=dict)
    history: dict[str, deque[float]] = field(init=False, default_factory=dict)
    latest: Sample = field(init=False)
    #: Sources that blew up while reading, so the UI can say so instead of
    #: quietly showing stale numbers.
    failed: dict[str, str] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        for src in self.sources:
            try:
                for ch in src.channels():
                    self._add(ch)
            except Exception as exc:
                log.debug("channel discovery failed for %s", src.name, exc_info=True)
                self.failed[src.name] = str(exc)
        for d in self.derived:
            self._add(d.channel)
        self.latest = Sample(t=time.time(), values={})

    def _add(self, ch: Channel) -> None:
        if ch.key in self.channels:
            log.debug("duplicate channel %s ignored", ch.key)
            return
        override = self.overrides.get(ch.key)
        if override:
            from wattop.core.config import apply_override

            ch = apply_override(ch, override)
        self.channels[ch.key] = ch
        self.history[ch.key] = deque(maxlen=self.history_len)

    def add_derived(self, derived: DerivedChannel) -> None:
        """Register a derived channel after construction.

        Aggregates that depend on what discovery found cannot be passed in up
        front -- see `wattop.core.aggregates`.
        """
        self.derived.append(derived)
        self._add(derived.channel)

    def role(self, role: str) -> Channel | None:
        """First channel claiming a semantic slot, e.g. "power_in"."""
        for ch in self.channels.values():
            if ch.role == role:
                return ch
        return None

    def by_group(self, group: str) -> list[Channel]:
        return [c for c in self.channels.values() if c.group == group]

    def groups(self) -> list[str]:
        from wattop.core.channel import GROUPS

        present = {c.group for c in self.channels.values()}
        ordered = [g for g in GROUPS if g in present]
        return ordered + sorted(present - set(ordered))

    def sample(self) -> Sample:
        values: dict[str, float] = {}
        for src in self.sources:
            try:
                values.update(src.read())
                self.failed.pop(src.name, None)
            except Exception as exc:
                log.debug("read failed for %s", src.name, exc_info=True)
                self.failed[src.name] = str(exc)

        for d in self.derived:
            v = d.evaluate(values)  # type: ignore[operator]
            if v is not None:
                values[d.channel.key] = v

        for key, v in values.items():
            if key in self.history:
                self.history[key].append(v)

        self.latest = Sample(t=time.time(), values=values)
        return self.latest

    def close(self) -> None:
        for src in self.sources:
            try:
                src.close()
            except Exception:  # noqa: BLE001
                pass

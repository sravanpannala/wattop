"""Source registry.

Sources register themselves at import time. Startup probes every registered
source and keeps the ones that say they are available, so the same binary works
on a Snapdragon laptop and an AMD desktop with no platform branching in the UI.
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable

from wattop.core.channel import Source

log = logging.getLogger(__name__)

_REGISTRY: list[Callable[[], Source]] = []


def register(factory: Callable[[], Source]) -> Callable[[], Source]:
    """Decorator: mark a Source class (or zero-arg factory) as built in."""
    _REGISTRY.append(factory)
    return factory


def registered_sources() -> list[Callable[[], Source]]:
    return list(_REGISTRY)


def build_sources(extra: Iterable[Source] = ()) -> list[Source]:
    """Instantiate every registered source, keep the available ones.

    A source that raises during construction or probing is skipped with a log
    line rather than taking the whole program down -- a broken sensor should
    never cost you the rest of the dashboard.
    """
    live: list[Source] = []
    for factory in _REGISTRY:
        try:
            src = factory()
            if src.available():
                live.append(src)
            else:
                log.debug("source %s not available", getattr(src, "name", factory))
        except Exception:  # noqa: BLE001 - a bad source must not be fatal
            log.debug("source %s failed to initialise", factory, exc_info=True)

    for src in extra:
        try:
            if src.available():
                live.append(src)
        except Exception:  # noqa: BLE001
            log.debug("configured source %s failed", getattr(src, "name", src), exc_info=True)

    return live

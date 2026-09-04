"""Generic sources built from `[[sensor]]` stanzas in config.toml.

These exist so that adding a reading usually costs no Python at all:

    [[sensor]]
    source = "sysfs"
    path   = "/sys/class/hwmon/hwmon3/power1_average"
    key    = "apu.power"; label = "APU"; unit = "W"; scale = 1e-6
    group  = "out"; role = "power_out"

    [[sensor]]
    source  = "http_json"
    url     = "http://plug.lan/cm?cmnd=Status%2010"
    pointer = "/StatusSNS/ENERGY/Power"
    key     = "wall"; label = "Wall"; unit = "W"; group = "in"; role = "power_in"

    [[sensor]]
    source = "exec"
    cmd    = ["ectool", "pwmgetfanrpm", "all"]
    parse  = "regex:(\\\\d+)$"
    key    = "ec.fan"; unit = "RPM"; group = "thermal"

    [[sensor]]
    source  = "pdh"
    counter = "\\\\Thermal Zone Information(*)\\\\Temperature"
    prefix  = "tz"; unit = "degC"; group = "thermal"; offset = -273.15

`http_json` and `exec` are polled on a background thread, because a slow plug or
a subprocess must not stall the sample loop; the dashboard shows the most recent
value they returned.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from wattop.core.channel import Channel


def build_generic_source(entry: dict[str, Any]):
    kind = entry.get("source")
    builders = {
        "sysfs": SysfsSensor,
        "file": SysfsSensor,
        "exec": ExecSensor,
        "http_json": HttpJsonSensor,
        "pdh": PdhSensor,
    }
    if kind not in builders:
        raise ValueError(f"unknown source {kind!r}; expected one of {sorted(builders)}")
    return builders[kind](entry)


def _channel(entry: dict[str, Any], key: str | None = None, label: str | None = None) -> Channel:
    key = key or entry["key"]
    return Channel(
        key=key,
        label=label or entry.get("label", key),
        unit=entry.get("unit", ""),
        group=entry.get("group", "other"),
        role=entry.get("role"),
        precision=int(entry.get("precision", 2)),
        nominal_max=entry.get("nominal_max"),
    )


def _convert(entry: dict[str, Any], value: float) -> float:
    return value * float(entry.get("scale", 1.0)) + float(entry.get("offset", 0.0))


class _Parser:
    """Turns arbitrary command/HTTP output into a number.

    `parse` is one of `float` (default), `regex:<pattern>` (first capture
    group), or `json:<pointer>`.
    """

    def __init__(self, spec: str | None) -> None:
        self.spec = spec or "float"

    def __call__(self, text: str) -> float | None:
        spec = self.spec
        if spec.startswith("regex:"):
            m = re.search(spec[len("regex:") :], text, re.MULTILINE)
            if not m:
                return None
            text = m.group(1) if m.groups() else m.group(0)
        elif spec.startswith("json:"):
            try:
                return _pointer(json.loads(text), spec[len("json:") :])
            except (ValueError, KeyError, IndexError, TypeError):
                return None
        try:
            return float(text.strip())
        except ValueError:
            return None


def _pointer(doc: Any, pointer: str) -> float | None:
    """A small subset of RFC 6901: /a/b/0."""
    node = doc
    for part in pointer.strip("/").split("/"):
        if part == "":
            continue
        node = node[int(part)] if isinstance(node, list) else node[part]
    return float(node) if node is not None else None


class SysfsSensor:
    """One number in one file. Cheap enough to read inline."""

    def __init__(self, entry: dict[str, Any]) -> None:
        self.name = f"sysfs:{entry.get('key', '?')}"
        self._entry = entry
        self._path = Path(entry["path"])
        self._key = entry["key"]
        self._parse = _Parser(entry.get("parse"))

    def available(self) -> bool:
        return self._read_raw() is not None

    def channels(self) -> list[Channel]:
        return [_channel(self._entry)]

    def _read_raw(self) -> float | None:
        try:
            return self._parse(self._path.read_text(errors="replace"))
        except OSError:
            return None

    def read(self) -> dict[str, float]:
        value = self._read_raw()
        return {} if value is None else {self._key: _convert(self._entry, value)}

    def close(self) -> None:
        pass


class _BackgroundSensor:
    """Base for sources whose read might block (subprocess, network).

    A worker thread refreshes the value on its own cadence; `read()` returns
    whatever arrived last and never waits.
    """

    def __init__(self, entry: dict[str, Any]) -> None:
        self._entry = entry
        self._key = entry["key"]
        self._parse = _Parser(entry.get("parse"))
        self._interval = float(entry.get("interval", 1.0))
        self._value: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _fetch(self) -> float | None:  # pragma: no cover - implemented by subclass
        raise NotImplementedError

    def available(self) -> bool:
        value = self._fetch()
        if value is None:
            return False
        self._value = value
        self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
        self._thread.start()
        return True

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                value = self._fetch()
            except Exception:  # noqa: BLE001 - a flaky sensor must not kill the thread
                value = None
            if value is not None:
                self._value = value

    def channels(self) -> list[Channel]:
        return [_channel(self._entry)]

    def read(self) -> dict[str, float]:
        if self._value is None:
            return {}
        return {self._key: _convert(self._entry, self._value)}

    def close(self) -> None:
        self._stop.set()


class ExecSensor(_BackgroundSensor):
    def __init__(self, entry: dict[str, Any]) -> None:
        super().__init__(entry)
        self.name = f"exec:{entry.get('key', '?')}"
        cmd = entry["cmd"]
        self._cmd = [cmd] if isinstance(cmd, str) else list(cmd)
        self._shell = bool(entry.get("shell", False))
        self._timeout = float(entry.get("timeout", 5.0))

    def _fetch(self) -> float | None:
        try:
            proc = subprocess.run(
                " ".join(self._cmd) if self._shell else self._cmd,
                shell=self._shell,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        return self._parse(proc.stdout)


class HttpJsonSensor(_BackgroundSensor):
    """Reads a number out of a JSON endpoint -- a Tasmota/Shelly/Kasa smart plug
    is the only way to see true wall power on a desktop, so this is how the
    Framework box gets a real `power_in` if one is ever added."""

    def __init__(self, entry: dict[str, Any]) -> None:
        super().__init__(entry)
        self.name = f"http:{entry.get('key', '?')}"
        self._url = entry["url"]
        self._timeout = float(entry.get("timeout", 3.0))
        pointer = entry.get("pointer")
        if pointer and not entry.get("parse"):
            self._parse = _Parser(f"json:{pointer}")

    def _fetch(self) -> float | None:
        import urllib.request

        try:
            with urllib.request.urlopen(self._url, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - network flakiness is expected
            return None
        return self._parse(body)


class PdhSensor:
    """Any Windows performance counter, wildcard included.

    The built-in energy-meter source is just this with a known counter path and
    nicer labels, so a new counter is a config stanza rather than new code.
    """

    def __init__(self, entry: dict[str, Any]) -> None:
        self.name = f"pdh:{entry.get('prefix') or entry.get('key', '?')}"
        self._entry = entry
        self._counter = entry["counter"]
        self._prefix = entry.get("prefix") or entry.get("key")
        self._single = "(*)" not in self._counter
        self._query = None
        self._instances: list[str] = []

    def available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            from wattop.sources._pdh import PdhWildcardQuery

            query = PdhWildcardQuery(self._counter)
        except OSError:
            return False
        values = query.prime()
        if not values:
            query.close()
            return False
        self._query = query
        self._instances = sorted(values)
        return True

    def channels(self) -> list[Channel]:
        if self._single:
            return [_channel(self._entry, key=self._prefix, label=self._entry.get("label"))]
        return [
            _channel(self._entry, key=f"{self._prefix}.{inst}", label=inst)
            for inst in self._instances
        ]

    def read(self) -> dict[str, float]:
        if self._query is None:
            return {}
        raw = self._query.read()
        if self._single:
            if not raw:
                return {}
            value = next(iter(raw.values()))
            return {self._prefix: _convert(self._entry, value)}
        return {
            f"{self._prefix}.{name}": _convert(self._entry, value) for name, value in raw.items()
        }

    def close(self) -> None:
        if self._query is not None:
            self._query.close()
            self._query = None

"""`--log FILE` writers.

CSV is always available. Parquet is opt-in (`pip install wattop[parquet]`) and
buffers in memory until close, since Parquet has no meaningful append.
"""

from __future__ import annotations

import contextlib
import csv
import datetime as dt
from pathlib import Path

from wattop.core.sampler import Sample


class CsvSink:
    def __init__(self, path: Path, keys: list[str]) -> None:
        self._keys = keys
        existed = path.exists() and path.stat().st_size > 0
        self._fh = path.open("a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._fh)
        if not existed:
            self._writer.writerow(["timestamp", "t", *keys])

    def write(self, sample: Sample) -> None:
        stamp = dt.datetime.fromtimestamp(sample.t).isoformat(timespec="milliseconds")
        row = [stamp, f"{sample.t:.3f}"]
        for key in self._keys:
            value = sample.values.get(key)
            row.append("" if value is None else f"{value:.6g}")
        self._writer.writerow(row)
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


class ParquetSink:
    def __init__(self, path: Path, keys: list[str]) -> None:
        import pyarrow  # noqa: F401  -- fail early with a clear message

        self._path = path
        self._keys = keys
        self._rows: list[dict[str, float | None]] = []

    def write(self, sample: Sample) -> None:
        row: dict[str, float | None] = {"t": sample.t}
        for key in self._keys:
            row[key] = sample.values.get(key)
        self._rows.append(row)

    def close(self) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        columns = {"t": [r["t"] for r in self._rows]}
        for key in self._keys:
            columns[key] = [r.get(key) for r in self._rows]
        pq.write_table(pa.table(columns), self._path)


@contextlib.contextmanager
def open_sink(path: str, keys: list[str]):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() in {".parquet", ".pq"}:
        try:
            sink = ParquetSink(target, keys)
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise SystemExit(
                "wattop: parquet output needs pyarrow (install the 'parquet' extra), "
                "or use a .csv path instead"
            ) from exc
    else:
        sink = CsvSink(target, keys)
    try:
        yield sink
    finally:
        sink.close()

"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from wattop import __version__
from wattop.core.aggregates import attach_builtin_aggregates
from wattop.core.config import load as load_config
from wattop.core.registry import build_sources
from wattop.core.sampler import Sampler

log = logging.getLogger("wattop")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wattop",
        description="Live power in/out, volts and amps, in the terminal.",
    )
    p.add_argument("--version", action="version", version=f"wattop {__version__}")
    p.add_argument("-c", "--config", metavar="FILE", help="path to config.toml")
    p.add_argument(
        "-i", "--interval", type=float, metavar="SEC", help="seconds between samples (default 1.0)"
    )
    p.add_argument("--history", type=int, metavar="N", help="samples kept for the graphs")
    p.add_argument(
        "--graph-height",
        type=int,
        metavar="ROWS",
        help="rows per headline graph (default: fill the window)",
    )

    mode = p.add_argument_group("modes (default is the live TUI)")
    mode.add_argument(
        "--list", action="store_true", help="list every discovered channel and exit"
    )
    mode.add_argument("--once", action="store_true", help="print one sample and exit")
    mode.add_argument(
        "--json", action="store_true", help="emit JSON lines instead of a table (with --once/--log)"
    )
    mode.add_argument(
        "--log",
        metavar="FILE",
        help="append samples to FILE (.csv, or .parquet with the parquet extra)",
    )
    mode.add_argument(
        "-n",
        "--count",
        type=int,
        metavar="N",
        help="stop after N samples (applies to --log and --json)",
    )
    p.add_argument("--debug", action="store_true", help="log source probing failures")
    return p


def make_sampler(args):
    cfg = load_config(args.config)
    interval = args.interval if args.interval is not None else cfg.interval
    history = args.history if args.history is not None else cfg.history

    import wattop.sources  # noqa: F401  -- importing registers the built-ins

    sources = build_sources(extra=cfg.sensors)
    sampler = Sampler(
        sources=sources,
        derived=cfg.derived,
        history_len=history,
        overrides=cfg.overrides,
    )
    attach_builtin_aggregates(sampler)
    if cfg.path is not None:
        log.debug("config loaded from %s", cfg.path)
    return sampler, interval, cfg


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    sampler, interval, cfg = make_sampler(args)
    if not sampler.channels:
        print(
            "wattop: no power sensors found on this machine.\n"
            "Run with --debug to see which sources were probed and why they "
            "declined, or declare one in config.toml.",
            file=sys.stderr,
        )
        return 1

    try:
        if args.list:
            return cmd_list(sampler, as_json=args.json)
        if args.once:
            return cmd_once(sampler, interval, as_json=args.json)
        if args.log:
            return cmd_log(sampler, interval, args.log, args.count)
        if args.json:
            return cmd_stream(sampler, interval, args.count)
        return cmd_tui(sampler, interval, args.graph_height, cfg.graph_weights or None)
    except KeyboardInterrupt:
        return 130
    finally:
        sampler.close()


def cmd_list(sampler: Sampler, as_json: bool = False) -> int:
    from wattop.render import render_list

    # One sample so the listing can show live values next to the channels.
    sampler.sample()
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "key": c.key,
                        "label": c.label,
                        "unit": c.unit,
                        "group": c.group,
                        "role": c.role,
                        "value": sampler.latest.values.get(c.key),
                    }
                    for c in sampler.channels.values()
                ],
                indent=2,
            )
        )
    else:
        print(render_list(sampler))
    return 0


def cmd_once(sampler: Sampler, interval: float, as_json: bool = False) -> int:
    from wattop.render import render_table

    # Rate counters and energy-delta sources need two reads to say anything, so
    # take a throwaway sample first.
    sampler.sample()
    time.sleep(min(interval, 1.0))
    sample = sampler.sample()

    if as_json:
        print(json.dumps({"t": sample.t, **sample.values}))
    else:
        print(render_table(sampler))
    return 0


def cmd_stream(sampler: Sampler, interval: float, count: int | None) -> int:
    sampler.sample()
    emitted = 0
    while count is None or emitted < count:
        time.sleep(interval)
        sample = sampler.sample()
        print(json.dumps({"t": sample.t, **sample.values}), flush=True)
        emitted += 1
    return 0


def cmd_log(sampler: Sampler, interval: float, path: str, count: int | None) -> int:
    from wattop.logging_sink import open_sink

    keys = [c.key for c in sampler.channels.values()]
    sampler.sample()
    with open_sink(path, keys) as sink:
        written = 0
        while count is None or written < count:
            time.sleep(interval)
            sample = sampler.sample()
            sink.write(sample)
            written += 1
    return 0


def cmd_tui(
    sampler: Sampler,
    interval: float,
    graph_height: int | None = None,
    graph_weights: dict[str, float] | None = None,
) -> int:
    from wattop.ui.app import WattopApp

    WattopApp(
        sampler=sampler,
        interval=interval,
        graph_height=graph_height,
        graph_weights=graph_weights,
    ).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

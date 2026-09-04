# Changelog

All notable changes to wattop are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `python -m wattop`, which works when the installed console script is not on
  PATH. `pip install --user` on Windows is the case people actually hit.

## [0.1.0] - 2026-09-04

### Added
- CPU and memory graphs, sourced from the Processor Information counterset and
  `GlobalMemoryStatusEx` on Windows and from `/proc/stat` and `/proc/meminfo` on
  Linux. Both emit the same channel keys, so the dashboard is the same screen on
  either platform.
- `s` shows or hides the per-rail and per-zone sensor panels. `--details` starts
  a run with them open; `show_details` in `config.toml` makes that the default.
- A test suite, and CI across Linux and Windows on both x86-64 and ARM64.
- Apache-2.0 licence, and packaging metadata good enough to publish.

### Fixed
- Quitting could print a traceback: the poll timer kept firing during teardown
  and repainted widgets that had already gone.
- `--list` reported rate-derived channels, such as processor utilisation, as a
  flat zero. It took a single sample, which gave them no interval to divide by.
- A misspelled `group` or `role` in `[overrides]` was accepted silently, so the
  channel was sampled and logged but never appeared on screen. It now warns.
- `rich` is declared as a dependency. It was imported directly by the dashboard
  and happened to resolve only because Textual pulls it in.

### Changed
- The Textual floor is now 2.1, which is the oldest release the dashboard has
  actually been exercised against, rather than the 0.80 that was never tested.

### Removed
- `block_graph` and its glyph tables, superseded by the braille renderer.

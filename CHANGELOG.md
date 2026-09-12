# Changelog

All notable changes to wattop are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.3] - 2026-09-12

### Added
- A **FAN** headline graph: the fastest fan of however many the machine
  reports, as a derived aggregate the way TEMP is the hottest sensor. Fanless
  machines get no panel. `fan` is also a valid `role` for `[[sensor]]` entries.
- Sources read the axis ceilings sysfs already declares -- `powerN_cap_max` /
  `powerN_cap` and `fanN_max` from hwmon, `constraint_0_max_power_uw` from RAPL
  powercap -- into `nominal_max`, where the stepped axes treat them as the top
  rung. The invented 140 W on the hwmon headline is gone.

### Changed
- Above their tuned rungs the power axes climb in 25 W steps instead of the
  1-2-5 grid, whose 100-to-200 doubling let a 0.06 W excursion past a 100 W cap
  waste half the panel for the rest of the run. The fan axis climbs thousands.
  A reading past a declared ceiling steps up rather than clipping.
- TEMP and FAN moved up to the 22% height tier, and headline pairing order in a
  weight tie is now deliberate: CPU with MEM, FAN beside OUT where roles are
  few, TEMP taking the spanned row in an odd set.

## [0.1.2] - 2026-09-11

### Fixed
- Graphs sharing a grid row ended at different lines: a graph's height came
  from its weight alone, so with four headline roles every row had a shorter
  member and a ragged gap under it. Each row's members now stretch to its
  tallest.
- Axis labels of five figures and up overflowed their field, pushing the top
  row of the plot past the crop and silently dropping its newest sample. They
  shed precision instead.
- Sensor panels were budgeted against the app width rather than their own
  content width, which could tear rows on a narrow window with long labels.
- tmux and byobu named the window "python3". The process title now says
  wattop, via a Linux-only `setproctitle` dependency whose import is guarded,
  so a build without it loses only the name.

### Changed
- The catch-all OTHER group -- GPU clocks and whatever else a source reads but
  cannot classify -- is a detail panel now, opened with `s` like rails and
  thermal zones.
- Default history doubled to 480 samples: braille packs two samples per cell,
  and 240 left the left third of a wide portrait plot permanently blank.

## [0.1.1] - 2026-09-04

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

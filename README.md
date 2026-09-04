# wattop

A btop-style terminal power monitor: **power in, power out, volts and amps**, next to the processor
and memory load that explains them, plus whatever per-rail SoC power the machine is willing to tell
you about.

It exists because btop can't do this. `btop4win` reads the battery through `GetSystemPowerStatus()`,
which gives percent and time remaining and nothing else — the watts code path that mainline Linux
btop has does not exist in the Windows port. `bottom` shows battery watts but no volts, no amps, and
no per-rail power. Neither has a plugin system, so there is no way to add a sensor short of
recompiling.

```
╭─ OUT  System ────────────────────────────────────────────────────────╮
│  60.0                                                                │
│                                                                      │
│                                                                      │
│            ⢀⣀⣠⣤⣶⣶⣤⣤⣀⣀              ⢀⣀⣤⣤⣴⣶⣤⣤⣤⣀⡀           ⢀⣠⣤⣤⣴⣴⣤⣤⣄⡀  │
│        ⢀⣠⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣦⣤⣀⣀⣀⣀⢀⣀⣠⣤⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣶⣦⣤⣤⣤⣤⣴⣶⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣶│
│       ⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
│   0.0 ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
╰───────────────────────────────────────────────── 22.93 W ████░░░░░░ ─╯
╭─ BATT  Battery ──────────────────────────────────────────────────────╮
│  25.0  ⢀⣀  ⢀                                                         │
│       ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣾⣷⣶⣷⣶⣶⣶⣴⣶⣤⣤⣤⣤⣄⣠⣀⣀⣀⢀⣀                                  │
│       ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣾⣶⣶⣤⣤⣤⣄⣀⡀⡀⡀                    │
│       ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣷⣶⣦⣴⣤⣄⣀           │
│       ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣾⣶⣤⣤⣀⣀⣀ │
│       ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
│   0.0 ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
╰───────────────────────────────────────────────── +7.59 W ███░░░░░░░ ─╯
╭─ CPU  Processor ─────────────────────────────────────────────────────╮
│ 100.0         ⣀⣠⣤⣀⡀                   ⣀⣠⣄⣀⡀                 ⣀⣠⣤⣀⡀    │
│            ⢀⣴⣾⣿⣿⣿⣿⣿⣶⣄              ⢀⣴⣾⣿⣿⣿⣿⣿⣶⣄            ⢀⣴⣾⣿⣿⣿⣿⣿⣶⣄  │
│          ⣀⣴⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣄⡀         ⣠⣴⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣦⡀       ⣠⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⣄│
│       ⢀⣤⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣦⣄⣀  ⢀⣀⣤⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣶⣦⣤⣤⣤⣴⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
│   0.0 ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
╰──────────────────────────────────────────────────── 47 % █████░░░░░ ─╯
╭─ MEM  In use ────────────────────────────────────────────────────────╮
│  15.6                                                                │
│                    ⣀⣀⣀⡀             ⢀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀⣠⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤│
│       ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
│       ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
│   0.0 ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
╰──────────────────────────────────────────────── 11.01 GB ███████░░░ ─╯
╭─ IN  Charger in ─────────────────────────────────────────────────────╮
│  60.0 ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
│       ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
│   0.0 ⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
╰───────────────────────────────────────────────── 59.45 W ██████████ ─╯
╭─ TEMP  Hottest sensor ───────────────────────────────────────────────╮
│ 100.0                                                                │
│            ⣀⣀⣀⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣄⣀⣀⣀⣀⣀⣤⣤⣤⣤⣤⣤⣤⣤⣶⣶⣶⣦⣶⣦⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣤⣶⣤⣤⣤⣤⣤│
│  40.0 ⣶⣶⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿│
╰─────────────────────────────────────────────── 69.3 degC █████░░░░░ ─╯
Voltage 8.630 V  Current +5.220 A  ██████████████░░░░  78.6%  49.4/62.9 Wh  charging
```

Six graphs, three rows, in the order they earn: **OUT** and **BATT** are the two that actually move,
so they take the top row at 30% of the window each. **CPU** and **MEM** sit under them at 22%, since
what the machine is doing is the explanation for what it is drawing and the two want reading
together. **IN** and **TEMP** get 16% on the bottom row — the charger rail sits at its ceiling most
of the time and the hottest sensor moves slowly, so both are read as a number more often than as a
shape. Retune per role in `config.toml`:

```toml
[graphs]
power_out = 0.3
battery_power = 0.3
cpu = 0.2
memory = 0.2
```

`--graph-height N` pins every graph instead.

The panel of per-rail power and per-zone temperatures under the graphs starts closed. Press `s` to
open it, `--details` to start a run with it open, or set `show_details = true` in `config.toml` to
make that the default. Closed is the default because on most machines those rows are a screenful of
numbers that rarely move, and they are rows the graphs wanted; the one thing they were read for at a
glance already survives as **TEMP**. Either way the channels are always sampled and always reach
`--list`, `--once`, `--json` and `--log`. If per-rail SoC power is the reason you are here, turn it
on and leave it on.

Every power graph is floored at zero on a fixed axis, so bar height means watts and one frame is
comparable to the last. **OUT** and **BATT** sit on a two-rung ladder: 0-25 W by default, which is
where the machine spends most of its life and where a single tall axis would squash everything into
the bottom third, and 0-60 W for as long as the window on screen holds a sample above 25 W. Each
picks its own rung from its own window, so a burst on one leaves the other where it was, and once
the burst scrolls off the axis drops back. **IN** keeps the ceiling its rail declares, and **CPU**
and **MEM** keep theirs: there is nothing above 100% of a processor and nothing above the RAM the
machine has, so both axes are the real limit rather than a guess, and the memory graph prints the
installed total as its top label. **TEMP** is the one graph that does not start at zero -- it runs a
fixed 40-100 degC, since the hottest sensor in a running machine never approaches zero and silicon
throttles just under 100, so the panel height is all live range and doubles as "how close to too
hot". Both bounds are printed on the axis, so what you are looking at is never ambiguous.

**BATT** plots magnitude — how hard the battery is working — and lets colour carry the direction:
amber discharging, green charging. Pin any ceiling you would rather set yourself with
`[overrides."<key>"] nominal_max`, and the ladder steps aside.

## What it can read

**Windows on a Snapdragon X Elite** — this is the good case. Windows surfaces the platform's EMI
(Energy Meter Interface) channels as ordinary performance counters, so the charger input rail is
*measured*, not inferred:

| Channel | Source |
|---|---|
| `emi.PSU_USB` | power in, from the USB-C charger |
| `emi.SYS` | system rail |
| `emi.USBC_TOTAL`, `emi.CPU_CLUSTER_0..2`, `emi.GPU` | per-rail SoC power |
| `batt.power` / `.voltage` / `.current` / `.charge` / `.level` / `.temp` / `.cycles` | the battery device, via `IOCTL_BATTERY_QUERY_STATUS` |
| `batt.eta.avg` | time left, from battery watts averaged over a growing window |
| `cpu.util` | `% Processor Time` off the `Processor Information` counterset |
| `mem.used` / `mem.total` | physical memory, from `GlobalMemoryStatusEx` |

Battery `Rate` is signed, so discharging falls out of the sign and current is a real division rather
than an estimate. Everything works **without administrator rights** and costs about 0.1 ms a sample.

CPU is the not-idle fraction, the same thing btop counts and the same thing `/proc/stat` gives on
Linux. Windows also offers `% Processor Utility`, which scales that by the frequency actually
delivered -- it is what Task Manager shows, and it tracks the **OUT** graph more closely, because a
core parked at its lowest clock and never quite idle is 100% busy and a couple of watts. Measured on
this laptop, idling at about a third of nominal, Utility reads about a third of Time for the same
work. wattop shows Time anyway: a CPU number that disagrees three-to-one with every other load meter
on the machine costs more than the tighter correlation buys.

The one reading wattop computes rather than reads is **time left**. Windows will hand you a
`BatteryEstimatedTime`, but it is derived from the instantaneous rate, and an idle machine breathing
between 15 and 25 W makes that estimate swing by the better part of an hour from one second to the
next -- measured here, 55 minutes of swing across 45 seconds of sitting still. So `batt.eta.avg`
averages the *watts* over a window that grows to five minutes from the last plug/unplug and rolls
after that, and divides once. Averaging the rate rather than the estimate is the point: time left is
hyperbolic in power, so a single near-idle sample is an absurd ETA but an unremarkable watt figure.
The same average against the charging rate gives a time to full, which Windows does not offer at
all. Set `eta_window` in `config.toml` to trade steadiness against how fast it notices a new load.

**Linux** — `/sys/class/hwmon` is walked and everything found is exposed, so the headline number on
an AMD APU is `power1_average` from the `amdgpu` node (package power, the same PPT figure `ryzenadj`
reports, no root needed). RAPL via powercap is picked up when readable, and laptops additionally get
`/sys/class/power_supply`. CPU and memory come from `/proc/stat` and `/proc/meminfo` under the
same two keys the Windows pair uses, so the dashboard is the same screen on both.

Be aware of what a Ryzen AI Max+ 395 desktop **cannot** give you: no voltage or current anywhere
(Zen 5 uses SVI3 and no in-tree driver reads it), and no true "power in" (a desktop has no charger
rail, and the Framework EC exposes no PSU wattage). For real wall power there, point the
`http_json` source at a smart plug — see below.

## Install

Needs Python 3.11+. On Windows ARM64, pin the native interpreter explicitly — `uv` itself is an
x86_64 build and will otherwise hand you an emulated Python:

```console
$ uv venv --python cpython-3.12-windows-aarch64
$ uv sync
```

Everywhere else `uv sync` is enough. Then:

```console
$ uv run wattop
```

## Usage

```console
$ wattop                     # the live dashboard
$ wattop --list              # every channel discovered, with its group and role
$ wattop --once              # one snapshot, then exit
$ wattop --once --json       # ... as JSON, for a prompt segment or an OSD
$ wattop --json -n 60        # a stream of JSON lines
$ wattop --log power.csv     # append samples to CSV (or .parquet with the extra)
$ wattop --details           # start with the per-rail sensor panels open
$ wattop -i 0.25             # faster sampling
```

In the TUI: `q` quit, `p` pause, `s` show or hide the per-rail and per-zone sensor panels,
`+`/`-` change the interval.

`--log` writes its header from the channels discovered at startup and skips it when the file
already has one, so start a new file rather than appending to a log written before a machine
grew a sensor -- the new columns land in the middle of the row, not at the end.

## Adding a reading

The UI never names a sensor. It lays out by **group** (`in`, `out`, `battery`, `system`, `rails`,
`thermal`) and headlines whatever fills each **role** (`power_in`, `power_out`, `battery_power`,
`battery_voltage`, `battery_current`, `battery_charge`, `battery_level`, `battery_eta`, `ac_online`,
`temperature`, `cpu`, `memory`). So a new reading only ever needs to declare where it belongs, and
the display follows. `rails` and `thermal` are sampled but not drawn, so anything you want on
screen wants one of the other groups or a role -- including a rail you miss, which
`[overrides."emi.GPU"] group = "other"` puts back.

That makes adding one come in three sizes.

**1. Nothing.** A new instance of an already-wrapped source is discovered on its own — another
`Energy Meter` rail after a firmware update, another `hwmon` node after a kernel bump.

**2. A config stanza.** Copy `config.example.toml` to `config.toml` (or
`~/.config/wattop/config.toml`, or `%APPDATA%\wattop\config.toml`):

```toml
[[sensor]]
source = "http_json"                              # a Tasmota smart plug: real wall watts
url     = "http://plug.lan/cm?cmnd=Status%2010"
pointer = "/StatusSNS/ENERGY/Power"
key = "wall"; label = "Wall"; unit = "W"; group = "in"; role = "power_in"

[[derived]]
key = "efficiency"; label = "Charger loss"; unit = "W"; group = "other"
expr = "emi.PSU_USB - emi.SYS - batt.power"
```

Generic sources: `sysfs` (a number in a file), `exec` (a command), `http_json` (an endpoint),
`pdh` (any Windows performance counter, wildcards included). `[[derived]]` computes channels from
other channels; `[overrides."key"]` relabels or regroups a built-in one.

**3. A new file in `wattop/sources/`.** Only needed for a genuinely new OS API. Implement four
methods, add `@register`, and change nothing else:

```python
@register
class MySource:
    name = "my_source"
    def available(self) -> bool: ...      # cheap probe; False means "skip me quietly"
    def channels(self) -> list[Channel]: ...
    def read(self) -> dict[str, float]: ...
    def close(self) -> None: ...
```

A source that fails to construct, discover or read is logged and skipped — a broken sensor never
costs you the rest of the dashboard. Run with `--debug` to see what declined and why.

## Layout

```
wattop/core/      Channel + Source protocol, registry, sampler, config, derived expressions
wattop/sources/   win_energy_meter, win_battery, win_thermal, win_system,
                  linux_hwmon, linux_powercap, linux_power_supply, linux_system,
                  generic (sysfs/exec/http_json/pdh)
wattop/ui/        the Textual dashboard
wattop/render.py  sparklines, bars, the text tables used by --list and --once
```

# wattop

A btop-style terminal power monitor: **power in, power out, volts and amps**, plus whatever per-rail
SoC power the machine is willing to tell you about.

It exists because btop can't do this. `btop4win` reads the battery through `GetSystemPowerStatus()`,
which gives percent and time remaining and nothing else — the watts code path that mainline Linux
btop has does not exist in the Windows port. `bottom` shows battery watts but no volts, no amps, and
no per-rail power. Neither has a plugin system, so there is no way to add a sensor short of
recompiling.

```
┌─ IN  Charger in ──────────────────────────────────────────────────────┐
│  59.7                                    ███████████████              │
│       ████████████████████████████████████████████████████            │
│  58.7 ██████████████████████████████████████████████████████          │
└────────────────────────────────────────────────────── 59.37 W ██████░─┘
┌─ OUT  System ─────────────────────────────────────────────────────────┐
│  29.5     ▂▃▁                ▃▃▁                                      │
│         ▁▇███▄             ▂████▃                                     │
│        ▂██████▅           ▃██████▄          ▂                         │
│       ▁████████▅         ▃████████▄         █                         │
│       ██████████▄       ▂██████████▃      ▃▄█                         │
│       ████████████▆▂ ▁▄██████████████▅▁ ▁▅███                         │
│   6.5 ████████████████████████████████████████                        │
└────────────────────────────────────────────────────── 15.59 W ███░░░░─┘
┌─ BATT  Battery ───────────────────────────────────────────────────────┐
│  47.3                                                                 │
│       ████████████████████████████████████████                        │
│  42.8 ████████████████████████████████████████                        │
└─────────────────────────────────────────────────────────── +45.09 W ──┘
Voltage 8.629 V  Current +5.225 A  ██████████████░░░░  78.6%  49.4/62.9 Wh  charging

RAILS
USB-C ports       9.30 W  ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
CPU_CLUSTER_0     1.48 W  ▆▇████▇▆▅▄▄▃▄▅▆▇███▇
CPU_CLUSTER_1     0.74 W  ██████████████████▅▅
GPU               0.10 W  ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇██
```

**OUT** and **BATT** take a quarter of the window each — they are the two that actually move — and
the charger rail makes do with the leftover, since it sits at its ceiling most of the time. Retune
per role in `config.toml`:

```toml
[graphs]
power_out = 0.25
battery_power = 0.25
```

`--graph-height N` pins every graph instead.

Every power graph is floored at zero on a fixed axis, so bar height means watts and one frame is
comparable to the last. **OUT** and **BATT** sit on a two-rung ladder: 0-25 W by default, which is
where the machine spends most of its life and where a single tall axis would squash everything into
the bottom third, and 0-60 W for as long as the window on screen holds a sample above 25 W. Each
picks its own rung from its own window, so a burst on one leaves the other where it was, and once
the burst scrolls off the axis drops back. **IN** keeps the ceiling its rail declares. **TEMP** is
the one graph that does not start at zero -- it runs a fixed 40-100 degC, since the hottest sensor
in a running machine never approaches zero and silicon throttles just under 100, so the panel height
is all live range and doubles as "how close to too hot". Both bounds are printed on the axis, so
what you are looking at is never ambiguous.

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

Battery `Rate` is signed, so discharging falls out of the sign and current is a real division rather
than an estimate. Everything works **without administrator rights** and costs about 0.1 ms a sample.

**Linux** — `/sys/class/hwmon` is walked and everything found is exposed, so the headline number on
an AMD APU is `power1_average` from the `amdgpu` node (package power, the same PPT figure `ryzenadj`
reports, no root needed). RAPL via powercap is picked up when readable, and laptops additionally get
`/sys/class/power_supply`.

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
$ wattop -i 0.25             # faster sampling
```

In the TUI: `q` quit, `p` pause, `+`/`-` change the interval.

## Adding a reading

The UI never names a sensor. It lays out by **group** (`in`, `out`, `battery`, `rails`, `thermal`)
and headlines whatever fills each **role** (`power_in`, `power_out`, `battery_power`,
`battery_voltage`, `battery_current`, `battery_charge`, `battery_level`, `ac_online`). So a new
reading only ever needs to declare where it belongs, and the display follows.

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
wattop/sources/   win_energy_meter, win_battery, linux_hwmon, linux_powercap,
                  linux_power_supply, generic (sysfs/exec/http_json/pdh)
wattop/ui/        the Textual dashboard
wattop/render.py  sparklines, bars, the text tables used by --list and --once
```

"""Fixture sysfs trees.

Every Linux source takes a `root: Path`, so the whole discovery path can be
driven from a temporary directory instead of the machine running the tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def write_tree(base: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return base


@pytest.fixture
def hwmon_root(tmp_path: Path) -> Path:
    """An AMD APU laptop: amdgpu package power plus a couple of thermal chips."""
    return write_tree(
        tmp_path / "hwmon",
        {
            "hwmon0/name": "amdgpu\n",
            # Both offered for the same rail; only the averaged one should survive.
            "hwmon0/power1_average": "31675000\n",
            "hwmon0/power1_input": "30560000\n",
            "hwmon0/power1_label": "PPT\n",
            "hwmon0/temp1_input": "31000\n",
            "hwmon0/temp1_label": "edge\n",
            # Declared but never populated on Strix Halo.
            "hwmon0/in0_input": "0\n",
            "hwmon0/in0_label": "vddgfx\n",
            "hwmon1/name": "k10temp\n",
            "hwmon1/temp1_input": "62000\n",
            "hwmon1/temp1_label": "Tctl\n",
            "hwmon2/name": "cros_ec\n",
            "hwmon2/fan1_input": "1257\n",
            # A genuinely stopped fan, which must NOT be dropped as unpopulated.
            "hwmon2/fan2_input": "0\n",
        },
    )


@pytest.fixture
def battery_root(tmp_path: Path) -> Path:
    """A laptop reporting energy in Wh, discharging, with the mains unplugged."""
    return write_tree(
        tmp_path / "power_supply",
        {
            "BAT0/type": "Battery\n",
            "BAT0/status": "Discharging\n",
            "BAT0/present": "1\n",
            "BAT0/energy_now": "28560000\n",      # uWh -> 28.56 Wh
            "BAT0/energy_full": "61160000\n",
            "BAT0/energy_full_design": "70000000\n",
            "BAT0/power_now": "15200000\n",       # uW -> 15.2 W
            "BAT0/voltage_now": "8109000\n",      # uV -> 8.109 V
            "BAT0/capacity": "47\n",
            "AC/type": "Mains\n",
            "AC/online": "0\n",
        },
    )


@pytest.fixture
def powercap_root(tmp_path: Path) -> Path:
    return write_tree(
        tmp_path / "powercap",
        {
            "intel-rapl:0/name": "package-0\n",
            "intel-rapl:0/energy_uj": "123456789\n",
            "intel-rapl:0/max_energy_range_uj": "262143328850\n",
        },
    )

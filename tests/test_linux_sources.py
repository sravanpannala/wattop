"""The Linux sources, driven from fixture sysfs trees.

Skipped on Windows: every one of these sources refuses outright when
`sys.platform == "win32"`, before it ever looks at `root`.
"""

from __future__ import annotations

import sys

import pytest

from wattop.sources.linux_hwmon import HwmonSource
from wattop.sources.linux_power_supply import PowerSupplySource
from wattop.sources.linux_powercap import PowercapSource

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="Linux sources decline on Windows by design"
)


def keys(src) -> set[str]:
    return {c.key for c in src.channels()}


def by_key(src) -> dict:
    return {c.key: c for c in src.channels()}


class TestHwmon:
    def test_discovers_a_fixture_tree(self, hwmon_root):
        src = HwmonSource(root=hwmon_root)
        assert src.available()
        assert src.channels()

    def test_prefers_power1_average_over_power1_input(self, hwmon_root):
        """amdgpu offers both for the same rail; showing both invites the
        question of which to believe."""
        src = HwmonSource(root=hwmon_root)
        src.available()
        found = keys(src)
        assert "hwmon.amdgpu.power1_average" in found
        assert "hwmon.amdgpu.power1_input" not in found

    def test_amdgpu_package_power_takes_the_headline_role(self, hwmon_root):
        src = HwmonSource(root=hwmon_root)
        src.available()
        ch = by_key(src)["hwmon.amdgpu.power1_average"]
        assert ch.role == "power_out"
        assert ch.group == "out"

    def test_only_one_channel_claims_the_headline(self, hwmon_root):
        src = HwmonSource(root=hwmon_root)
        src.available()
        assert sum(c.role == "power_out" for c in src.channels()) == 1

    def test_unpopulated_voltage_rails_are_dropped(self, hwmon_root):
        """vddgfx reads a hard zero forever; a channel stuck at 0.000 V is
        worse than an absent one."""
        src = HwmonSource(root=hwmon_root)
        src.available()
        assert "hwmon.amdgpu.in0_input" not in keys(src)

    def test_a_stopped_fan_is_kept(self, hwmon_root):
        """0 RPM means the fan is off, which is a real reading."""
        src = HwmonSource(root=hwmon_root)
        src.available()
        assert "hwmon.cros_ec.fan2_input" in keys(src)

    def test_reads_scaled_values(self, hwmon_root):
        src = HwmonSource(root=hwmon_root)
        src.available()
        values = src.read()
        assert values["hwmon.amdgpu.power1_average"] == pytest.approx(31.675)
        assert values["hwmon.k10temp.temp1_input"] == pytest.approx(62.0)
        assert values["hwmon.cros_ec.fan1_input"] == pytest.approx(1257)

    def test_labels_come_from_the_label_file(self, hwmon_root):
        src = HwmonSource(root=hwmon_root)
        src.available()
        assert by_key(src)["hwmon.amdgpu.power1_average"].label == "amdgpu PPT"

    def test_declines_on_an_empty_tree(self, tmp_path):
        empty = tmp_path / "hwmon"
        empty.mkdir()
        assert not HwmonSource(root=empty).available()

    def test_declines_when_the_tree_does_not_exist(self, tmp_path):
        assert not HwmonSource(root=tmp_path / "nope").available()


class TestPowerSupply:
    def test_discovers_a_battery(self, battery_root):
        src = PowerSupplySource(root=battery_root)
        assert src.available()
        assert any(c.role == "battery_power" for c in src.channels())

    def test_converts_microwatt_hours_to_watt_hours(self, battery_root):
        src = PowerSupplySource(root=battery_root)
        src.available()
        values = src.read()
        charge = next(c.key for c in src.channels() if c.role == "battery_charge")
        assert values[charge] == pytest.approx(28.56)

    def test_reads_voltage_in_volts(self, battery_root):
        src = PowerSupplySource(root=battery_root)
        src.available()
        volts = next(
            (c.key for c in src.channels() if c.role == "battery_voltage"), None
        )
        if volts is not None:
            assert src.read()[volts] == pytest.approx(8.109)

    def test_mains_offline_is_reported(self, battery_root):
        src = PowerSupplySource(root=battery_root)
        src.available()
        ac = next((c.key for c in src.channels() if c.role == "ac_online"), None)
        assert ac is not None
        assert src.read()[ac] == 0.0

    def test_declines_with_no_supplies(self, tmp_path):
        empty = tmp_path / "power_supply"
        empty.mkdir()
        assert not PowerSupplySource(root=empty).available()


class TestPowercap:
    def test_declines_when_energy_uj_is_unreadable(self, powercap_root):
        """Since the PLATYPUS mitigation energy_uj is 0400 on most distros. The
        source must drop out quietly rather than erroring."""
        energy = powercap_root / "intel-rapl:0" / "energy_uj"
        energy.chmod(0o000)
        try:
            src = PowercapSource(root=powercap_root)
            # Either it declines, or it read the file anyway (running as root,
            # or a filesystem that ignores the mode). Both are acceptable; what
            # must not happen is an exception.
            src.available()
        finally:
            energy.chmod(0o644)

    def test_declines_when_the_tree_does_not_exist(self, tmp_path):
        assert not PowercapSource(root=tmp_path / "nope").available()

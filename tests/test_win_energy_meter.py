"""Rail classification for the Windows Energy Meter counters.

`_classify` is pure and platform-free, so it is testable on any machine. The
source around it is not: it needs a real PDH provider.
"""

from __future__ import annotations

import pytest

from wattop.sources.win_energy_meter import _classify


class TestSnapdragon:
    def test_the_charger_rail_is_power_in(self):
        label, group, role, nominal = _classify("PSU_USB")
        assert (group, role) == ("in", "power_in")
        assert label == "Charger in"
        assert nominal == 60.0

    def test_the_system_rail_is_power_out(self):
        assert _classify("SYS")[1:3] == ("out", "power_out")

    @pytest.mark.parametrize("rail", ["NPU", "GPU", "MEMORY", "MULTIMEDIA", "SOC"])
    def test_named_soc_rails_get_a_label_but_no_role(self, rail):
        label, group, role, nominal = _classify(rail)
        assert group == "rails"
        assert role is None
        assert nominal is None
        assert label


class TestRapl:
    def test_the_package_rail_headlines(self):
        label, group, role, _ = _classify("RAPL_Package0_PKG")
        assert (group, role) == ("out", "power_out")
        assert "Package0" in label

    @pytest.mark.parametrize(
        "instance, expected",
        [
            ("RAPL_Package0_PP0", "CPU cores"),
            ("RAPL_Package0_PP1", "Integrated GPU"),
            ("RAPL_Package0_DRAM", "Memory"),
            ("RAPL_Package0_PSYS", "Platform"),
        ],
    )
    def test_domains_are_labelled_and_stay_rails(self, instance, expected):
        label, group, role, _ = _classify(instance)
        assert group == "rails"
        assert role is None
        assert label.startswith(expected)

    def test_the_socket_index_survives_into_the_label(self):
        """A two-socket box must not show two rails both called CPU cores."""
        assert _classify("RAPL_Package0_PP0")[0] != _classify("RAPL_Package1_PP0")[0]

    def test_per_core_rails_are_left_under_their_raw_name(self):
        label, group, role, _ = _classify("RAPL_Package0_Core0_CORE")
        assert label == "RAPL_Package0_Core0_CORE"
        assert (group, role) == ("rails", None)

    def test_case_is_not_load_bearing(self):
        assert _classify("rapl_package0_pkg")[2] == "power_out"


def test_an_unknown_rail_still_appears_under_its_own_name():
    """An unrecognised name costs a nice label and nothing else."""
    label, group, role, nominal = _classify("SOME_FUTURE_RAIL")
    assert label == "SOME_FUTURE_RAIL"
    assert (group, role, nominal) == ("rails", None, None)


def test_no_guessed_axis_ceiling_on_unmeasured_hardware():
    """Only the two rails measured on the reference laptop carry a nominal_max;
    a guessed ceiling is worse than none."""
    for rail in ("NPU", "RAPL_Package0_PKG", "RAPL_Package0_DRAM", "WHATEVER"):
        assert _classify(rail)[3] is None


@pytest.mark.parametrize(
    "instance, expected",
    [("CPU_CLUSTER_0", "CPU cluster 0"), ("CPU_CLUSTER_2", "CPU cluster 2"),
     ("CPU_CLUSTER_7", "CPU cluster 7")],
)
def test_snapdragon_core_clusters_are_labelled(instance, expected):
    """Measured on the reference laptop; matched by prefix so a chip with more
    clusters needs no change."""
    label, group, role, _ = _classify(instance)
    assert label == expected
    assert (group, role) == ("rails", None)

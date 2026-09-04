"""Config loading. A bad stanza must cost you that stanza, not the file."""

from __future__ import annotations

import pytest

from wattop.core.channel import Channel
from wattop.core.config import apply_override, load


def write(tmp_path, text: str):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_when_no_file_is_given(tmp_path, monkeypatch):
    monkeypatch.setattr("wattop.core.config.default_paths", lambda: [tmp_path / "absent.toml"])
    cfg = load(None)
    assert cfg.interval == 1.0
    assert cfg.history == 240
    assert cfg.show_details is False
    assert cfg.path is None


def test_general_section_is_read(tmp_path):
    cfg = load(write(tmp_path, """
[general]
interval = 0.25
history = 500
eta_window = 120.0
show_details = true
"""))
    assert cfg.interval == 0.25
    assert cfg.history == 500
    assert cfg.eta_window == 120.0
    assert cfg.show_details is True


def test_graph_weights_are_floats_keyed_by_role(tmp_path):
    cfg = load(write(tmp_path, """
[graphs]
power_out = 0.3
cpu = 0.22
"""))
    assert cfg.graph_weights == {"power_out": 0.3, "cpu": 0.22}


def test_a_missing_explicit_config_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "nope.toml")


def test_a_bad_derived_stanza_is_skipped_not_fatal(tmp_path, caplog):
    cfg = load(write(tmp_path, """
[general]
interval = 2.0

[[derived]]
key = "broken"
expr = "__import__('os')"

[[derived]]
key = "fine"
unit = "W"
expr = "a - b"
"""))
    assert cfg.interval == 2.0                      # the rest of the file still loaded
    assert [d.channel.key for d in cfg.derived] == ["fine"]


def test_a_bad_sensor_stanza_is_skipped_not_fatal(tmp_path):
    cfg = load(write(tmp_path, """
[general]
history = 99

[[sensor]]
source = "no_such_source"
key = "nope"
"""))
    assert cfg.history == 99
    assert cfg.sensors == []


def test_overrides_are_read_verbatim(tmp_path):
    cfg = load(write(tmp_path, """
[overrides."emi.GPU"]
group = "other"
label = "Graphics"
"""))
    assert cfg.overrides["emi.GPU"] == {"group": "other", "label": "Graphics"}


class TestApplyOverride:
    def base(self):
        return Channel("emi.GPU", "GPU", "W", "rails", None)

    def test_relabel_and_regroup(self):
        out = apply_override(self.base(), {"label": "Graphics", "group": "other"})
        assert (out.label, out.group) == ("Graphics", "other")
        assert out.key == "emi.GPU"

    def test_nominal_max_is_settable(self):
        assert apply_override(self.base(), {"nominal_max": 25.0}).nominal_max == 25.0

    def test_unknown_fields_are_ignored_rather_than_raising(self):
        """A typo in a config file must not take the dashboard down."""
        out = apply_override(self.base(), {"not_a_field": 1, "label": "GPU rail"})
        assert out.label == "GPU rail"

    def test_the_key_cannot_be_overridden(self):
        out = apply_override(self.base(), {"key": "something.else"})
        assert out.key == "emi.GPU"

"""Pure rendering helpers: axis ceilings, graph bounds, braille plotting."""

from __future__ import annotations

import pytest

from wattop.render import bar, braille_graph, format_eta, graph_bounds, nice_ceil, sparkline


@pytest.mark.parametrize(
    "value, expected",
    [
        (0.0, 1.0), (-5.0, 1.0),
        (0.4, 0.5), (1.0, 1.0), (1.1, 2.0), (2.0, 2.0),
        (2.1, 5.0), (5.0, 5.0), (5.1, 10.0),
        (23.0, 50.0), (60.0, 100.0), (140.0, 200.0),
    ],
)
def test_nice_ceil_snaps_to_the_1_2_5_grid(value, expected):
    assert nice_ceil(value) == pytest.approx(expected)


def test_nice_ceil_is_idempotent_so_the_axis_does_not_creep():
    for v in (0.3, 7.0, 23.0, 61.0, 999.0):
        once = nice_ceil(v)
        assert nice_ceil(once) == pytest.approx(once)


def test_graph_bounds_keeps_zero_inside_a_series_that_crosses_it():
    lo, hi = graph_bounds([-5.0, 2.0, -1.0, 3.0])
    assert lo < 0 < hi


def test_graph_bounds_gives_a_flat_series_a_band_not_a_wall():
    lo, hi = graph_bounds([10.0] * 20)
    assert lo < 10.0 < hi


def test_graph_bounds_on_all_zero_data_says_so_plainly():
    assert graph_bounds([0.0, 0.0, 0.0]) == (0.0, 1.0)


def test_graph_bounds_does_not_stretch_a_negative_series_up_to_zero():
    lo, hi = graph_bounds([-20.0, -18.0, -19.0])
    assert hi <= 0.0
    assert lo < -20.0


def test_braille_graph_returns_exactly_height_rows_of_width_cells():
    rows = braille_graph([1.0, 5.0, 3.0, 9.0], width=20, height=6, lo=0.0, hi=10.0)
    assert len(rows) == 6
    assert all(len(r) == 20 for r in rows)


def test_braille_graph_is_right_aligned_so_new_samples_enter_at_the_right():
    """A short history hugs the right edge, padded on the left with spaces, so
    the newest sample is always in the same place."""
    rows = braille_graph([9.0, 9.0], width=10, height=3, lo=0.0, hi=10.0)
    bottom = rows[-1]
    assert bottom[-1] != " "     # ink at the right edge
    assert bottom[0] == " "      # padding on the left


def test_braille_graph_leaves_a_floor_line_rather_than_a_dead_sensor():
    rows = braille_graph([0.0] * 8, width=8, height=3, lo=0.0, hi=10.0)
    assert any(ch != "⠀" for ch in rows[-1])


def test_braille_graph_clamps_out_of_range_values():
    rows = braille_graph([-50.0, 500.0], width=6, height=4, lo=0.0, hi=10.0)
    assert len(rows) == 4
    assert all(len(r) == 6 for r in rows)


def test_braille_graph_handles_empty_input():
    assert braille_graph([], width=10, height=4) == ["", "", "", ""]


@pytest.mark.parametrize(
    "seconds, expected",
    [(0, "--"), (-1, "--"), (60, "1m"), (599, "9m"), (3600, "1h00m"), (7380, "2h03m")],
)
def test_format_eta(seconds, expected):
    assert format_eta(seconds) == expected


def test_bar_spans_empty_to_full():
    assert bar(0.0, 10.0, width=10).count("█") == 0
    assert bar(10.0, 10.0, width=10).count("█") == 10


def test_bar_clamps_above_maximum():
    assert len(bar(999.0, 10.0, width=10)) == 10


def test_sparkline_emits_one_cell_per_sample_up_to_width():
    assert len(sparkline([1.0, 2.0, 3.0], width=12)) == 3
    assert len(sparkline([1.0] * 40, width=12)) == 12

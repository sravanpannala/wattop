"""The command-line entry points."""

from __future__ import annotations

import subprocess
import sys

from wattop import __version__


def test_python_dash_m_works():
    """The console script lands in a directory that is not always on PATH --
    `pip install --user` on Windows being the case people hit. `python -m`
    needs no PATH, so it has to keep working."""
    out = subprocess.run(
        [sys.executable, "-m", "wattop", "--version"],
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert __version__ in (out.stdout + out.stderr)


def test_version_flag_matches_the_package():
    from wattop.cli import build_parser

    parser = build_parser()
    assert parser.prog == "wattop"

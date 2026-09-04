"""Entry point for `python -m wattop`.

The console script installed by the wheel is the usual way in, but it lands in
a scripts directory that is not always on PATH -- `pip install --user` on
Windows being the case people actually hit, where `wattop` then answers "not
recognized" and the install looks broken. `python -m` needs no PATH at all, so
it is the answer that always works.
"""

from wattop.cli import main

raise SystemExit(main())

"""Importing this package is what registers the built-in sources.

Platform modules are imported conditionally -- `ctypes.wintypes` does not exist
off Windows, and the sysfs sources have nothing to say on it.
"""

from __future__ import annotations

import sys

from wattop.sources import generic  # noqa: F401  (registers nothing, provides builders)

if sys.platform == "win32":
    from wattop.sources import (  # noqa: F401
        win_battery,
        win_energy_meter,
        win_system,
        win_thermal,
    )
else:
    from wattop.sources import (  # noqa: F401
        linux_hwmon,
        linux_power_supply,
        linux_powercap,
        linux_system,
    )

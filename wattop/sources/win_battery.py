"""Windows battery, straight off the battery device.

Everything comes from one handle via DeviceIoControl -- no WMI, no pywin32, no
elevation. `IOCTL_BATTERY_QUERY_STATUS` gives a *signed* charge rate in mW
alongside the pack voltage in mV, so current is a real division rather than a
guess, and the discharge case just falls out of the sign.

Measured on a Yoga Slim 7 14Q8X9 (SMP L23M4PF2) while charging:

    Capacity 23380 mWh, Voltage 7905 mV, Rate +33169 mW  =>  +4.196 A

One ctypes trap worth remembering: the default `restype` of `c_int` truncates
64-bit handles, which makes SetupDiEnumDeviceInterfaces silently return nothing.
Every prototype below is declared explicitly for that reason.
"""

from __future__ import annotations

import ctypes as C
import sys
from ctypes import wintypes as W

from wattop.core.channel import Channel
from wattop.core.registry import register

# Device interface class for batteries.
_GUID_DEVICE_BATTERY = (
    0x72631E54, 0x78A4, 0x11D0, (0xBC, 0xF7, 0x00, 0xAA, 0x00, 0xB7, 0xB3, 0x2A)
)

_DIGCF_PRESENT = 0x02
_DIGCF_DEVICEINTERFACE = 0x10

_IOCTL_BATTERY_QUERY_TAG = 0x294040
_IOCTL_BATTERY_QUERY_INFORMATION = 0x294044
_IOCTL_BATTERY_QUERY_STATUS = 0x29404C

# BATTERY_QUERY_INFORMATION_LEVEL
_BatteryInformation = 0
_BatteryTemperature = 2
_BatteryEstimatedTime = 3

# BATTERY_STATUS.PowerState bits
_BATTERY_POWER_ON_LINE = 0x00000001
_BATTERY_DISCHARGING = 0x00000002
_BATTERY_CHARGING = 0x00000004
_BATTERY_CRITICAL = 0x00000008

_BATTERY_CAPACITY_RELATIVE = 0x40000000

_UNKNOWN_32 = 0xFFFFFFFF
_UNKNOWN_RATE = 0x80000000


class _GUID(C.Structure):
    _fields_ = [
        ("Data1", C.c_ulong),
        ("Data2", C.c_ushort),
        ("Data3", C.c_ushort),
        ("Data4", C.c_ubyte * 8),
    ]


class _SP_DEVICE_INTERFACE_DATA(C.Structure):
    _fields_ = [
        ("cbSize", W.DWORD),
        ("InterfaceClassGuid", _GUID),
        ("Flags", W.DWORD),
        ("Reserved", C.c_ulonglong),
    ]


class _BATTERY_QUERY_INFORMATION(C.Structure):
    _fields_ = [("BatteryTag", W.DWORD), ("InformationLevel", C.c_int), ("AtRate", C.c_long)]


class _BATTERY_WAIT_STATUS(C.Structure):
    _fields_ = [
        ("BatteryTag", W.DWORD),
        ("Timeout", W.DWORD),
        ("PowerState", W.DWORD),
        ("LowCapacity", W.DWORD),
        ("HighCapacity", W.DWORD),
    ]


class _BATTERY_STATUS(C.Structure):
    _fields_ = [
        ("PowerState", W.DWORD),
        ("Capacity", W.DWORD),
        ("Voltage", W.DWORD),
        ("Rate", C.c_long),  # signed: negative while discharging
    ]


class _BATTERY_INFORMATION(C.Structure):
    _fields_ = [
        ("Capabilities", W.DWORD),
        ("Technology", C.c_ubyte),
        ("Reserved", C.c_ubyte * 3),
        ("Chemistry", C.c_char * 4),
        ("DesignedCapacity", W.DWORD),
        ("FullChargedCapacity", W.DWORD),
        ("DefaultAlert1", W.DWORD),
        ("DefaultAlert2", W.DWORD),
        ("CriticalBias", W.DWORD),
        ("CycleCount", W.DWORD),
    ]


def _bind():
    setupapi = C.WinDLL("setupapi", use_last_error=True)
    k32 = C.WinDLL("kernel32", use_last_error=True)

    setupapi.SetupDiGetClassDevsW.restype = C.c_void_p
    setupapi.SetupDiGetClassDevsW.argtypes = [C.POINTER(_GUID), C.c_wchar_p, C.c_void_p, W.DWORD]
    setupapi.SetupDiEnumDeviceInterfaces.restype = W.BOOL
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
        C.c_void_p,
        C.c_void_p,
        C.POINTER(_GUID),
        W.DWORD,
        C.POINTER(_SP_DEVICE_INTERFACE_DATA),
    ]
    setupapi.SetupDiGetDeviceInterfaceDetailW.restype = W.BOOL
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        C.c_void_p,
        C.POINTER(_SP_DEVICE_INTERFACE_DATA),
        C.c_void_p,
        W.DWORD,
        C.POINTER(W.DWORD),
        C.c_void_p,
    ]
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [C.c_void_p]

    k32.CreateFileW.restype = C.c_void_p
    k32.CreateFileW.argtypes = [
        C.c_wchar_p,
        W.DWORD,
        W.DWORD,
        C.c_void_p,
        W.DWORD,
        W.DWORD,
        C.c_void_p,
    ]
    k32.DeviceIoControl.restype = W.BOOL
    k32.DeviceIoControl.argtypes = [
        C.c_void_p,
        W.DWORD,
        C.c_void_p,
        W.DWORD,
        C.c_void_p,
        W.DWORD,
        C.POINTER(W.DWORD),
        C.c_void_p,
    ]
    k32.CloseHandle.argtypes = [C.c_void_p]
    return setupapi, k32


def _battery_paths(setupapi) -> list[str]:
    guid = _GUID(
        _GUID_DEVICE_BATTERY[0],
        _GUID_DEVICE_BATTERY[1],
        _GUID_DEVICE_BATTERY[2],
        (C.c_ubyte * 8)(*_GUID_DEVICE_BATTERY[3]),
    )
    hdev = setupapi.SetupDiGetClassDevsW(
        C.byref(guid), None, None, _DIGCF_PRESENT | _DIGCF_DEVICEINTERFACE
    )
    if not hdev:
        return []
    paths: list[str] = []
    did = _SP_DEVICE_INTERFACE_DATA()
    did.cbSize = C.sizeof(did)
    index = 0
    try:
        while setupapi.SetupDiEnumDeviceInterfaces(hdev, None, C.byref(guid), index, C.byref(did)):
            need = W.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, C.byref(did), None, 0, C.byref(need), None
            )
            buf = C.create_string_buffer(need.value)
            # cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA_W is 8 on 64-bit.
            C.cast(buf, C.POINTER(W.DWORD))[0] = 8
            if setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, C.byref(did), buf, need.value, C.byref(need), None
            ):
                paths.append(C.wstring_at(C.addressof(buf) + 4))
            index += 1
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return paths


@register
class BatterySource:
    name = "win_battery"

    def __init__(self) -> None:
        self._k32 = None
        self._handle = None
        self._tag = 0
        self._prefix = "batt"
        self._static: dict[str, float] = {}
        self._relative = False

    def available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            setupapi, k32 = _bind()
            paths = _battery_paths(setupapi)
        except OSError:
            return False
        if not paths:
            return False

        # Multi-battery machines exist; this covers the first pack, and a
        # second one would be a small extension of the key prefix.
        handle = k32.CreateFileW(paths[0], 0xC0000000, 3, None, 3, 0, None)
        if not handle or handle == 0xFFFFFFFFFFFFFFFF:
            return False
        self._k32 = k32
        self._handle = handle
        if not self._refresh_tag():
            return False
        self._read_static()
        return True

    def _refresh_tag(self) -> bool:
        """The tag invalidates when a pack is swapped or re-enumerated."""
        ret = W.DWORD()
        tag = W.DWORD()
        zero = W.DWORD(0)
        ok = self._k32.DeviceIoControl(
            self._handle,
            _IOCTL_BATTERY_QUERY_TAG,
            C.byref(zero),
            4,
            C.byref(tag),
            4,
            C.byref(ret),
            None,
        )
        if not ok or tag.value == 0:
            return False
        self._tag = tag.value
        return True

    def _query(self, level: int, out_type):
        q = _BATTERY_QUERY_INFORMATION(BatteryTag=self._tag, InformationLevel=level, AtRate=0)
        out = out_type()
        ret = W.DWORD()
        ok = self._k32.DeviceIoControl(
            self._handle,
            _IOCTL_BATTERY_QUERY_INFORMATION,
            C.byref(q),
            C.sizeof(q),
            C.byref(out),
            C.sizeof(out),
            C.byref(ret),
            None,
        )
        return out if ok else None

    def _read_static(self) -> None:
        info = self._query(_BatteryInformation, _BATTERY_INFORMATION)
        if info is None:
            return
        # With BATTERY_CAPACITY_RELATIVE set, capacities and rates are opaque
        # percentages rather than mWh/mW, and reporting them as watts would be
        # a lie. Not the case on the hardware this was written against.
        self._relative = bool(info.Capabilities & _BATTERY_CAPACITY_RELATIVE)
        if not self._relative:
            if info.DesignedCapacity not in (0, _UNKNOWN_32):
                self._static[f"{self._prefix}.design"] = info.DesignedCapacity / 1000.0
            if info.FullChargedCapacity not in (0, _UNKNOWN_32):
                self._static[f"{self._prefix}.full"] = info.FullChargedCapacity / 1000.0
        if info.CycleCount not in (0, _UNKNOWN_32):
            self._static[f"{self._prefix}.cycles"] = float(info.CycleCount)
        health_full = self._static.get(f"{self._prefix}.full")
        health_design = self._static.get(f"{self._prefix}.design")
        if health_full and health_design:
            self._static[f"{self._prefix}.health"] = 100.0 * health_full / health_design

    def channels(self) -> list[Channel]:
        p = self._prefix
        full = self._static.get(f"{p}.full")
        out = [
            Channel(f"{p}.power", "Battery", "W", "battery", "battery_power", 2, signed=True),
            Channel(f"{p}.voltage", "Voltage", "V", "battery", "battery_voltage", 3),
            Channel(f"{p}.current", "Current", "A", "battery", "battery_current", 3, signed=True),
            Channel(
                f"{p}.charge", "Charge", "Wh", "battery", "battery_charge", 2, nominal_max=full
            ),
            Channel(f"{p}.level", "Level", "%", "battery", "battery_level", 1, nominal_max=100.0),
            Channel(f"{p}.temp", "Batt temp", "degC", "thermal", None, 1),
            Channel(f"{p}.ac", "AC online", "", "battery", "ac_online", 0),
            Channel(f"{p}.eta", "Time left", "s", "battery", None, 0),
        ]
        if self._relative:
            # Keep only what still means something without absolute units.
            out = [c for c in out if c.key.rsplit(".", 1)[-1] in {"level", "temp", "ac"}]
        for key, label, unit, precision in (
            (f"{p}.full", "Full charge", "Wh", 2),
            (f"{p}.design", "Design", "Wh", 2),
            (f"{p}.health", "Health", "%", 1),
            (f"{p}.cycles", "Cycles", "", 0),
        ):
            if key in self._static:
                out.append(Channel(key, label, unit, "battery", None, precision, static=True))
        return out

    def read(self) -> dict[str, float]:
        p = self._prefix
        out: dict[str, float] = dict(self._static)

        wait = _BATTERY_WAIT_STATUS(BatteryTag=self._tag)
        status = _BATTERY_STATUS()
        ret = W.DWORD()
        ok = self._k32.DeviceIoControl(
            self._handle,
            _IOCTL_BATTERY_QUERY_STATUS,
            C.byref(wait),
            C.sizeof(wait),
            C.byref(status),
            C.sizeof(status),
            C.byref(ret),
            None,
        )
        if not ok:
            # Usually a stale tag after a pack re-enumerated; one retry.
            if not self._refresh_tag():
                return out
            wait.BatteryTag = self._tag
            ok = self._k32.DeviceIoControl(
                self._handle,
                _IOCTL_BATTERY_QUERY_STATUS,
                C.byref(wait),
                C.sizeof(wait),
                C.byref(status),
                C.sizeof(status),
                C.byref(ret),
                None,
            )
            if not ok:
                return out

        out[f"{p}.ac"] = 1.0 if status.PowerState & _BATTERY_POWER_ON_LINE else 0.0

        voltage = None
        if status.Voltage != _UNKNOWN_32:
            voltage = status.Voltage / 1000.0
            out[f"{p}.voltage"] = voltage

        rate = None
        if status.Rate not in (_UNKNOWN_RATE, -0x80000000) and not self._relative:
            rate = status.Rate / 1000.0
            # Some firmware reports magnitude only and leans on the state bits.
            if rate > 0 and status.PowerState & _BATTERY_DISCHARGING:
                rate = -rate
            out[f"{p}.power"] = rate

        if rate is not None and voltage:
            out[f"{p}.current"] = rate / voltage

        if status.Capacity != _UNKNOWN_32:
            if not self._relative:
                out[f"{p}.charge"] = status.Capacity / 1000.0
            full = self._static.get(f"{p}.full")
            if full:
                out[f"{p}.level"] = 100.0 * (status.Capacity / 1000.0) / full

        temp = self._query(_BatteryTemperature, W.DWORD)
        if temp is not None and temp.value not in (0, _UNKNOWN_32):
            out[f"{p}.temp"] = temp.value / 10.0 - 273.15  # tenths of a kelvin

        eta = self._query(_BatteryEstimatedTime, W.DWORD)
        if eta is not None and eta.value != _UNKNOWN_32:
            out[f"{p}.eta"] = float(eta.value)

        return out

    def close(self) -> None:
        if self._handle and self._k32 is not None:
            self._k32.CloseHandle(self._handle)
            self._handle = None

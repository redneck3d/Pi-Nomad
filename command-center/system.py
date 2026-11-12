"""System panel: CPU, memory, temperature, power warnings, uptime and SD-card write totals.

Everything is read straight from /proc and /sys (no extra tools). Inside Docker these
files still describe the host, so the numbers are the Pi's, not the container's.
Every reading is best effort: anything a machine doesn't expose comes back as None.
"""
import glob
import os
import time

PROC = os.environ.get("PROC_DIR", "/proc")
SYS = os.environ.get("SYS_DIR", "/sys")
DATA = os.environ.get("NOMAD_DATA", "/data")

TEMP_WARM, TEMP_HOT = 70.0, 80.0     # a Pi 5 starts slowing itself down at 80 C
_prev_cpu = None


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError):
        return None


def _cpu_times():
    """(idle, total) jiffies from the first line of /proc/stat."""
    line = (_read(os.path.join(PROC, "stat")) or "").splitlines()[:1]
    if not line or not line[0].startswith("cpu "):
        return None
    try:
        n = [int(x) for x in line[0].split()[1:]]
    except ValueError:
        return None
    if len(n) < 4:
        return None
    idle = n[3] + (n[4] if len(n) > 4 else 0)      # idle + iowait
    return idle, sum(n[:8])


def cpu_percent(sample=0.25):
    """CPU use since the previous call (or over a short sample on the first call)."""
    global _prev_cpu
    prev, cur = _prev_cpu, _cpu_times()
    if cur is None:
        return None
    if prev is None or cur[1] <= prev[1]:
        time.sleep(sample)
        prev, cur = cur, _cpu_times()
        if cur is None:
            return None
    _prev_cpu = cur
    total = cur[1] - prev[1]
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * (1 - (cur[0] - prev[0]) / total))), 1)


def memory():
    kb = {}
    for line in (_read(os.path.join(PROC, "meminfo")) or "").splitlines():
        key, _, rest = line.partition(":")
        try:
            kb[key] = int(rest.split()[0]) * 1024
        except (ValueError, IndexError):
            pass
    if "MemTotal" not in kb:
        return None
    total = kb["MemTotal"]
    avail = kb.get("MemAvailable", kb.get("MemFree", 0))
    return {"total": total, "available": avail,
            "used_percent": round(100.0 * (total - avail) / total, 1) if total else 0.0,
            "swap_total": kb.get("SwapTotal", 0),
            "swap_used": max(0, kb.get("SwapTotal", 0) - kb.get("SwapFree", 0))}


def temperature():
    """Hottest thermal zone in Celsius, or None."""
    temps = []
    for p in glob.glob(os.path.join(SYS, "class/thermal/thermal_zone*/temp")):
        try:
            temps.append(int(_read(p)) / 1000.0)
        except (TypeError, ValueError):
            pass
    return round(max(temps), 1) if temps else None


def fan_rpm():
    for p in glob.glob(os.path.join(SYS, "devices/platform/cooling_fan/hwmon/hwmon*/fan1_input")):
        try:
            return int(_read(p))
        except (TypeError, ValueError):
            pass
    return None


def power_flags():
    """Raspberry Pi firmware flags: low voltage and throttling, now and since boot."""
    flags = set()
    for pat in ("devices/platform/soc*/soc*firmware/get_throttled", "devices/platform/*firmware*/get_throttled"):
        for p in glob.glob(os.path.join(SYS, pat)):
            try:
                v = int(_read(p), 16)
            except (TypeError, ValueError):
                continue
            for bit, name in ((0, "undervoltage"), (1, "freq_capped"), (2, "throttled"), (3, "temp_limit"),
                              (16, "undervoltage_past"), (17, "freq_capped_past"),
                              (18, "throttled_past"), (19, "temp_limit_past")):
                if v & (1 << bit):
                    flags.add(name)
    for h in glob.glob(os.path.join(SYS, "class/hwmon/hwmon*")):       # rpi_volt driver
        if _read(os.path.join(h, "name")) == "rpi_volt" and _read(os.path.join(h, "in0_lcrit_alarm")) == "1":
            flags.add("undervoltage")
    return sorted(flags)


def _dev_numbers(path):
    st = os.stat(path)
    return os.major(st.st_dev), os.minor(st.st_dev)


def disk_io(path=None):
    """Bytes read/written since boot on the drive that holds the data folder."""
    try:
        major, minor = _dev_numbers(path or DATA)
    except OSError:
        return None
    real = os.path.realpath(os.path.join(SYS, "dev/block", f"{major}:{minor}"))
    if not os.path.isdir(real):
        return None
    name = os.path.basename(real)
    if os.path.exists(os.path.join(real, "partition")):    # a partition: report the whole drive
        name = os.path.basename(os.path.dirname(real))
    for line in (_read(os.path.join(PROC, "diskstats")) or "").splitlines():
        f = line.split()
        if len(f) >= 10 and f[2] == name:
            try:
                return {"device": name, "read": int(f[5]) * 512, "written": int(f[9]) * 512}
            except ValueError:
                return None
    return None


def warnings(temp, flags, mem):
    out = []
    if "undervoltage" in flags:
        out.append("Power supply voltage is too low right now. Use a stronger supply or a shorter cable.")
    elif "undervoltage_past" in flags:
        out.append("Power supply voltage dropped too low at some point since startup.")
    if "throttled" in flags or "freq_capped" in flags:
        out.append("The processor is being slowed down right now (heat or low voltage).")
    if temp is not None and temp >= TEMP_HOT:
        out.append(f"Running hot ({temp:.0f} °C). The Pi slows itself down at this temperature; add cooling.")
    elif temp is not None and temp >= TEMP_WARM:
        out.append(f"Running warm ({temp:.0f} °C).")
    if mem and mem["total"] and mem["available"] / mem["total"] < 0.10:
        out.append("Memory is nearly full.")
    return out


def snapshot():
    temp, flags, mem = temperature(), power_flags(), memory()
    load = None
    try:
        load = [float(x) for x in (_read(os.path.join(PROC, "loadavg")) or "").split()[:3]]
        load = load if len(load) == 3 else None
    except ValueError:
        pass
    uptime = None
    try:
        uptime = int(float((_read(os.path.join(PROC, "uptime")) or "").split()[0]))
    except (ValueError, IndexError):
        pass
    return {"cpu": {"percent": cpu_percent(), "cores": os.cpu_count(), "load": load},
            "memory": mem, "temp_c": temp, "fan_rpm": fan_rpm(), "uptime_s": uptime,
            "time": time.time(), "disk": disk_io(), "power": flags,
            "warnings": warnings(temp, flags, mem)}

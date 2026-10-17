"""Resource sampling for the machine the agent runs on.

Standard library only — no psutil — so the NixOS client package stays dependency-light.
The parsing is split from the file reading so it can be tested against fixture text
instead of whatever this machine happens to be doing.
"""

import shutil
import time
from dataclasses import dataclass

PROC_STAT = "/proc/stat"
PROC_MEMINFO = "/proc/meminfo"
KB_PER_MB = 1024
BYTES_PER_GB = 1024**3
CPU_SAMPLE_INTERVAL_SECONDS = 0.1


@dataclass(frozen=True)
class CpuTimes:
    """Cumulative jiffies from /proc/stat — only meaningful as a difference."""

    idle: int
    total: int


@dataclass(frozen=True)
class Reading:
    cpu_percent: float
    ram_used_mb: int
    ram_total_mb: int
    disk_used_gb: float
    disk_total_gb: float

    def as_message_fields(self) -> dict:
        """Exactly the keyword arguments `telemetry_message` expects."""
        return {
            "cpu_percent": self.cpu_percent,
            "ram_used_mb": self.ram_used_mb,
            "ram_total_mb": self.ram_total_mb,
            "disk_used_gb": self.disk_used_gb,
            "disk_total_gb": self.disk_total_gb,
        }


def parse_cpu_times(proc_stat_text: str) -> CpuTimes:
    for line in proc_stat_text.splitlines():
        if line.startswith("cpu "):
            fields = [int(value) for value in line.split()[1:]]
            # Fields are: user nice system idle iowait irq softirq [steal guest...]
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
            return CpuTimes(idle=idle, total=sum(fields[:7]))
    raise ValueError(f"no aggregate 'cpu ' line found in {PROC_STAT}")


def cpu_percent_between(first: CpuTimes, second: CpuTimes) -> float:
    elapsed = second.total - first.total
    if elapsed <= 0:
        return 0.0
    busy = elapsed - (second.idle - first.idle)
    return max(0.0, min(100.0, round(busy / elapsed * 100, 1)))


def parse_memory_kb(proc_meminfo_text: str) -> tuple[int, int]:
    """Return (total_kb, used_kb). Used is derived from MemAvailable where present."""
    values: dict[str, int] = {}
    for line in proc_meminfo_text.splitlines():
        label, _, rest = line.partition(":")
        if rest.strip():
            values[label] = int(rest.split()[0])

    if "MemTotal" not in values:
        raise ValueError(f"no MemTotal found in {PROC_MEMINFO}")

    total_kb = values["MemTotal"]
    # MemAvailable accounts for reclaimable cache; MemFree alone overstates usage badly.
    available_kb = values.get("MemAvailable", values.get("MemFree", 0))
    return total_kb, max(0, total_kb - available_kb)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def sample(disk_path: str = "/") -> Reading:
    """Take one live reading of this machine's CPU, memory and disk usage."""
    first = parse_cpu_times(_read(PROC_STAT))
    time.sleep(CPU_SAMPLE_INTERVAL_SECONDS)
    cpu_percent = cpu_percent_between(first, parse_cpu_times(_read(PROC_STAT)))

    total_kb, used_kb = parse_memory_kb(_read(PROC_MEMINFO))
    usage = shutil.disk_usage(disk_path)

    return Reading(
        cpu_percent=cpu_percent,
        ram_used_mb=used_kb // KB_PER_MB,
        ram_total_mb=total_kb // KB_PER_MB,
        disk_used_gb=round(usage.used / BYTES_PER_GB, 1),
        disk_total_gb=round(usage.total / BYTES_PER_GB, 1),
    )

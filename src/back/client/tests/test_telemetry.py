import pytest

from nixync_client.telemetry import (
    CpuTimes,
    cpu_percent_between,
    parse_cpu_times,
    parse_memory_kb,
    sample,
)

PROC_STAT = """cpu  989011 525 264491 19219199 10443 73106 35423 0 0 0
cpu0 83531 40 26670 1585112 964 6668 10821 0 0 0
intr 123456
"""

# MemAvailable is what "used" should be derived from — MemFree alone counts reclaimable
# cache as used and badly overstates pressure.
PROC_MEMINFO = """MemTotal:       32699800 kB
MemFree:        15845308 kB
MemAvailable:   23545516 kB
Buffers:          771492 kB
Cached:          6378188 kB
"""


def test_parse_cpu_times_reads_the_aggregate_cpu_line():
    times = parse_cpu_times(PROC_STAT)

    assert times.idle == 19219199 + 10443, "idle counts iowait too"
    assert times.total == 989011 + 525 + 264491 + 19219199 + 10443 + 73106 + 35423


def test_parse_cpu_times_rejects_a_file_without_a_cpu_line():
    with pytest.raises(ValueError, match="cpu"):
        parse_cpu_times("intr 123\nctxt 456\n")


def test_cpu_percent_between_two_samples_measures_busy_time():
    first = CpuTimes(idle=100, total=200)
    second = CpuTimes(idle=150, total=300)  # 100 ticks passed, 50 of them idle

    assert cpu_percent_between(first, second) == 50.0


def test_cpu_percent_is_zero_when_no_time_has_passed():
    """Two identical samples must not divide by zero."""
    times = CpuTimes(idle=100, total=200)

    assert cpu_percent_between(times, times) == 0.0


def test_cpu_percent_is_clamped_to_a_sane_range():
    """Counter resets must not produce a negative or absurd percentage."""
    first = CpuTimes(idle=500, total=1000)
    second = CpuTimes(idle=0, total=100)

    assert 0.0 <= cpu_percent_between(first, second) <= 100.0


def test_parse_memory_reports_total_and_used_in_kb():
    total_kb, used_kb = parse_memory_kb(PROC_MEMINFO)

    assert total_kb == 32699800
    assert used_kb == 32699800 - 23545516, "used is total minus MemAvailable"


def test_parse_memory_falls_back_to_memfree_when_memavailable_is_absent():
    total_kb, used_kb = parse_memory_kb("MemTotal: 1000 kB\nMemFree: 400 kB\n")

    assert (total_kb, used_kb) == (1000, 600)


def test_parse_memory_rejects_a_file_without_memtotal():
    with pytest.raises(ValueError, match="MemTotal"):
        parse_memory_kb("MemFree: 400 kB\n")


def test_sample_returns_plausible_live_numbers_for_this_machine():
    """An integration check against the real /proc on this Linux box."""
    reading = sample()

    assert 0.0 <= reading.cpu_percent <= 100.0
    assert reading.ram_total_mb > 0
    assert 0 <= reading.ram_used_mb <= reading.ram_total_mb
    assert reading.disk_total_gb > 0
    assert 0 <= reading.disk_used_gb <= reading.disk_total_gb


def test_sample_output_matches_the_telemetry_message_fields():
    """The reading must drop straight into the protocol builder with no renaming."""
    from nixync_client.protocol import telemetry_message

    message = telemetry_message(**sample().as_message_fields())

    assert message["type"] == "telemetry"
    assert set(message) == {
        "type",
        "cpu_percent",
        "ram_used_mb",
        "ram_total_mb",
        "disk_used_gb",
        "disk_total_gb",
    }

"""The shared display helpers.

`ago` and `timestamp` are called with whatever a caller happens to hold. The server
sends ISO 8601 strings and sample data holds datetimes, so both have to work — a
helper that crashes on one of them takes a whole page down with it.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from nixync_ui.widgets import ago, timestamp
except ImportError as unavailable:  # pragma: no cover - environment dependent
    pytest.skip(f"PySide6 is unusable here: {unavailable}", allow_module_level=True)


def test_a_naive_datetime_is_described_relatively():
    assert ago(datetime.now() - timedelta(minutes=5)) == "5m ago"


def test_an_aware_datetime_is_described_relatively():
    assert ago(datetime.now(timezone.utc) - timedelta(hours=2)) == "2h ago"


def test_an_iso_string_from_the_server_is_accepted():
    """This crashed the device app's machine page: the server sends a string."""
    when = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    assert ago(when) == "5m ago"


def test_an_iso_string_works_for_timestamps_too():
    when = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    assert "ago" in timestamp(when)


def test_something_very_recent_reads_as_recently():
    assert ago(datetime.now(timezone.utc).isoformat()) == "recently"


def test_an_unparseable_string_says_so_rather_than_crashing():
    """A page must not die because one timestamp was malformed."""
    assert ago("not a date") == "unknown"
    assert timestamp("not a date") == "unknown"


def test_none_is_handled_rather_than_raising():
    assert ago(None) == "unknown"

#!/usr/bin/python3
"""Desk presence helper: POST /api/presence when the Mac was used recently.

Run every 60 s by a LaunchAgent. Posts nothing when idle, locked-and-idle or
when the idle time is unknown. Always exits 0.
"""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import homehub_client  # noqa: E402

IOREG = "/usr/sbin/ioreg"
ACTIVE_BELOW = 120.0
_IDLE_RE = re.compile(r'"HIDIdleTime"\s*=\s*(\d+)')


def idle_seconds():
    """Seconds since last HID input, or None if unknown."""
    try:
        r = subprocess.run(
            [IOREG, "-c", "IOHIDSystem", "-d", "4", "-k", "HIDIdleTime", "-r"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            universal_newlines=True, timeout=2,
        )
        if r.returncode != 0:
            return None
        m = _IDLE_RE.search(r.stdout or "")
        if not m:
            return None
        return int(m.group(1)) / 1e9
    except Exception:
        return None


def main():
    try:
        idle = idle_seconds()
        if idle is None or idle >= ACTIVE_BELOW:
            return 0
        at = datetime.now().astimezone() - timedelta(seconds=idle)
        homehub_client.post_json(
            "/api/presence",
            {"active": True, "at": at.isoformat(timespec="seconds")},
            timeout=3.0,
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    main()
    sys.exit(0)

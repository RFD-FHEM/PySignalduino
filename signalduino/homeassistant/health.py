"""Connectivity receipt; quiet RF traffic is not an unhealthy gateway."""

import time
from pathlib import Path

HEALTH_FILE = Path("/tmp/signalduino-health")


def healthy():
    try:
        age = time.monotonic() - float(HEALTH_FILE.read_text())
        return 0 <= age < 45
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if healthy() else 1)

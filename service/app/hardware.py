"""Host hardware detection.

Small, dependency-free probes the setup wizard uses to tailor itself to the
device it is running on. The big one is "are we on a Raspberry Pi", which
decides whether to offer the Pi deployment modes (Pi Hosted, Pi Remote) and
hide the generic "Server hosted" mode.

All probes are read-only and degrade to a safe default (False) when the source
they read is missing, so they are safe to call on any platform, including in
tests and CI where none of these files exist.
"""
from __future__ import annotations

import os
from functools import lru_cache

# Files the kernel/firmware expose with the board model string. On Raspberry Pi
# OS both contain "Raspberry Pi ..."; /proc/cpuinfo carries a "Model" line on
# older images. We read whichever is present.
_MODEL_FILES = (
    "/proc/device-tree/model",
    "/sys/firmware/devicetree/base/model",
)


def _read_model() -> str:
    """Return the board model string, or '' if none is exposed.

    The device-tree node is NUL-terminated, so strip trailing NULs/whitespace.
    """
    # Test/override hook: FOODASSISTANT_FORCE_MODEL lets tests and the demo
    # setup pretend to be (or not be) a Pi without touching the filesystem.
    forced = os.environ.get("FOODASSISTANT_FORCE_MODEL")
    if forced is not None:
        return forced
    for path in _MODEL_FILES:
        try:
            with open(path, "rb") as fh:
                return fh.read().decode("utf-8", "replace").strip("\x00").strip()
        except OSError:
            continue
    return ""


@lru_cache(maxsize=1)
def is_raspberry_pi() -> bool:
    """True when the host is a Raspberry Pi.

    Cached: the answer cannot change for the life of the process. Tests that
    exercise both branches clear the cache via ``is_raspberry_pi.cache_clear()``.
    """
    return "raspberry pi" in _read_model().lower()


@lru_cache(maxsize=1)
def board_model() -> str:
    """Human-readable board model (e.g. 'Raspberry Pi 5 Model B'), or ''."""
    return _read_model()

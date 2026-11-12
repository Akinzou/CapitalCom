"""One ``DeprecationWarning`` per legacy name and process."""

import os
import sys
import threading
import warnings
from pathlib import Path

MIGRATION_URL = "https://akinzou.github.io/CapitalCom/guides/migration/"

# Module-level rather than per client: a bot that builds a client per trade must not get a
# warning per trade, and code that skips __init__ still has the registry.
_warned: set[str] = set()
_lock = threading.Lock()
_PACKAGE_DIR = os.path.normcase(str(Path(__file__).resolve().parent.parent))


def warn_once(name: str, extra: str = "") -> None:
    """Warn that ``name`` is deprecated, the first time it is used in this process."""
    with _lock:
        if name in _warned:
            return
        _warned.add(name)
    message = f"{name} is deprecated and will be removed no earlier than 3.0; see {MIGRATION_URL}"
    if extra:
        message = f"{message}. {extra}"
    warnings.warn(message, DeprecationWarning, stacklevel=_first_frame_outside_package())


def _first_frame_outside_package() -> int:
    """``stacklevel`` of the first frame outside ``capitalcom``.

    A fixed level would point into the library whenever a legacy method is reached through
    another one (open_forex_position calls open_raw_position), and Python's default filters
    hide a DeprecationWarning attributed to library code: the user would never see it.
    """
    level = 2  # 1 is warn_once itself, 2 the legacy method that called it
    frame = sys._getframe(2)  # 0 is this function, 1 warn_once, 2 the legacy method
    while frame is not None and os.path.normcase(frame.f_code.co_filename).startswith(_PACKAGE_DIR):
        frame = frame.f_back  # type: ignore[assignment]
        level += 1
    return level

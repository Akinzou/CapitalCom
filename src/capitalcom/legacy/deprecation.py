"""One ``DeprecationWarning`` per legacy name and process."""

import threading
import warnings

MIGRATION_URL = "https://github.com/Akinzou/CapitalCom/blob/master/docs/migration.md"

# Module-level rather than per client: a bot that builds a client per trade must not get a
# warning per trade, and code that skips __init__ still has the registry.
_warned: set[str] = set()
_lock = threading.Lock()


def warn_once(name: str, extra: str = "") -> None:
    """Warn that ``name`` is deprecated, the first time it is used in this process."""
    with _lock:
        if name in _warned:
            return
        _warned.add(name)
    message = f"{name} is deprecated and will be removed in 3.0; see {MIGRATION_URL}"
    if extra:
        message = f"{message}. {extra}"
    # stacklevel 3 points past warn_once and the legacy method at the caller's own line.
    warnings.warn(message, DeprecationWarning, stacklevel=3)

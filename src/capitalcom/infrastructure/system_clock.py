"""The real clock behind the ``Clock`` port."""

import time
from datetime import UTC, datetime


class SystemClock:
    """Monotonic time for intervals, UTC wall time for timestamps, real sleeping."""

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin; never goes backwards."""
        return time.monotonic()

    def now_utc(self) -> datetime:
        """Current time as an aware UTC datetime."""
        # From time.time() rather than datetime.now(): code written for 1.x patches
        # "capitalcom.client.time.time", and the legacy token_expiry must follow that patch.
        return datetime.fromtimestamp(time.time(), UTC)

    def sleep(self, seconds: float) -> None:
        """Block the calling thread."""
        time.sleep(seconds)

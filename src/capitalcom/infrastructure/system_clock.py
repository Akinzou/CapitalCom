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
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        """Block the calling thread."""
        time.sleep(seconds)

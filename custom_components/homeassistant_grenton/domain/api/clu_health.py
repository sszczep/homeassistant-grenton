"""Local CLU communication health; observing traffic never creates more traffic."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic

KEEPALIVE_INTERVAL = 10
REGISTRATION_INTERVAL = 45
CONNECTION_STALE_AFTER = 30
REALTIME_STALE_AFTER = 2 * REGISTRATION_INTERVAL


@dataclass
class CluConnectionHealth:
    """Keep wall time for diagnostics and monotonic time for availability."""

    started_at: float = field(default_factory=lambda: monotonic())
    last_seen: datetime | None = None
    last_seen_at: float | None = None
    request_timeouts: int = 0

    def record_response(self) -> None:
        self.last_seen = datetime.now(UTC)
        self.last_seen_at = monotonic()

    def describe_last_response(self) -> str:
        """Describe passive receive history without probing the controller."""
        if self.last_seen is None or self.last_seen_at is None:
            return "never"
        age = max(0.0, monotonic() - self.last_seen_at)
        return f"{self.last_seen.isoformat(timespec='seconds')} ({age:.1f}s ago)"

    @property
    def connected(self) -> bool | None:
        if self.last_seen_at is None:
            return (
                False
                if monotonic() - self.started_at >= CONNECTION_STALE_AFTER
                else None
            )
        return monotonic() - self.last_seen_at < CONNECTION_STALE_AFTER

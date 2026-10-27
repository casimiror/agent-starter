import threading
import time
from collections import OrderedDict
from collections.abc import Callable


class RecentIds:
    """Remembers ids for `ttl` seconds, to drop a provider's retries of a webhook.

    In memory, per process: with several workers or instances a retry that lands elsewhere is
    processed again (docs/channels.md). The cost is a duplicated reply, not a lost one."""

    def __init__(
        self, ttl: float = 600, max_size: int = 10_000, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._clock = clock
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._guard = threading.Lock()

    def seen_before(self, key: str) -> bool:
        """True when `key` was seen within the TTL; otherwise remembers it and returns False."""
        now = self._clock()
        with self._guard:
            while self._seen:  # oldest first: insertion order is time order
                oldest, expires = next(iter(self._seen.items()))
                if expires > now and len(self._seen) < self._max_size:
                    break
                del self._seen[oldest]
            if key in self._seen:
                return True
            self._seen[key] = now + self._ttl
            return False

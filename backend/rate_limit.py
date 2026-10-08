from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from threading import Lock

_buckets: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()

def check_rate_limit(key: str, limit: int, window_seconds: int) -> int | None:
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        q = _buckets[key]
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= limit:
            return max(1, math.ceil(window_seconds - (now - q[0])))
        q.append(now)
        if len(_buckets) > 5000:
            stale = [k for k, v in _buckets.items() if not v or v[-1] <= cutoff]
            for k in stale[:1000]:
                _buckets.pop(k, None)
    return None

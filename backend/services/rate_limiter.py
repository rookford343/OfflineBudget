import time
from collections import defaultdict

# key -> list of attempt timestamps within the current window.
# In-memory and per-process, matching this app's single-process local
# deployment (no Redis/shared-state dependency).
_attempts: dict[str, list[float]] = defaultdict(list)


def allow(key: str, limit: int, window_seconds: int) -> bool:
    now = time.time()
    cutoff = now - window_seconds
    recent = [t for t in _attempts[key] if t > cutoff]
    if len(recent) >= limit:
        _attempts[key] = recent
        return False
    recent.append(now)
    _attempts[key] = recent
    return True


def _reset_for_tests() -> None:
    _attempts.clear()

"""Tiny abuse protection"""
import threading
import time

from . import config

_lock = threading.Lock()
_active = 0
_per_ip: dict[str, list[float]] = {}


def try_acquire(ip: str) -> tuple[bool, str]:
    global _active
    now = time.time()
    with _lock:
        hist = [t for t in _per_ip.get(ip, []) if now - t < 86400]
        if len(hist) >= config.MAX_CALLS_PER_IP_PER_DAY:
            _per_ip[ip] = hist
            return False, "You've reached today's demo-call limit. Please try again tomorrow."
        if _active >= config.MAX_CONCURRENT_CALLS:
            return False, "The demo line is busy right now. Please try again in a minute."
        hist.append(now)
        _per_ip[ip] = hist
        _active += 1
        return True, ""


def release() -> None:
    global _active
    with _lock:
        _active = max(0, _active - 1)

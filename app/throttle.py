import threading
import time

from app.errors import AppError


class LoginThrottle:
    def __init__(self, limit: int = 10, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            recent = [stamp for stamp in self._hits.get(key, []) if now - stamp < self.window_seconds]
            if len(recent) >= self.limit:
                self._hits[key] = recent
                raise AppError(429, "Too many login attempts. Try again in a minute.")
            recent.append(now)
            self._hits[key] = recent

import json
import threading
import time
from collections.abc import Callable
from datetime import date


class SlotCache:
    def get_or_load(self, doctor_id: int, day: date, loader: Callable[[], list[dict]]):
        raise NotImplementedError

    def evict(self, doctor_id: int, day: date) -> None:
        raise NotImplementedError

    def stats(self) -> dict:
        raise NotImplementedError


class InMemorySlotCache(SlotCache):
    """Process-local cache used in development and tests. Production swaps in Redis."""

    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._values: dict[tuple[int, date], tuple[float, list[dict]]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get_or_load(self, doctor_id: int, day: date, loader: Callable[[], list[dict]]):
        key = (doctor_id, day)
        now = time.monotonic()
        with self._lock:
            found = self._values.get(key)
            if found and found[0] > now:
                self.hits += 1
                return found[1]
            self.misses += 1
        loaded = loader()
        with self._lock:
            self._values[key] = (time.monotonic() + self.ttl_seconds, loaded)
        return loaded

    def evict(self, doctor_id: int, day: date) -> None:
        with self._lock:
            self._values.pop((doctor_id, day), None)

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "backend": "memory"}


class RedisSlotCache(SlotCache):
    def __init__(self, client, ttl_seconds: int):
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.hits = 0
        self.misses = 0

    def _key(self, doctor_id: int, day: date) -> str:
        return f"open-slots:{doctor_id}:{day.isoformat()}"

    def get_or_load(self, doctor_id: int, day: date, loader: Callable[[], list[dict]]):
        key = self._key(doctor_id, day)
        raw = self.client.get(key)
        if raw:
            self.hits += 1
            return json.loads(raw)
        self.misses += 1
        loaded = loader()
        self.client.setex(key, self.ttl_seconds, json.dumps(loaded, default=str))
        return loaded

    def evict(self, doctor_id: int, day: date) -> None:
        self.client.delete(self._key(doctor_id, day))

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "backend": "redis"}


def build_cache(settings) -> SlotCache:
    if not settings.redis_enabled:
        return InMemorySlotCache(settings.cache_ttl_seconds)
    import redis

    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return RedisSlotCache(client, settings.cache_ttl_seconds)

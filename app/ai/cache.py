import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from time import monotonic

from app.ai.models import AIQueryResponse


GenerateSummary = Callable[[datetime, datetime], Awaitable[AIQueryResponse]]
CacheKey = tuple[int, int, int]


@dataclass(frozen=True)
class _CacheEntry:
    response: AIQueryResponse
    expires_at: float


class AIExecutiveSummaryCache:
    """Short process-local cache that coalesces Executive AI summary generation."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        max_entries: int = 8,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._clock = clock
        self._max_entries = max_entries
        self._entries: dict[CacheKey, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get_or_generate(
        self,
        *,
        start: datetime,
        end: datetime,
        ttl_seconds: int,
        generate: GenerateSummary,
    ) -> AIQueryResponse:
        key = _cache_key(start, end, ttl_seconds)
        now = self._clock()
        entry = self._entries.get(key)
        if entry is not None and now < entry.expires_at:
            return entry.response

        async with self._lock:
            now = self._clock()
            self._prune_expired(now)
            entry = self._entries.get(key)
            if entry is not None and now < entry.expires_at:
                return entry.response

            response = await generate(start, end)
            self._entries[key] = _CacheEntry(
                response=response,
                expires_at=self._clock() + ttl_seconds,
            )
            self._trim_oldest()
            return response

    def _prune_expired(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if now >= entry.expires_at]
        for key in expired:
            self._entries.pop(key, None)

    def _trim_oldest(self) -> None:
        while len(self._entries) > self._max_entries:
            oldest_key = next(iter(self._entries))
            self._entries.pop(oldest_key, None)


def _cache_key(start: datetime, end: datetime, ttl_seconds: int) -> CacheKey:
    return (
        ttl_seconds,
        int(start.timestamp()) // ttl_seconds,
        int(end.timestamp()) // ttl_seconds,
    )

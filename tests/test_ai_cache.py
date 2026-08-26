import asyncio
from datetime import datetime, timedelta, timezone

from app.ai.cache import AIExecutiveSummaryCache
from app.ai.models import AIAnalysis, AIQueryResponse


BASE = datetime(2026, 8, 20, 0, 0, 10, tzinfo=timezone.utc)


def make_response(start: datetime, end: datetime) -> AIQueryResponse:
    return AIQueryResponse(
        observed_at=end,
        range_start=start,
        range_end=end,
        analysis=AIAnalysis(summary="Cached summary.", confidence="high"),
        source_warnings=[],
    )


def test_summary_cache_reuses_shifted_ranges_in_same_bucket() -> None:
    async def run() -> None:
        now = [100.0]
        cache = AIExecutiveSummaryCache(clock=lambda: now[0])
        calls = []

        async def generate(start: datetime, end: datetime) -> AIQueryResponse:
            calls.append((start, end))
            return make_response(start, end)

        first = await cache.get_or_generate(
            start=BASE - timedelta(hours=24),
            end=BASE,
            ttl_seconds=300,
            generate=generate,
        )
        second = await cache.get_or_generate(
            start=BASE - timedelta(hours=24) + timedelta(seconds=30),
            end=BASE + timedelta(seconds=30),
            ttl_seconds=300,
            generate=generate,
        )

        assert second is first
        assert len(calls) == 1

    asyncio.run(run())


def test_summary_cache_expires_and_does_not_cache_failures() -> None:
    async def run() -> None:
        now = [100.0]
        cache = AIExecutiveSummaryCache(clock=lambda: now[0])
        calls = 0

        async def generate(start: datetime, end: datetime) -> AIQueryResponse:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("synthetic failure")
            return make_response(start, end)

        try:
            await cache.get_or_generate(
                start=BASE - timedelta(hours=24),
                end=BASE,
                ttl_seconds=300,
                generate=generate,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("synthetic failure should propagate")

        cached = await cache.get_or_generate(
            start=BASE - timedelta(hours=24),
            end=BASE,
            ttl_seconds=300,
            generate=generate,
        )
        assert calls == 2

        now[0] += 301
        refreshed = await cache.get_or_generate(
            start=BASE - timedelta(hours=24),
            end=BASE,
            ttl_seconds=300,
            generate=generate,
        )

        assert calls == 3
        assert refreshed is not cached

    asyncio.run(run())


def test_summary_cache_coalesces_concurrent_misses() -> None:
    async def run() -> None:
        cache = AIExecutiveSummaryCache(clock=lambda: 100.0)
        calls = 0

        async def generate(start: datetime, end: datetime) -> AIQueryResponse:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return make_response(start, end)

        results = await asyncio.gather(
            cache.get_or_generate(
                start=BASE - timedelta(hours=24),
                end=BASE,
                ttl_seconds=300,
                generate=generate,
            ),
            cache.get_or_generate(
                start=BASE - timedelta(hours=24),
                end=BASE,
                ttl_seconds=300,
                generate=generate,
            ),
        )

        assert calls == 1
        assert results[0] is results[1]

    asyncio.run(run())

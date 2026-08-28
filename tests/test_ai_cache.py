import asyncio
from datetime import datetime, timedelta, timezone

from app.ai.cache import AIExecutiveSummaryCache
from app.ai.models import AIAnalysis, AIDashboardSummaryResponse, AIQueryResponse


BASE = datetime(2026, 8, 20, 0, 0, 10, tzinfo=timezone.utc)


def make_response(start: datetime, end: datetime) -> AIQueryResponse:
    return AIQueryResponse(
        observed_at=end,
        range_start=start,
        range_end=end,
        analysis=AIAnalysis(summary="Cached summary.", confidence="high"),
        source_warnings=[],
    )


def test_summary_cache_keeps_shifted_ranges_exact() -> None:
    async def run() -> None:
        now = [100.0]
        cache = AIExecutiveSummaryCache[AIQueryResponse](clock=lambda: now[0])
        calls = []
        first_start = BASE - timedelta(hours=24)
        second_start = first_start + timedelta(seconds=30)
        second_end = BASE + timedelta(seconds=30)

        async def generate(start: datetime, end: datetime) -> AIQueryResponse:
            calls.append((start, end))
            return make_response(start, end)

        first = await cache.get_or_generate(
            start=first_start,
            end=BASE,
            ttl_seconds=300,
            generate=generate,
        )
        second = await cache.get_or_generate(
            start=second_start,
            end=second_end,
            ttl_seconds=300,
            generate=generate,
        )

        assert first.range_start == first_start
        assert first.range_end == BASE
        assert second.range_start == second_start
        assert second.range_end == second_end
        assert calls == [(first_start, BASE), (second_start, second_end)]

    asyncio.run(run())


def test_summary_cache_supports_dashboard_summary_response_type() -> None:
    async def run() -> None:
        cache = AIExecutiveSummaryCache[AIDashboardSummaryResponse](clock=lambda: 100.0)
        analysis = AIAnalysis(summary="Dashboard summary.", confidence="medium")

        async def generate(start: datetime, end: datetime) -> AIDashboardSummaryResponse:
            return AIDashboardSummaryResponse(
                observed_at=end,
                range_start=start,
                range_end=end,
                executive=analysis,
                wazuh=analysis,
                zabbix=analysis,
                snipe_it=analysis,
                freshservice=analysis,
            )

        response = await cache.get_or_generate(
            start=BASE - timedelta(hours=24),
            end=BASE,
            ttl_seconds=300,
            generate=generate,
        )

        assert response.executive.summary == "Dashboard summary."
        assert response.range_start == BASE - timedelta(hours=24)
        assert response.range_end == BASE

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

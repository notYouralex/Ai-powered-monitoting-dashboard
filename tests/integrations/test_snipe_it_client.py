import asyncio
from datetime import date

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import IntegrationError
from app.integrations.snipe_it.client import SnipeItClient


def make_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "app_secret_key": "t" * 48,
        "database_url": "sqlite:///test.db",
        "snipe_it_base_url": "http://snipe.internal",
        "snipe_it_api_token": "fake-snipe-token",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def asset_payload(asset_id: int = 101, **overrides) -> dict:
    payload = {
        "id": asset_id,
        "name": "Engineering Laptop",
        "asset_tag": f"LT-{asset_id}",
        "serial": f"SERIAL-{asset_id}",
        "model": {"id": 11, "name": "Latitude 7450"},
        "category": {"id": 12, "name": "Laptop"},
        "manufacturer": {"id": 13, "name": "Dell"},
        "status_label": {"id": 14, "name": "Ready to Deploy", "status_meta": "deployable"},
        "assigned_to": {"id": 15, "name": "Example User", "type": "user"},
        "location": {"id": 16, "name": "Main Office"},
        "purchase_date": {"date": "2026-01-15", "formatted": "Jan 15, 2026"},
        "warranty_months": 36,
        "warranty_expires": {"date": "2029-01-15", "formatted": "Jan 15, 2029"},
    }
    payload.update(overrides)
    return payload


def test_from_settings_rejects_unconfigured_snipe_it() -> None:
    settings = make_settings(snipe_it_base_url=None, snipe_it_api_token=None)

    with pytest.raises(IntegrationError) as exc_info:
        SnipeItClient.from_settings(settings)

    assert exc_info.value.source == "snipe_it"
    assert exc_info.value.code == "SOURCE_NOT_CONFIGURED"
    assert exc_info.value.retryable is False


def test_list_assets_uses_bearer_auth_and_normalizes_reporting_fields() -> None:
    async def run() -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"total": 1, "rows": [asset_payload()]})

        client = SnipeItClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        assets = await client.list_assets()

        assert len(requests) == 1
        request = requests[0]
        assert request.method == "GET"
        assert request.url.path == "/api/v1/hardware"
        assert request.headers["Authorization"] == "Bearer fake-snipe-token"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["User-Agent"].startswith("ai-powered-monitoring-dashboard/")
        assert request.url.params["limit"] == "100"
        assert request.url.params["offset"] == "0"
        assert request.url.params["sort"] == "id"
        assert request.url.params["order"] == "asc"

        assert len(assets) == 1
        asset = assets[0]
        assert asset.asset_id == 101
        assert asset.asset_tag == "LT-101"
        assert asset.serial == "SERIAL-101"
        assert asset.model_id == 11
        assert asset.model == "Latitude 7450"
        assert asset.category_id == 12
        assert asset.category == "Laptop"
        assert asset.manufacturer_id == 13
        assert asset.manufacturer == "Dell"
        assert asset.status_label_id == 14
        assert asset.status_label == "Ready to Deploy"
        assert asset.status_type == "deployable"
        assert asset.assigned_to_id == 15
        assert asset.assigned_type == "user"
        assert asset.location_id == 16
        assert asset.location == "Main Office"
        assert asset.purchase_date == date(2026, 1, 15)
        assert asset.warranty_months == 36
        assert asset.warranty_expires == date(2029, 1, 15)

    asyncio.run(run())


def test_list_assets_pages_with_bounded_limit_and_offset() -> None:
    async def run() -> None:
        offsets: list[int] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            offset = int(request.url.params["offset"])
            offsets.append(offset)
            if offset == 0:
                return httpx.Response(200, json={"total": 2, "rows": [asset_payload(101)]})
            return httpx.Response(200, json={"total": 2, "rows": [asset_payload(102)]})

        client = SnipeItClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        assets = await client.list_assets()

        assert offsets == [0, 1]
        assert [asset.asset_id for asset in assets] == [101, 102]

    asyncio.run(run())


def test_list_assets_rejects_duplicate_asset_ids_across_pages() -> None:
    async def run() -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"total": 2, "rows": [asset_payload(101)]})

        client = SnipeItClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_assets()

        assert calls == 2
        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"
        assert exc_info.value.retryable is False

    asyncio.run(run())


def test_auth_failure_does_not_leak_snipe_it_token() -> None:
    async def run() -> None:
        token = "fake-token-that-must-not-leak"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": token})

        client = SnipeItClient.from_settings(
            make_settings(snipe_it_api_token=token),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_assets()

        assert exc_info.value.code == "SOURCE_AUTH_FAILED"
        assert exc_info.value.retryable is False
        assert token not in str(exc_info.value)
        assert token not in repr(exc_info.value)

    asyncio.run(run())


def test_malformed_hardware_response_maps_to_safe_bad_response() -> None:
    async def run() -> None:
        marker = "raw-snipe-marker-must-not-leak"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"total": 1, "rows": marker})

        client = SnipeItClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_assets()

        assert exc_info.value.code == "SOURCE_BAD_RESPONSE"
        assert marker not in str(exc_info.value)
        assert marker not in repr(exc_info.value)

    asyncio.run(run())


def test_empty_hardware_inventory_returns_empty_list() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"total": 0, "rows": []})

        client = SnipeItClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        assert await client.list_assets() == []

    asyncio.run(run())


def test_read_timeout_maps_to_source_unavailable_without_leaking_details() -> None:
    async def run() -> None:
        marker = "snipe-timeout-marker"

        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout(marker, request=request)

        client = SnipeItClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_assets()

        assert exc_info.value.code == "SOURCE_UNAVAILABLE"
        assert exc_info.value.retryable is True
        assert marker not in str(exc_info.value)
        assert marker not in repr(exc_info.value)

    asyncio.run(run())


def test_rate_limit_is_retried_bounded_then_maps_to_rate_limited(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(429, json={"message": "limited"})

        monkeypatch.setattr("app.core.http.asyncio.sleep", fake_sleep)
        client = SnipeItClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_assets()

        assert attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == "SOURCE_RATE_LIMITED"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_transient_server_failure_is_retried_bounded_then_unavailable(monkeypatch) -> None:
    async def run() -> None:
        attempts = 0
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(503, json={"message": "unavailable"})

        monkeypatch.setattr("app.core.http.asyncio.sleep", fake_sleep)
        client = SnipeItClient.from_settings(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(IntegrationError) as exc_info:
            await client.list_assets()

        assert attempts == 3
        assert delays == [0.25, 0.5]
        assert exc_info.value.code == "SOURCE_UNAVAILABLE"
        assert exc_info.value.retryable is True

    asyncio.run(run())


def test_client_public_surface_remains_read_only() -> None:
    assert hasattr(SnipeItClient, "list_assets")
    for method in ("create", "update", "delete", "checkout", "checkin"):
        assert not hasattr(SnipeItClient, method)

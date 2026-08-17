from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.errors import IntegrationError, IntegrationErrorCode
from app.core.http import create_http_client, request_with_retries
from app.integrations.snipe_it.models import SnipeItAsset


SNIPE_IT_ASSET_PAGE_SIZE = 100
SNIPE_IT_MAX_ASSET_PAGES = 100
SNIPE_IT_MAX_ASSETS = SNIPE_IT_ASSET_PAGE_SIZE * SNIPE_IT_MAX_ASSET_PAGES


class SnipeItClient:
    """Read-only Snipe-IT API client for bounded hardware inventory retrieval."""

    def __init__(
        self,
        *,
        base_url: str,
        api_token: SecretStr,
        verify_tls: bool,
        ca_bundle: Path | None,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token
        self._verify_tls = verify_tls
        self._ca_bundle = ca_bundle
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> "SnipeItClient":
        base_url = settings.snipe_it_base_url
        api_token = settings.snipe_it_api_token
        if (
            settings.integration_config_state("snipe_it") != "configured"
            or base_url is None
            or api_token is None
        ):
            raise IntegrationError(
                source="snipe_it",
                code="SOURCE_NOT_CONFIGURED",
                retryable=False,
            )

        return cls(
            base_url=str(base_url),
            api_token=api_token,
            verify_tls=settings.snipe_it_verify_tls,
            ca_bundle=settings.snipe_it_ca_bundle,
            timeout_seconds=settings.snipe_it_timeout_seconds,
            transport=transport,
        )

    async def list_assets(self) -> list[SnipeItAsset]:
        assets: list[SnipeItAsset] = []
        seen_ids: set[int] = set()
        offset = 0

        async with create_http_client(
            timeout_seconds=self._timeout_seconds,
            verify_tls=self._verify_tls,
            ca_bundle=self._ca_bundle,
            transport=self._transport,
        ) as client:
            for _ in range(SNIPE_IT_MAX_ASSET_PAGES):
                response = await self._get_asset_page(client, offset=offset)
                payload = self._parse_json_object(response)
                try:
                    total = _required_nonnegative_int(payload.get("total"))
                except (TypeError, ValueError) as exc:
                    raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc
                rows = payload.get("rows")
                if (
                    not isinstance(rows, list)
                    or len(rows) > SNIPE_IT_ASSET_PAGE_SIZE
                    or total > SNIPE_IT_MAX_ASSETS
                ):
                    raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

                try:
                    normalized = [self._normalize_asset(row) for row in rows]
                except (TypeError, ValueError, ValidationError) as exc:
                    raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc

                for asset in normalized:
                    if asset.asset_id in seen_ids:
                        raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
                    seen_ids.add(asset.asset_id)
                    assets.append(asset)

                if len(assets) > total:
                    raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
                if len(assets) == total:
                    return assets
                if not rows:
                    raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)
                offset += len(rows)

        raise self._source_error("SOURCE_BAD_RESPONSE", retryable=False)

    async def _get_asset_page(
        self,
        client: httpx.AsyncClient,
        *,
        offset: int,
    ) -> httpx.Response:
        try:
            response = await request_with_retries(
                client,
                "GET",
                f"{self._base_url}/api/v1/hardware",
                retry_safe=True,
                headers={
                    "Authorization": f"Bearer {self._api_token.get_secret_value()}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                params={
                    "limit": SNIPE_IT_ASSET_PAGE_SIZE,
                    "offset": offset,
                    "sort": "id",
                    "order": "asc",
                },
            )
        except httpx.RequestError as exc:
            raise self._source_error("SOURCE_UNAVAILABLE", retryable=True) from exc

        self._raise_for_status(response)
        return response

    @staticmethod
    def _normalize_asset(value: Any) -> SnipeItAsset:
        if not isinstance(value, dict):
            raise TypeError("Snipe-IT asset must be an object")

        model_id, model = _optional_relation(value.get("model"))
        category_id, category = _optional_relation(value.get("category"))
        manufacturer_id, manufacturer = _optional_relation(value.get("manufacturer"))
        status_label_id, status_label = _optional_relation(value.get("status_label"))
        assigned_to_id, _assigned_to_name = _optional_relation(value.get("assigned_to"))
        location_id, location = _optional_relation(value.get("location"))

        status_value = value.get("status_label")
        status_type = None
        if isinstance(status_value, dict):
            status_type = _optional_string(
                status_value.get("status_meta", status_value.get("type"))
            )

        assigned_value = value.get("assigned_to")
        assigned_type = None
        if isinstance(assigned_value, dict):
            assigned_type = _optional_string(assigned_value.get("type"))

        return SnipeItAsset(
            asset_id=_required_positive_int(value.get("id")),
            asset_tag=_optional_string(value.get("asset_tag")),
            name=_optional_string(value.get("name")),
            serial=_optional_string(value.get("serial")),
            model_id=model_id,
            model=model,
            category_id=category_id,
            category=category,
            manufacturer_id=manufacturer_id,
            manufacturer=manufacturer,
            status_label_id=status_label_id,
            status_label=status_label,
            status_type=status_type,
            assigned_to_id=assigned_to_id,
            assigned_type=assigned_type,
            location_id=location_id,
            location=location,
            purchase_date=_optional_date(value.get("purchase_date")),
            warranty_months=_optional_warranty_months(value.get("warranty_months")),
            warranty_expires=_optional_date(value.get("warranty_expires")),
        )

    @staticmethod
    def _parse_json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise SnipeItClient._source_error("SOURCE_BAD_RESPONSE", retryable=False) from exc
        if not isinstance(payload, dict):
            raise SnipeItClient._source_error("SOURCE_BAD_RESPONSE", retryable=False)
        return payload

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        if status in {401, 403}:
            raise SnipeItClient._source_error("SOURCE_AUTH_FAILED", retryable=False)
        if status == 429:
            raise SnipeItClient._source_error("SOURCE_RATE_LIMITED", retryable=True)
        if status >= 500:
            raise SnipeItClient._source_error("SOURCE_UNAVAILABLE", retryable=True)
        raise SnipeItClient._source_error("SOURCE_BAD_RESPONSE", retryable=False)

    @staticmethod
    def _source_error(code: IntegrationErrorCode, *, retryable: bool) -> IntegrationError:
        return IntegrationError(
            source="snipe_it",
            code=code,
            retryable=retryable,
        )


def _required_nonnegative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("required Snipe-IT integer is invalid")
    return value


def _required_positive_int(value: Any) -> int:
    parsed = _optional_positive_int(value)
    if parsed is None:
        raise ValueError("required Snipe-IT integer is invalid")
    return parsed


def _optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Snipe-IT integer is invalid")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ValueError("Snipe-IT integer is invalid")
    if parsed <= 0:
        raise ValueError("Snipe-IT integer is invalid")
    return parsed


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Snipe-IT integer is invalid")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ValueError("Snipe-IT integer is invalid")
    if parsed < 0:
        raise ValueError("Snipe-IT integer is invalid")
    return parsed


def _optional_warranty_months(value: Any) -> int | None:
    if isinstance(value, str):
        parts = value.strip().split()
        if len(parts) == 2 and parts[1].casefold() == "months":
            value = parts[0]
    return _optional_nonnegative_int(value)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Snipe-IT string is invalid")
    text = value.strip()
    return text or None


def _optional_relation(value: Any) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict):
        raise ValueError("Snipe-IT relation is invalid")
    return _optional_positive_int(value.get("id")), _optional_string(value.get("name"))


def _optional_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    raw = value
    if isinstance(value, dict):
        raw = value.get("date", value.get("datetime"))
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise ValueError("Snipe-IT date is invalid")
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError as exc:
        raise ValueError("Snipe-IT date is invalid") from exc

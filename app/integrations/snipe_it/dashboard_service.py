from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from fastapi import Depends
from sqlalchemy import MetaData, Table, select
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.orm import Session

from app.contracts import ExecutiveSourceSummary, IntegrationHealthSummary, IntegrationStatus
from app.core.config import Settings, get_settings
from app.db.models import SyncRun
from app.db.session import get_db
from app.integrations.snipe_it.dashboard_models import (
    SnipeItDashboardResponse,
    SnipeItDashboardSummary,
    SnipeItNamedCount,
    SnipeItWarrantyExpiryItem,
    SnipeItWarrantyExpiryResponse,
)


SNIPE_IT_DASHBOARD_TIMEZONE = ZoneInfo("Asia/Manila")
SNIPE_IT_DEFAULT_SYNC_INTERVAL_SECONDS = 900
SNIPE_IT_WARRANTY_EXPIRING_DAYS = 90


class SnipeItAssetStoreUnavailable(RuntimeError):
    """Raised when the normalized Snipe-IT asset store has not been provisioned yet."""


@dataclass(frozen=True, slots=True)
class SnipeItDashboardAssetRecord:
    source_asset_id: int
    asset_tag: str | None = None
    serial: str | None = None
    category: str | None = None
    company: str | None = None
    status_label: str | None = None
    assigned_to_id: int | None = None
    location: str | None = None
    warranty_expires: date | None = None
    synced_at: datetime | None = None


class SnipeItAssetRepository(Protocol):
    def list_assets(self) -> list[SnipeItDashboardAssetRecord]: ...


class SqlAlchemySnipeItAssetRepository:
    """Read normalized Snipe-IT assets without coupling to the pending ORM model."""

    _REQUIRED_COLUMNS = {
        "source_asset_id",
        "asset_tag",
        "serial",
        "category",
        "company",
        "status_label",
        "assigned_to_id",
        "location",
        "warranty_expires",
        "synced_at",
    }

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_assets(self) -> list[SnipeItDashboardAssetRecord]:
        try:
            assets = Table("assets", MetaData(), autoload_with=self._db.get_bind())
        except NoSuchTableError as exc:
            raise SnipeItAssetStoreUnavailable from exc

        if not self._REQUIRED_COLUMNS.issubset(set(assets.c.keys())):
            raise SnipeItAssetStoreUnavailable

        rows = self._db.execute(
            select(
                assets.c.source_asset_id,
                assets.c.asset_tag,
                assets.c.serial,
                assets.c.category,
                assets.c.company,
                assets.c.status_label,
                assets.c.assigned_to_id,
                assets.c.location,
                assets.c.warranty_expires,
                assets.c.synced_at,
            ).order_by(assets.c.source_asset_id)
        ).mappings()

        try:
            return [
                SnipeItDashboardAssetRecord(
                    source_asset_id=int(row["source_asset_id"]),
                    asset_tag=_optional_text(row["asset_tag"]),
                    serial=_optional_text(row["serial"]),
                    category=_optional_text(row["category"]),
                    company=_optional_text(row["company"]),
                    status_label=_optional_text(row["status_label"]),
                    assigned_to_id=_optional_positive_int(row["assigned_to_id"]),
                    location=_optional_text(row["location"]),
                    warranty_expires=_optional_date(row["warranty_expires"]),
                    synced_at=_optional_datetime(row["synced_at"]),
                )
                for row in rows
            ]
        except (TypeError, ValueError) as exc:
            raise SnipeItAssetStoreUnavailable from exc


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _status_label_is(value: str | None, *labels: str) -> bool:
    if not _has_text(value):
        return False
    normalized = value.strip().casefold()
    return normalized in {label.casefold() for label in labels}


def _status_label_contains(value: str | None, *terms: str) -> bool:
    if not _has_text(value):
        return False
    normalized = value.casefold()
    return any(term.casefold() in normalized for term in terms)


class SnipeItDashboardService:
    """Build Grafana-facing Snipe-IT metrics exclusively from normalized local data."""

    def __init__(
        self,
        db: Session,
        settings: Settings,
        *,
        asset_repository: SnipeItAssetRepository | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._db = db
        self._settings = settings
        self._asset_repository = asset_repository or SqlAlchemySnipeItAssetRepository(db)
        self._clock = clock

    def get_dashboard(self) -> SnipeItDashboardResponse:
        now = self._clock()
        storage_available = True
        try:
            assets = self._asset_repository.list_assets()
        except SnipeItAssetStoreUnavailable:
            assets = []
            storage_available = False

        latest_run = self._latest_run()
        last_success = self._latest_success()
        health_status, is_stale, warnings = self._health_state(
            now=now,
            asset_count=len(assets),
            storage_available=storage_available,
            latest_run=latest_run,
            last_success=last_success,
        )

        local_today = now.astimezone(SNIPE_IT_DASHBOARD_TIMEZONE).date()
        warranty_soon = local_today + timedelta(days=SNIPE_IT_WARRANTY_EXPIRING_DAYS)
        summary = SnipeItDashboardSummary(
            assets_total=len(assets),
            assets_assigned=sum(asset.assigned_to_id is not None for asset in assets),
            assets_unassigned=sum(asset.assigned_to_id is None for asset in assets),
            assets_deployed=sum(asset.assigned_to_id is not None for asset in assets),
            assets_available=sum(
                asset.assigned_to_id is None
                and _status_label_is(asset.status_label, "available", "ready to deploy")
                for asset in assets
            ),
            assets_maintenance=sum(
                _status_label_contains(asset.status_label, "maintenance", "repair")
                for asset in assets
            ),
            assets_retired=sum(
                _status_label_contains(asset.status_label, "retired") for asset in assets
            ),
            assets_missing_serial=sum(not _has_text(asset.serial) for asset in assets),
            assets_missing_asset_tag=sum(not _has_text(asset.asset_tag) for asset in assets),
            warranty_expired=sum(
                asset.warranty_expires is not None and asset.warranty_expires < local_today
                for asset in assets
            ),
            warranty_expiring_soon=sum(
                asset.warranty_expires is not None
                and local_today <= asset.warranty_expires <= warranty_soon
                for asset in assets
            ),
        )

        health = self._build_health(
            now=now,
            status=health_status,
            is_stale=is_stale,
            last_success=last_success,
            warnings=warnings,
        )
        return SnipeItDashboardResponse(
            observed_at=now,
            is_stale=is_stale,
            health=health,
            summary=summary,
            status_distribution=_named_counts(
                (asset.status_label or "Unknown" for asset in assets),
                limit=20,
            ),
            category_distribution=_named_counts(
                (asset.category or "Uncategorized" for asset in assets),
                limit=10,
            ),
            company_distribution=_named_counts(
                (asset.company or "Unknown" for asset in assets),
                limit=50,
            ),
            location_distribution=_named_counts(
                (asset.location or "Unknown" for asset in assets),
                limit=10,
            ),
            warnings=warnings,
        )

    def get_warranty_expiry(self) -> SnipeItWarrantyExpiryResponse:
        assets = self._asset_repository.list_assets()
        now = self._clock().astimezone(SNIPE_IT_DASHBOARD_TIMEZONE).date()
        warranty_limit = now + timedelta(days=SNIPE_IT_WARRANTY_EXPIRING_DAYS)

        return SnipeItWarrantyExpiryResponse(
            warranty_expiry=[
                SnipeItWarrantyExpiryItem(
                    asset_tag=asset.asset_tag,
                    serial=asset.serial,
                    category=asset.category,
                    location=asset.location,
                    warranty_expires=asset.warranty_expires.isoformat(),
                )
                for asset in assets
                if asset.warranty_expires is not None
                and now <= asset.warranty_expires <= warranty_limit
            ][:10]
        )

    def get_executive_summary(self) -> ExecutiveSourceSummary:
        dashboard = self.get_dashboard()
        summary = dashboard.summary

        return ExecutiveSourceSummary(
            source="snipe_it",
            observed_at=dashboard.observed_at,
            is_stale=dashboard.is_stale,
            health=dashboard.health,
            metrics={
                "assets_total": summary.assets_total,
                "assets_assigned": summary.assets_assigned,
                "assets_unassigned": summary.assets_unassigned,
                "assets_missing_serial": summary.assets_missing_serial,
                "assets_missing_asset_tag": summary.assets_missing_asset_tag,
                "warranty_expired": summary.warranty_expired,
                "warranty_expiring_soon": summary.warranty_expiring_soon,
            },
            warnings=dashboard.warnings,
        )

    def _latest_run(self) -> SyncRun | None:
        return self._db.scalar(
            select(SyncRun)
            .where(SyncRun.source == "snipe_it")
            .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
            .limit(1)
        )

    def _latest_success(self) -> SyncRun | None:
        return self._db.scalar(
            select(SyncRun)
            .where(SyncRun.source == "snipe_it", SyncRun.status == "success")
            .order_by(SyncRun.completed_at.desc(), SyncRun.id.desc())
            .limit(1)
        )

    def _health_state(
        self,
        *,
        now: datetime,
        asset_count: int,
        storage_available: bool,
        latest_run: SyncRun | None,
        last_success: SyncRun | None,
    ) -> tuple[IntegrationStatus, bool, list[str]]:
        warnings: list[str] = []
        configured = self._settings.integration_config_state("snipe_it") == "configured"

        if not configured:
            if asset_count:
                warnings.append("Snipe-IT is not configured; showing previously synchronized data.")
            return "not_configured", asset_count > 0, warnings

        if not storage_available:
            warnings.append("Snipe-IT synchronized asset storage is not available.")
            return "unavailable", False, warnings

        if last_success is None:
            if latest_run is not None and latest_run.status == "failed":
                warnings.append("Snipe-IT has not completed a successful synchronization.")
                return "unavailable", asset_count > 0, warnings
            warnings.append("Snipe-IT has not completed its initial synchronization.")
            return "degraded", asset_count > 0, warnings

        status = "healthy"
        is_stale = False
        if latest_run is not None and latest_run.id != last_success.id and latest_run.status == "failed":
            warnings.append("The latest Snipe-IT synchronization failed; showing last successful data.")
            status = "degraded"
            is_stale = True

        stale_after = timedelta(
            seconds=getattr(
                self._settings,
                "snipe_it_sync_interval_seconds",
                SNIPE_IT_DEFAULT_SYNC_INTERVAL_SECONDS,
            )
            * 2
        )
        if last_success.completed_at is not None and now - last_success.completed_at > stale_after:
            warnings.append("Snipe-IT synchronized data is older than the expected refresh window.")
            status = "degraded"
            is_stale = True

        return status, is_stale, warnings

    @staticmethod
    def _build_health(
        *,
        now: datetime,
        status: IntegrationStatus,
        is_stale: bool,
        last_success: SyncRun | None,
        warnings: list[str],
    ) -> IntegrationHealthSummary:
        return IntegrationHealthSummary(
            source="snipe_it",
            status=status,
            observed_at=now,
            last_success_at=last_success.completed_at if last_success is not None else None,
            is_stale=is_stale,
            warnings=warnings,
        )


def get_snipe_it_dashboard_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SnipeItDashboardService:
    return SnipeItDashboardService(db=db, settings=settings)


def _named_counts(values, *, limit: int) -> list[SnipeItNamedCount]:
    counts = Counter(_normalized_label(value) for value in values)
    return [
        SnipeItNamedCount(name=name, count=count)
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _normalized_label(value: str) -> str:
    text = value.strip()
    return text or "Unknown"


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _optional_text(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Snipe-IT stored text is invalid")
    text = value.strip()
    return text or None


def _optional_positive_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Snipe-IT stored integer is invalid")
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("Snipe-IT stored integer is invalid")
    return parsed


def _optional_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise ValueError("Snipe-IT stored date is invalid")


def _optional_datetime(value) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError("Snipe-IT stored datetime is invalid")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

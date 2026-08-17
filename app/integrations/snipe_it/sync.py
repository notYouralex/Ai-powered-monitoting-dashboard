from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import IntegrationError
from app.db.models import Asset, SyncRun
from app.integrations.snipe_it.client import SnipeItClient
from app.integrations.snipe_it.models import SnipeItAsset


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SnipeItSyncService:
    """Persist full bounded Snipe-IT asset snapshots without source-side writes."""

    def __init__(
        self,
        client: SnipeItClient,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._client = client
        self._clock = clock

    async def sync(self, db: Session) -> SyncRun:
        run = SyncRun(
            source="snipe_it",
            sync_type="full",
            status="running",
            started_at=self._clock(),
            records_received=0,
            records_upserted=0,
        )
        db.add(run)
        db.commit()
        run_id = run.id

        try:
            assets = await self._client.list_assets()
        except IntegrationError as exc:
            self._mark_failed(db, run_id, exc.code)
            raise

        completed_at = self._clock()
        unique_assets = {asset.asset_id: asset for asset in assets}
        try:
            existing: dict[int, Asset] = {}
            if unique_assets:
                existing = {
                    asset.source_asset_id: asset
                    for asset in db.scalars(
                        select(Asset).where(Asset.source_asset_id.in_(unique_assets))
                    )
                }

            for source_asset_id, asset in unique_assets.items():
                record = existing.get(source_asset_id)
                if record is None:
                    record = Asset(
                        source_asset_id=source_asset_id,
                        synced_at=completed_at,
                    )
                    db.add(record)
                _apply_asset(record, asset, synced_at=completed_at)

            persisted_run = db.get(SyncRun, run_id)
            if persisted_run is None:
                raise RuntimeError("Snipe-IT sync run disappeared")
            persisted_run.status = "success"
            persisted_run.completed_at = completed_at
            persisted_run.records_received = len(assets)
            persisted_run.records_upserted = len(unique_assets)
            persisted_run.error_code = None
            db.commit()
            return persisted_run
        except SQLAlchemyError:
            db.rollback()
            self._mark_failed(db, run_id, "SYNC_DATABASE_ERROR")
            raise

    def _mark_failed(self, db: Session, run_id: int, error_code: str) -> None:
        run = db.get(SyncRun, run_id)
        if run is None:
            return
        run.status = "failed"
        run.completed_at = self._clock()
        run.error_code = error_code[:64]
        run.records_upserted = 0
        db.commit()


def _apply_asset(record: Asset, asset: SnipeItAsset, *, synced_at: datetime) -> None:
    record.asset_tag = asset.asset_tag
    record.name = asset.name
    record.serial = asset.serial
    record.model_id = asset.model_id
    record.model = asset.model
    record.category_id = asset.category_id
    record.category = asset.category
    record.manufacturer_id = asset.manufacturer_id
    record.manufacturer = asset.manufacturer
    record.status_label_id = asset.status_label_id
    record.status_label = asset.status_label
    record.status_type = asset.status_type
    record.assigned_to_id = asset.assigned_to_id
    record.assigned_type = asset.assigned_type
    record.location_id = asset.location_id
    record.location = asset.location
    record.purchase_date = asset.purchase_date
    record.warranty_months = asset.warranty_months
    record.warranty_expires = asset.warranty_expires
    record.synced_at = synced_at

import asyncio
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import IntegrationError
from app.db.base import Base
from app.db.models import Asset, SyncRun
from app.db.session import create_engine_for_url
from app.integrations.snipe_it.models import SnipeItAsset
from app.integrations.snipe_it.sync import SnipeItSyncService


T0 = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=15)


def normalized_asset(asset_id: int = 101, **overrides) -> SnipeItAsset:
    values = {
        "asset_id": asset_id,
        "asset_tag": f"LT-{asset_id}",
        "name": "Engineering Laptop",
        "serial": f"SERIAL-{asset_id}",
        "model_id": 11,
        "model": "Latitude 7450",
        "category_id": 12,
        "category": "Laptop",
        "manufacturer_id": 13,
        "manufacturer": "Dell",
        "status_label_id": 14,
        "status_label": "Ready to Deploy",
        "status_type": "deployable",
        "assigned_to_id": 15,
        "assigned_type": "user",
        "location_id": 16,
        "location": "Main Office",
        "purchase_date": date(2026, 1, 15),
        "warranty_months": 36,
        "warranty_expires": date(2029, 1, 15),
    }
    values.update(overrides)
    return SnipeItAsset(**values)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def list_assets(self):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_db() -> Session:
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_sync_upserts_assets_without_duplicates_or_mass_deactivation() -> None:
    async def run() -> None:
        db = make_db()
        client = FakeClient(
            [
                [normalized_asset(101), normalized_asset(102)],
                [normalized_asset(101, name="Renamed Laptop", status_label="Deployed")],
            ]
        )
        clock_values = iter([T0, T0, T1, T1])
        service = SnipeItSyncService(client, clock=lambda: next(clock_values))

        first = await service.sync(db)
        second = await service.sync(db)

        assets = db.scalars(select(Asset).order_by(Asset.source_asset_id)).all()
        runs = db.scalars(
            select(SyncRun).where(SyncRun.source == "snipe_it").order_by(SyncRun.id)
        ).all()

        assert first.status == "success"
        assert second.status == "success"
        assert client.calls == 2
        assert len(assets) == 2
        assert assets[0].source_asset_id == 101
        assert assets[0].name == "Renamed Laptop"
        assert assets[0].status_label == "Deployed"
        assert assets[0].assigned_to_id == 15
        assert assets[0].synced_at == T1
        assert assets[1].source_asset_id == 102
        assert assets[1].name == "Engineering Laptop"
        assert [run.sync_type for run in runs] == ["full", "full"]
        assert [run.records_received for run in runs] == [2, 1]
        assert [run.records_upserted for run in runs] == [2, 1]
        db.close()

    asyncio.run(run())


def test_failed_sync_preserves_existing_assets_and_records_safe_error() -> None:
    async def run() -> None:
        db = make_db()
        db.add(
            Asset(
                source_asset_id=101,
                asset_tag="LT-101",
                name="Existing Laptop",
                synced_at=T0,
            )
        )
        db.commit()
        error = IntegrationError(
            source="snipe_it",
            code="SOURCE_UNAVAILABLE",
            retryable=True,
        )
        client = FakeClient([error])
        clock_values = iter([T1, T1])
        service = SnipeItSyncService(client, clock=lambda: next(clock_values))

        try:
            await service.sync(db)
        except IntegrationError as exc:
            assert exc is error
        else:
            raise AssertionError("sync should propagate the source error")

        asset = db.scalar(select(Asset).where(Asset.source_asset_id == 101))
        run = db.scalar(
            select(SyncRun)
            .where(SyncRun.source == "snipe_it")
            .order_by(SyncRun.id.desc())
        )
        assert asset is not None
        assert asset.name == "Existing Laptop"
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "SOURCE_UNAVAILABLE"
        assert run.records_upserted == 0
        db.close()

    asyncio.run(run())

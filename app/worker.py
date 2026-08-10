import asyncio
import sys
from collections.abc import Callable

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.core.errors import IntegrationError
from app.db.session import SessionLocal
from app.integrations.freshservice.client import FreshserviceClient
from app.integrations.freshservice.sync import FreshserviceSyncService


async def run_freshservice_sync_once(
    *,
    settings: Settings,
    session_factory=SessionLocal,
    client_factory: Callable[[Settings], FreshserviceClient] = FreshserviceClient.from_settings,
) -> str:
    if settings.integration_config_state("freshservice") != "configured":
        return "not_configured"

    client = client_factory(settings)
    with session_factory() as db:
        run = await FreshserviceSyncService(client).sync(db)
    return run.status


async def run_worker() -> None:
    settings = get_settings()
    while True:
        try:
            await run_freshservice_sync_once(settings=settings)
        except IntegrationError as exc:
            print(f"Freshservice synchronization failed: {exc.code}", file=sys.stderr)
        except SQLAlchemyError:
            print("Freshservice synchronization database operation failed.", file=sys.stderr)
        await asyncio.sleep(settings.freshservice_sync_interval_seconds)


def main() -> int:
    asyncio.run(run_worker())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

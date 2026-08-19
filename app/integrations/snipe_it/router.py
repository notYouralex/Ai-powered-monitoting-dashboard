from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.grafana.dependencies import require_dashboard_access
from app.integrations.snipe_it.client import SnipeItClient
from app.integrations.snipe_it.dashboard_models import (
    SnipeItDashboardResponse,
    SnipeItRecentActivityResponse,
)
from app.integrations.snipe_it.dashboard_service import (
    SnipeItDashboardService,
    get_snipe_it_dashboard_service,
)


def get_snipe_it_client(
    settings: Settings = Depends(get_settings),
) -> SnipeItClient:
    return SnipeItClient.from_settings(settings)


router = APIRouter(
    prefix="/api/dashboard/snipe-it",
    tags=["dashboard", "snipe-it"],
    dependencies=[Depends(require_dashboard_access)],
)


@router.get("", response_model=SnipeItDashboardResponse)
def get_snipe_it_dashboard(
    service: SnipeItDashboardService = Depends(get_snipe_it_dashboard_service),
) -> SnipeItDashboardResponse:
    return service.get_dashboard()


@router.get("/recent-activity", response_model=SnipeItRecentActivityResponse)
async def get_snipe_it_recent_activity(
    client: SnipeItClient = Depends(get_snipe_it_client),
) -> SnipeItRecentActivityResponse:
    return SnipeItRecentActivityResponse(activity=await client.list_recent_activity())

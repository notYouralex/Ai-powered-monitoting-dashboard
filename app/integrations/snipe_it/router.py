from fastapi import APIRouter, Depends

from app.grafana.dependencies import require_dashboard_access
from app.integrations.snipe_it.dashboard_models import SnipeItDashboardResponse
from app.integrations.snipe_it.dashboard_service import (
    SnipeItDashboardService,
    get_snipe_it_dashboard_service,
)


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

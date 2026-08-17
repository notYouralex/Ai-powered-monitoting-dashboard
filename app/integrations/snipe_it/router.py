from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.integrations.snipe_it.dashboard_models import SnipeItDashboardResponse
from app.integrations.snipe_it.dashboard_service import (
    SnipeItDashboardService,
    get_snipe_it_dashboard_service,
)


router = APIRouter(
    prefix="/api/dashboard/snipe-it",
    tags=["dashboard", "snipe-it"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=SnipeItDashboardResponse)
def get_snipe_it_dashboard(
    service: SnipeItDashboardService = Depends(get_snipe_it_dashboard_service),
) -> SnipeItDashboardResponse:
    return service.get_dashboard()

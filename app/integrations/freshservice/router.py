from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.integrations.freshservice.models import FreshserviceDashboardResponse
from app.integrations.freshservice.service import FreshserviceDashboardService


router = APIRouter(
    prefix="/api/dashboard/freshservice",
    tags=["dashboard", "freshservice"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=FreshserviceDashboardResponse)
def get_freshservice_dashboard(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FreshserviceDashboardResponse:
    return FreshserviceDashboardService(db, settings).get_dashboard()

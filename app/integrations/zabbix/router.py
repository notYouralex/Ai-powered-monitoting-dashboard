from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.integrations.zabbix.cache import ZabbixCachedDashboardService
from app.integrations.zabbix.models import ZabbixDashboardResponse


router = APIRouter(
    prefix="/api/dashboard/zabbix",
    tags=["dashboard", "zabbix"],
    dependencies=[Depends(get_current_user)],
)


def get_zabbix_dashboard_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ZabbixCachedDashboardService:
    return ZabbixCachedDashboardService(db, settings)


@router.get("", response_model=ZabbixDashboardResponse)
def get_zabbix_dashboard(
    service: ZabbixCachedDashboardService = Depends(get_zabbix_dashboard_service),
) -> ZabbixDashboardResponse:
    return service.get_dashboard()

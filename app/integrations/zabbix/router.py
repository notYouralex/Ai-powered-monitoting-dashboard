from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.integrations.zabbix.client import ZabbixClient
from app.integrations.zabbix.models import ZabbixDashboardResponse
from app.integrations.zabbix.service import ZabbixDashboardService


router = APIRouter(
    prefix="/api/dashboard/zabbix",
    tags=["dashboard", "zabbix"],
    dependencies=[Depends(get_current_user)],
)


def get_zabbix_dashboard_service(
    settings: Settings = Depends(get_settings),
) -> ZabbixDashboardService:
    return ZabbixDashboardService(
        client=ZabbixClient.from_settings(settings),
    )


@router.get("", response_model=ZabbixDashboardResponse)
async def get_zabbix_dashboard(
    service: ZabbixDashboardService = Depends(get_zabbix_dashboard_service),
) -> ZabbixDashboardResponse:
    return await service.get_dashboard()

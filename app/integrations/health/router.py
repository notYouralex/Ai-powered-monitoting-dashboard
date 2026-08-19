from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.contracts import ExecutiveSourceSummary
from app.core.config import Settings, get_settings
from app.core.errors import IntegrationError
from app.db.session import get_db
from app.grafana.dependencies import require_dashboard_access
from app.integrations.freshservice.service import FreshserviceDashboardService
from app.integrations.health.models import IntegrationHealthResponse
from app.integrations.health.service import IntegrationHealthService, WazuhHealthProvider
from app.integrations.snipe_it.dashboard_service import (
    SnipeItDashboardService,
    get_snipe_it_dashboard_service,
)
from app.integrations.wazuh.router import get_wazuh_dashboard_service
from app.integrations.zabbix.cache import ZabbixCachedDashboardService
from app.integrations.zabbix.router import get_zabbix_dashboard_service


router = APIRouter(
    prefix="/api/integrations/health",
    tags=["integrations", "health"],
    dependencies=[Depends(require_dashboard_access)],
)


class _DeferredWazuhHealthProvider:
    def __init__(self, error: IntegrationError) -> None:
        self._error = error

    async def get_executive_summary(
        self,
        start: datetime,
        end: datetime,
    ) -> ExecutiveSourceSummary:
        raise self._error


def get_wazuh_health_provider(
    settings: Settings = Depends(get_settings),
) -> WazuhHealthProvider:
    try:
        return get_wazuh_dashboard_service(settings)
    except IntegrationError as exc:
        return _DeferredWazuhHealthProvider(exc)


def get_integration_health_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    wazuh_service: WazuhHealthProvider = Depends(get_wazuh_health_provider),
    zabbix_service: ZabbixCachedDashboardService = Depends(get_zabbix_dashboard_service),
    snipe_it_service: SnipeItDashboardService = Depends(get_snipe_it_dashboard_service),
) -> IntegrationHealthService:
    return IntegrationHealthService(
        wazuh_service=wazuh_service,
        zabbix_service=zabbix_service,
        snipe_it_service=snipe_it_service,
        freshservice_service=FreshserviceDashboardService(db, settings),
    )


@router.get("", response_model=IntegrationHealthResponse)
async def get_integration_health(
    service: IntegrationHealthService = Depends(get_integration_health_service),
) -> IntegrationHealthResponse:
    return await service.get_health()

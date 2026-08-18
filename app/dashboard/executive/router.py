from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.dashboard.executive.models import ExecutiveDashboardResponse
from app.dashboard.executive.service import ExecutiveDashboardService
from app.db.session import get_db
from app.grafana.dependencies import require_dashboard_access
from app.integrations.freshservice.service import FreshserviceDashboardService
from app.integrations.snipe_it.dashboard_service import (
    SnipeItDashboardService,
    get_snipe_it_dashboard_service,
)
from app.integrations.wazuh.router import get_wazuh_dashboard_service
from app.integrations.wazuh.service import WazuhDashboardService
from app.integrations.zabbix.cache import ZabbixCachedDashboardService
from app.integrations.zabbix.router import get_zabbix_dashboard_service


EXECUTIVE_DEFAULT_RANGE = timedelta(hours=24)
EXECUTIVE_MAX_RANGE = timedelta(days=30)

router = APIRouter(
    prefix="/api/dashboard/executive",
    tags=["dashboard", "executive"],
    dependencies=[Depends(require_dashboard_access)],
)


def get_executive_dashboard_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    wazuh_service: WazuhDashboardService = Depends(get_wazuh_dashboard_service),
    zabbix_service: ZabbixCachedDashboardService = Depends(get_zabbix_dashboard_service),
    snipe_it_service: SnipeItDashboardService = Depends(get_snipe_it_dashboard_service),
) -> ExecutiveDashboardService:
    return ExecutiveDashboardService(
        wazuh_service=wazuh_service,
        zabbix_service=zabbix_service,
        snipe_it_service=snipe_it_service,
        freshservice_service=FreshserviceDashboardService(db, settings),
    )


@router.get("", response_model=ExecutiveDashboardResponse)
async def get_executive_dashboard(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    service: ExecutiveDashboardService = Depends(get_executive_dashboard_service),
) -> ExecutiveDashboardResponse:
    start, end = _resolve_time_range(from_, to)
    return await service.get_dashboard(start, end)


def _resolve_time_range(
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime]:
    resolved_end = end or datetime.now(timezone.utc)
    resolved_start = start or (resolved_end - EXECUTIVE_DEFAULT_RANGE)

    if resolved_start.tzinfo is None or resolved_end.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Executive dashboard time range must include a timezone offset",
        )

    resolved_start = resolved_start.astimezone(timezone.utc)
    resolved_end = resolved_end.astimezone(timezone.utc)

    if resolved_start >= resolved_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Executive dashboard 'from' must be earlier than 'to'",
        )
    if resolved_end - resolved_start > EXECUTIVE_MAX_RANGE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Executive dashboard time range cannot exceed 30 days",
        )

    return resolved_start, resolved_end

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.grafana.dependencies import require_dashboard_access
from app.core.config import Settings, get_settings
from app.integrations.wazuh.client import WazuhClient
from app.integrations.wazuh.indexer_client import WazuhIndexerClient
from app.integrations.wazuh.models import WazuhDashboardResponse
from app.integrations.wazuh.service import WazuhDashboardService


WAZUH_DEFAULT_RANGE = timedelta(hours=24)
WAZUH_MAX_RANGE = timedelta(days=30)

router = APIRouter(
    prefix="/api/dashboard/wazuh",
    tags=["dashboard", "wazuh"],
    dependencies=[Depends(require_dashboard_access)],
)


def get_wazuh_dashboard_service(
    settings: Settings = Depends(get_settings),
) -> WazuhDashboardService:
    return WazuhDashboardService(
        agent_client=WazuhClient.from_settings(settings),
        indexer_client=WazuhIndexerClient.from_settings(settings),
    )


@router.get("", response_model=WazuhDashboardResponse)
async def get_wazuh_dashboard(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    service: WazuhDashboardService = Depends(get_wazuh_dashboard_service),
) -> WazuhDashboardResponse:
    start, end = _resolve_time_range(from_, to)
    return await service.get_dashboard(start, end)


def _resolve_time_range(
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime]:
    resolved_end = end or datetime.now(timezone.utc)
    resolved_start = start or (resolved_end - WAZUH_DEFAULT_RANGE)

    if resolved_start.tzinfo is None or resolved_end.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Wazuh dashboard time range must include a timezone offset",
        )

    resolved_start = resolved_start.astimezone(timezone.utc)
    resolved_end = resolved_end.astimezone(timezone.utc)

    if resolved_start >= resolved_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Wazuh dashboard 'from' must be earlier than 'to'",
        )
    if resolved_end - resolved_start > WAZUH_MAX_RANGE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Wazuh dashboard time range cannot exceed 30 days",
        )

    return resolved_start, resolved_end

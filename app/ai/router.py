from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.ai.cache import AIExecutiveSummaryCache
from app.ai.devices import AIDeviceRepository
from app.ai.errors import AIError
from app.ai.freshservice import AIFreshserviceRepository
from app.ai.models import (
    AIDashboardSummaryResponse,
    AIInvestigationResponse,
    AIQueryRequest,
    AIQueryResponse,
)
from app.ai.ollama import OllamaProvider
from app.ai.service import AIService
from app.ai.snipe_it import AISnipeItRepository
from app.auth.dependencies import get_current_user
from app.contracts import IntegrationSource
from app.core.config import Settings, get_settings
from app.dashboard.executive.router import get_executive_dashboard_service
from app.dashboard.executive.service import ExecutiveDashboardService
from app.db.session import get_db
from app.grafana.dependencies import require_dashboard_access
from app.integrations.wazuh.router import get_wazuh_dashboard_service
from app.integrations.zabbix.cache import ZabbixCachedDashboardService
from app.integrations.zabbix.router import get_zabbix_dashboard_service


AI_DEFAULT_RANGE = timedelta(hours=24)
AI_MAX_RANGE = timedelta(days=30)

router = APIRouter(prefix="/api/ai", tags=["ai"])
_dashboard_summary_cache = AIExecutiveSummaryCache()
_executive_summary_cache = AIExecutiveSummaryCache()
_wazuh_summary_cache = AIExecutiveSummaryCache()
_zabbix_summary_cache = AIExecutiveSummaryCache()
_snipe_it_summary_cache = AIExecutiveSummaryCache()
_freshservice_summary_cache = AIExecutiveSummaryCache()


class _LazyWazuhDashboardService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def get_dashboard(self, start: datetime, end: datetime):
        service = get_wazuh_dashboard_service(self._settings)
        return await service.get_dashboard(start, end)


def get_ai_investigation_service(
    settings: Settings = Depends(get_settings),
    executive_service: ExecutiveDashboardService = Depends(get_executive_dashboard_service),
    zabbix_service: ZabbixCachedDashboardService = Depends(get_zabbix_dashboard_service),
    db: Session = Depends(get_db),
) -> AIService:
    return AIService(
        provider=OllamaProvider(settings),
        executive_service=executive_service,
        device_repository=AIDeviceRepository(db),
        freshservice_repository=AIFreshserviceRepository(db),
        snipe_it_repository=AISnipeItRepository(db),
        wazuh_service=_LazyWazuhDashboardService(settings),
        zabbix_service=zabbix_service,
    )


def get_ai_dashboard_summary_cache() -> AIExecutiveSummaryCache:
    return _dashboard_summary_cache


def get_ai_summary_cache() -> AIExecutiveSummaryCache:
    return _executive_summary_cache


def get_ai_wazuh_summary_cache() -> AIExecutiveSummaryCache:
    return _wazuh_summary_cache


def get_ai_zabbix_summary_cache() -> AIExecutiveSummaryCache:
    return _zabbix_summary_cache


def get_ai_snipe_it_summary_cache() -> AIExecutiveSummaryCache:
    return _snipe_it_summary_cache


def get_ai_freshservice_summary_cache() -> AIExecutiveSummaryCache:
    return _freshservice_summary_cache


def get_ai_service(
    settings: Settings = Depends(get_settings),
    executive_service: ExecutiveDashboardService = Depends(get_executive_dashboard_service),
) -> AIService:
    return AIService(
        provider=OllamaProvider(settings),
        executive_service=executive_service,
    )


@router.post(
    "/query",
    response_model=AIInvestigationResponse,
    dependencies=[Depends(get_current_user)],
)
async def query_ai(
    request: AIQueryRequest,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    service: AIService = Depends(get_ai_investigation_service),
) -> AIInvestigationResponse:
    if not settings.ai_enabled:
        raise AIError(code="AI_DISABLED", retryable=False)

    start, end = _resolve_time_range(from_, to)
    return await service.investigate(request.question, start, end)


@router.get(
    "/insights/dashboard",
    response_model=AIDashboardSummaryResponse,
    dependencies=[Depends(require_dashboard_access)],
)
async def get_dashboard_ai_insight(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    service: AIService = Depends(get_ai_service),
    cache: AIExecutiveSummaryCache = Depends(get_ai_dashboard_summary_cache),
) -> AIDashboardSummaryResponse:
    if not settings.ai_enabled:
        raise AIError(code="AI_DISABLED", retryable=False)

    start, end = _resolve_time_range(from_, to)
    return await cache.get_or_generate(
        start=start,
        end=end,
        ttl_seconds=settings.ai_summary_cache_seconds,
        generate=service.summarize_dashboard,
    )


@router.get(
    "/insights/executive",
    response_model=AIQueryResponse,
    dependencies=[Depends(require_dashboard_access)],
)
async def get_executive_ai_insight(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    service: AIService = Depends(get_ai_service),
    cache: AIExecutiveSummaryCache = Depends(get_ai_summary_cache),
) -> AIQueryResponse:
    if not settings.ai_enabled:
        raise AIError(code="AI_DISABLED", retryable=False)

    start, end = _resolve_time_range(from_, to)
    return await cache.get_or_generate(
        start=start,
        end=end,
        ttl_seconds=settings.ai_summary_cache_seconds,
        generate=service.summarize_executive,
    )


@router.get(
    "/insights/wazuh",
    response_model=AIQueryResponse,
    dependencies=[Depends(require_dashboard_access)],
)
async def get_wazuh_ai_insight(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    service: AIService = Depends(get_ai_service),
    cache: AIExecutiveSummaryCache = Depends(get_ai_wazuh_summary_cache),
) -> AIQueryResponse:
    return await _get_source_ai_insight(
        source="wazuh",
        from_=from_,
        to=to,
        settings=settings,
        service=service,
        cache=cache,
    )


@router.get(
    "/insights/zabbix",
    response_model=AIQueryResponse,
    dependencies=[Depends(require_dashboard_access)],
)
async def get_zabbix_ai_insight(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    service: AIService = Depends(get_ai_service),
    cache: AIExecutiveSummaryCache = Depends(get_ai_zabbix_summary_cache),
) -> AIQueryResponse:
    return await _get_source_ai_insight(
        source="zabbix",
        from_=from_,
        to=to,
        settings=settings,
        service=service,
        cache=cache,
    )


@router.get(
    "/insights/snipe-it",
    response_model=AIQueryResponse,
    dependencies=[Depends(require_dashboard_access)],
)
async def get_snipe_it_ai_insight(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    service: AIService = Depends(get_ai_service),
    cache: AIExecutiveSummaryCache = Depends(get_ai_snipe_it_summary_cache),
) -> AIQueryResponse:
    return await _get_source_ai_insight(
        source="snipe_it",
        from_=from_,
        to=to,
        settings=settings,
        service=service,
        cache=cache,
    )


@router.get(
    "/insights/freshservice",
    response_model=AIQueryResponse,
    dependencies=[Depends(require_dashboard_access)],
)
async def get_freshservice_ai_insight(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    service: AIService = Depends(get_ai_service),
    cache: AIExecutiveSummaryCache = Depends(get_ai_freshservice_summary_cache),
) -> AIQueryResponse:
    return await _get_source_ai_insight(
        source="freshservice",
        from_=from_,
        to=to,
        settings=settings,
        service=service,
        cache=cache,
    )


async def _get_source_ai_insight(
    *,
    source: IntegrationSource,
    from_: datetime | None,
    to: datetime | None,
    settings: Settings,
    service: AIService,
    cache: AIExecutiveSummaryCache,
) -> AIQueryResponse:
    if not settings.ai_enabled:
        raise AIError(code="AI_DISABLED", retryable=False)

    start, end = _resolve_time_range(from_, to)

    async def generate(range_start: datetime, range_end: datetime) -> AIQueryResponse:
        return await service.summarize_source(
            range_start,
            range_end,
            source=source,
        )

    return await cache.get_or_generate(
        start=start,
        end=end,
        ttl_seconds=settings.ai_summary_cache_seconds,
        generate=generate,
    )


def _resolve_time_range(
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime]:
    resolved_end = end or datetime.now(timezone.utc)
    resolved_start = start or (resolved_end - AI_DEFAULT_RANGE)

    if resolved_start.tzinfo is None or resolved_end.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="AI time range must include a timezone offset",
        )

    resolved_start = resolved_start.astimezone(timezone.utc)
    resolved_end = resolved_end.astimezone(timezone.utc)
    if resolved_start >= resolved_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="AI 'from' must be earlier than 'to'",
        )
    if resolved_end - resolved_start > AI_MAX_RANGE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="AI time range cannot exceed 30 days",
        )
    return resolved_start, resolved_end

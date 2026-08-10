from fastapi import APIRouter

from app.integrations.freshservice.router import router as freshservice_router
from app.integrations.snipe_it.router import router as snipe_it_router
from app.integrations.wazuh.router import router as wazuh_router
from app.integrations.zabbix.router import router as zabbix_router


router = APIRouter()
router.include_router(wazuh_router)
router.include_router(zabbix_router)
router.include_router(snipe_it_router)
router.include_router(freshservice_router)

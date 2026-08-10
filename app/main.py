from fastapi import FastAPI

from app.auth.admin_router import router as admin_router
from app.auth.router import router as auth_router
from app.core.errors import IntegrationError, integration_error_handler
from app.core.request_id import RequestIdMiddleware
from app.integrations.router import router as integrations_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI-Powered Monitoring Platform")
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(IntegrationError, integration_error_handler)
    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(integrations_router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

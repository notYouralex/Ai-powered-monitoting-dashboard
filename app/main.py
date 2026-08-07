from fastapi import FastAPI

from app.auth.admin_router import router as admin_router
from app.auth.router import router as auth_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI-Powered Monitoring Platform")
    app.include_router(auth_router)
    app.include_router(admin_router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

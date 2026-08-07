from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="AI-Powered Monitoring Platform")

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

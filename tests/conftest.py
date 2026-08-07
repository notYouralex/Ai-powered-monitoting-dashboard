from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import create_engine_for_url, get_db
from app.main import create_app


@pytest.fixture
def auth_env(tmp_path):
    database_path = tmp_path / "auth.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine_for_url(database_url)
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = Settings(
        app_env="test",
        app_secret_key="t" * 48,
        database_url=database_url,
        session_idle_minutes=30,
        session_absolute_hours=12,
        session_refresh_seconds=60,
        login_window_seconds=300,
        login_max_failures=3,
        cookie_secure=True,
        _env_file=None,
    )

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    def override_get_settings() -> Settings:
        return settings

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings

    with TestClient(app, base_url="https://testserver") as client:
        yield SimpleNamespace(
            client=client,
            session_factory=testing_session_local,
            settings=settings,
        )

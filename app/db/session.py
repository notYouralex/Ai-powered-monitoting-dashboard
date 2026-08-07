from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings


def create_engine_for_url(url: str) -> Engine:
    """Create a SQLAlchemy engine with safe defaults for the requested URL."""
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if url == "sqlite:///:memory:":
        kwargs.update(
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    elif url.startswith("sqlite:"):
        kwargs.update(connect_args={"check_same_thread": False})
    return create_engine(url, **kwargs)


engine = create_engine_for_url(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

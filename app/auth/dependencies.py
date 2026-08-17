from dataclasses import dataclass
from secrets import compare_digest

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.service import SESSION_COOKIE_NAME, revoke_session, validate_session_token
from app.core.config import Settings, get_settings
from app.db.models import AuthSession, User
from app.db.session import get_db


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


def _not_authenticated() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def get_auth_context(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise _not_authenticated()

    auth_session = validate_session_token(db, raw_token, settings)
    if auth_session is None or not auth_session.user.is_active:
        if auth_session is not None and auth_session.revoked_at is None:
            revoke_session(auth_session)
            db.commit()
        raise _not_authenticated()

    return AuthContext(user=auth_session.user, session=auth_session)


def require_dashboard_access(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    """Allow an interactive session or the configured Grafana read-only service token."""

    authorization = request.headers.get("Authorization")
    if authorization is not None:
        if _valid_grafana_service_token(authorization, settings):
            return
        raise _not_authenticated()

    get_auth_context(request=request, db=db, settings=settings)


def _valid_grafana_service_token(authorization: str, settings: Settings) -> bool:
    scheme, separator, raw_token = authorization.partition(" ")
    token = raw_token.strip()
    configured = settings.grafana_service_token
    if separator != " " or scheme.casefold() != "bearer" or not token or configured is None:
        return False
    return compare_digest(token, configured.get_secret_value())


def get_current_user(context: AuthContext = Depends(get_auth_context)) -> User:
    return context.user

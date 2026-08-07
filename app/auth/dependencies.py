from dataclasses import dataclass

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


def get_auth_context(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    auth_session = validate_session_token(db, raw_token, settings)
    if auth_session is None or not auth_session.user.is_active:
        if auth_session is not None and auth_session.revoked_at is None:
            revoke_session(auth_session)
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    return AuthContext(user=auth_session.user, session=auth_session)


def get_current_user(context: AuthContext = Depends(get_auth_context)) -> User:
    return context.user

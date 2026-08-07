from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context, get_current_user
from app.auth.security import hash_password, verify_password
from app.auth.service import (
    SESSION_COOKIE_NAME,
    create_session,
    is_login_rate_limited,
    normalize_username,
    record_auth_event,
    record_login_attempt,
    revoke_session,
)
from app.core.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-used-only-for-timing-equalization")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class UserResponse(BaseModel):
    username: str
    is_admin: bool


def _remote_addr(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


@router.post("/login", response_model=UserResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserResponse:
    username = normalize_username(payload.username)
    remote_addr = _remote_addr(request)

    if is_login_rate_limited(db, username, settings):
        record_auth_event(
            db,
            event_type="login",
            username=username,
            success=False,
            reason="rate_limited",
            remote_addr=remote_addr,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")

    user = db.scalar(select(User).where(User.username == username))
    password_valid = verify_password(
        payload.password,
        user.password_hash if user is not None else _DUMMY_PASSWORD_HASH,
    )

    if user is None or not password_valid:
        record_login_attempt(db, username=username, success=False, remote_addr=remote_addr)
        record_auth_event(
            db,
            event_type="login",
            username=username,
            user_id=user.id if user is not None else None,
            success=False,
            reason="invalid_credentials",
            remote_addr=remote_addr,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    if not user.is_active:
        record_login_attempt(db, username=username, success=False, remote_addr=remote_addr)
        record_auth_event(
            db,
            event_type="login",
            username=username,
            user_id=user.id,
            success=False,
            reason="inactive_user",
            remote_addr=remote_addr,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    _, raw_token = create_session(db, user, settings)
    record_login_attempt(db, username=username, success=True, remote_addr=remote_addr)
    record_auth_event(
        db,
        event_type="login",
        username=username,
        user_id=user.id,
        success=True,
        remote_addr=remote_addr,
    )
    db.commit()

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=settings.session_absolute_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return UserResponse(username=user.username, is_admin=user.is_admin)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    revoke_session(context.session)
    record_auth_event(
        db,
        event_type="logout",
        username=context.user.username,
        user_id=context.user.id,
        success=True,
    )
    db.commit()
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(username=user.username, is_admin=user.is_admin)

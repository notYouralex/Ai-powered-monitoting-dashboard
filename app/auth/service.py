from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.security import digest_session_token, generate_session_token
from app.core.config import Settings
from app.db.models import AuthAuditEvent, AuthSession, LoginAttempt, User

SESSION_COOKIE_NAME = "monitoring_session"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def is_login_rate_limited(
    db: Session,
    username: str,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> bool:
    current = now or utc_now()
    cutoff = current - timedelta(seconds=settings.login_window_seconds)
    failures = db.scalar(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.username == username,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= cutoff,
        )
    )
    return bool(failures and failures >= settings.login_max_failures)


def record_login_attempt(
    db: Session,
    *,
    username: str,
    success: bool,
    remote_addr: str | None = None,
) -> None:
    db.add(LoginAttempt(username=username, success=success, remote_addr=remote_addr))


def record_auth_event(
    db: Session,
    *,
    event_type: str,
    username: str | None,
    success: bool,
    user_id: int | None = None,
    reason: str | None = None,
    remote_addr: str | None = None,
) -> None:
    db.add(
        AuthAuditEvent(
            event_type=event_type,
            username=username,
            user_id=user_id,
            success=success,
            reason=reason,
            remote_addr=remote_addr,
        )
    )


def create_session(
    db: Session,
    user: User,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> tuple[AuthSession, str]:
    current = now or utc_now()
    raw_token = generate_session_token()
    session = AuthSession(
        user_id=user.id,
        token_digest=digest_session_token(raw_token),
        created_at=current,
        last_seen_at=current,
        idle_expires_at=current + timedelta(minutes=settings.session_idle_minutes),
        absolute_expires_at=current + timedelta(hours=settings.session_absolute_hours),
    )
    db.add(session)
    return session, raw_token


def validate_session_token(
    db: Session,
    raw_token: str,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> AuthSession | None:
    current = now or utc_now()
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_digest == digest_session_token(raw_token))
    )
    if session is None or session.revoked_at is not None:
        return None
    if as_utc(session.absolute_expires_at) <= current:
        return None
    if as_utc(session.idle_expires_at) <= current:
        return None

    refresh_after = as_utc(session.last_seen_at) + timedelta(seconds=settings.session_refresh_seconds)
    if refresh_after <= current:
        session.last_seen_at = current
        session.idle_expires_at = current + timedelta(minutes=settings.session_idle_minutes)
        db.commit()
    return session


def revoke_session(session: AuthSession, *, now: datetime | None = None) -> None:
    session.revoked_at = now or utc_now()

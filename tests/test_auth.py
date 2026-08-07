from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, Type
from sqlalchemy import select

from app.db.models import AuthAuditEvent, AuthSession, LoginAttempt, User


SESSION_COOKIE_NAME = "monitoring_session"


def create_user(auth_env, username="alice", password="correct horse", *, active=True, admin=False):
    password_hash = PasswordHasher(type=Type.ID).hash(password)
    with auth_env.session_factory() as db:
        user = User(
            username=username,
            password_hash=password_hash,
            is_active=active,
            is_admin=admin,
        )
        db.add(user)
        db.commit()
        return user.id


def login(auth_env, username="alice", password="correct horse"):
    return auth_env.client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )


def test_password_hashing_uses_argon2id() -> None:
    from app.auth.security import hash_password, verify_password

    password_hash = hash_password("long-enough-password")

    assert password_hash.startswith("$argon2id$")
    assert verify_password("long-enough-password", password_hash) is True
    assert verify_password("wrong-password", password_hash) is False


def test_successful_login_sets_secure_cookie_and_stores_only_digest(auth_env) -> None:
    create_user(auth_env)

    response = login(auth_env)

    assert response.status_code == 200
    assert response.json() == {"username": "alice", "is_admin": False}
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=strict" in set_cookie

    raw_token = auth_env.client.cookies.get(SESSION_COOKIE_NAME)
    assert raw_token
    with auth_env.session_factory() as db:
        session = db.scalar(select(AuthSession))
        audits = db.scalars(select(AuthAuditEvent)).all()
        attempts = db.scalars(select(LoginAttempt)).all()

        assert session is not None
        assert len(session.token_digest) == 64
        assert session.token_digest != raw_token
        assert all(raw_token not in (audit.reason or "") for audit in audits)
        assert [event.success for event in audits] == [True]
        assert [attempt.success for attempt in attempts] == [True]


def test_invalid_credentials_return_safe_error_and_are_audited(auth_env) -> None:
    create_user(auth_env)

    response = login(auth_env, password="wrong")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}
    assert "wrong" not in response.text

    with auth_env.session_factory() as db:
        audit = db.scalar(select(AuthAuditEvent))
        attempt = db.scalar(select(LoginAttempt))
        assert audit is not None
        assert audit.success is False
        assert audit.reason == "invalid_credentials"
        assert attempt is not None
        assert attempt.success is False


def test_inactive_user_cannot_login(auth_env) -> None:
    create_user(auth_env, active=False)

    response = login(auth_env)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password"}


def test_repeated_failures_are_rate_limited(auth_env) -> None:
    create_user(auth_env)

    for _ in range(auth_env.settings.login_max_failures):
        assert login(auth_env, password="wrong").status_code == 401

    response = login(auth_env, password="correct horse")

    assert response.status_code == 429
    assert response.json() == {"detail": "Too many login attempts"}


def test_me_requires_authentication(auth_env) -> None:
    response = auth_env.client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_me_returns_current_user(auth_env) -> None:
    create_user(auth_env, admin=True)
    assert login(auth_env).status_code == 200

    response = auth_env.client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {"username": "alice", "is_admin": True}


def test_idle_expired_session_is_rejected(auth_env) -> None:
    create_user(auth_env)
    assert login(auth_env).status_code == 200

    with auth_env.session_factory() as db:
        session = db.scalar(select(AuthSession))
        assert session is not None
        session.idle_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    response = auth_env.client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_absolute_expired_session_is_rejected(auth_env) -> None:
    create_user(auth_env)
    assert login(auth_env).status_code == 200

    with auth_env.session_factory() as db:
        session = db.scalar(select(AuthSession))
        assert session is not None
        session.absolute_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    response = auth_env.client.get("/api/auth/me")
    assert response.status_code == 401


def test_session_last_seen_refresh_is_bounded(auth_env) -> None:
    create_user(auth_env)
    assert login(auth_env).status_code == 200

    with auth_env.session_factory() as db:
        session = db.scalar(select(AuthSession))
        assert session is not None
        initial_last_seen = session.last_seen_at

    assert auth_env.client.get("/api/auth/me").status_code == 200

    with auth_env.session_factory() as db:
        session = db.scalar(select(AuthSession))
        assert session is not None
        assert session.last_seen_at == initial_last_seen
        session.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        session.idle_expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        db.commit()
        stale_last_seen = session.last_seen_at

    assert auth_env.client.get("/api/auth/me").status_code == 200

    with auth_env.session_factory() as db:
        session = db.scalar(select(AuthSession))
        assert session is not None
        assert session.last_seen_at > stale_last_seen


def test_logout_revokes_session_and_clears_authentication(auth_env) -> None:
    create_user(auth_env)
    assert login(auth_env).status_code == 200

    response = auth_env.client.post("/api/auth/logout")

    assert response.status_code == 204
    assert auth_env.client.get("/api/auth/me").status_code == 401
    with auth_env.session_factory() as db:
        session = db.scalar(select(AuthSession))
        assert session is not None
        assert session.revoked_at is not None

from argon2 import PasswordHasher, Type
from sqlalchemy import select

from app.db.models import AuthAuditEvent, User


def seed_user(auth_env, username, password, *, admin=False):
    with auth_env.session_factory() as db:
        user = User(
            username=username,
            password_hash=PasswordHasher(type=Type.ID).hash(password),
            is_admin=admin,
        )
        db.add(user)
        db.commit()
        return user.id


def login(auth_env, username, password):
    return auth_env.client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )


def test_regular_user_cannot_create_accounts(auth_env) -> None:
    seed_user(auth_env, "alice", "regular-user-password")
    assert login(auth_env, "alice", "regular-user-password").status_code == 200

    response = auth_env.client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "strong-password-123", "is_admin": False},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Administrator access required"}


def test_admin_can_create_user_without_exposing_password_hash(auth_env) -> None:
    admin_id = seed_user(auth_env, "admin", "administrator-password", admin=True)
    assert login(auth_env, "admin", "administrator-password").status_code == 200

    response = auth_env.client.post(
        "/api/admin/users",
        json={"username": "Bob", "password": "strong-password-123", "is_admin": False},
    )

    assert response.status_code == 201
    assert response.json() == {"username": "bob", "is_active": True, "is_admin": False}
    assert "password" not in response.text.lower()
    assert "hash" not in response.text.lower()

    with auth_env.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "bob"))
        audit = db.scalar(
            select(AuthAuditEvent).where(AuthAuditEvent.event_type == "admin_create_user")
        )
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert audit is not None
        assert audit.user_id == admin_id
        assert audit.username == "bob"
        assert audit.success is True


def test_duplicate_username_is_rejected_safely(auth_env) -> None:
    seed_user(auth_env, "admin", "administrator-password", admin=True)
    seed_user(auth_env, "bob", "existing-password")
    assert login(auth_env, "admin", "administrator-password").status_code == 200

    response = auth_env.client.post(
        "/api/admin/users",
        json={"username": "Bob", "password": "another-strong-password", "is_admin": False},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Username already exists"}
    assert "integrity" not in response.text.lower()
    assert "sql" not in response.text.lower()

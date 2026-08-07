from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.schemas import UserCreateRequest, UserSummary
from app.auth.security import hash_password
from app.auth.service import normalize_username, record_auth_event
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return user


def _record_duplicate(db: Session, admin: User, username: str) -> None:
    record_auth_event(
        db,
        event_type="admin_create_user",
        username=username,
        user_id=admin.id,
        success=False,
        reason="duplicate_username",
    )
    db.commit()


@router.post("/users", response_model=UserSummary, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> UserSummary:
    username = normalize_username(payload.username)
    if not username:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Username is required")

    if db.scalar(select(User.id).where(User.username == username)) is not None:
        _record_duplicate(db, admin, username)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        is_active=True,
        is_admin=payload.is_admin,
    )
    db.add(user)
    record_auth_event(
        db,
        event_type="admin_create_user",
        username=username,
        user_id=admin.id,
        success=True,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        _record_duplicate(db, admin, username)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from None

    return UserSummary(
        username=user.username,
        is_active=user.is_active,
        is_admin=user.is_admin,
    )

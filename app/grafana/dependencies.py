from hmac import compare_digest

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_auth_context
from app.auth.service import SESSION_COOKIE_NAME
from app.core.config import Settings, get_settings
from app.db.session import get_db


def require_dashboard_access(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    """Allow a signed-in user or the read-only Grafana service token."""

    authorization = request.headers.get("Authorization", "")
    scheme, _, raw_token = authorization.partition(" ")
    expected_token = settings.grafana_api_token

    if (
        expected_token is not None
        and scheme.lower() == "bearer"
        and raw_token
        and compare_digest(raw_token, expected_token.get_secret_value())
    ):
        return

    if request.cookies.get(SESSION_COOKIE_NAME):
        get_auth_context(request=request, db=db, settings=settings)
        return

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

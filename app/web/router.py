from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter(tags=["web"])
_ASSET_DIR = Path(__file__).resolve().parent / "static"
_HTML_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}
_ASSET_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/ai", include_in_schema=False)
def ai_chat_page() -> FileResponse:
    return FileResponse(
        _ASSET_DIR / "index.html",
        media_type="text/html",
        headers=_HTML_HEADERS,
    )


@router.get("/ai/assets/app.css", include_in_schema=False)
def ai_chat_styles() -> FileResponse:
    return FileResponse(
        _ASSET_DIR / "app.css",
        media_type="text/css",
        headers=_ASSET_HEADERS,
    )


@router.get("/ai/assets/app.js", include_in_schema=False)
def ai_chat_script() -> FileResponse:
    return FileResponse(
        _ASSET_DIR / "app.js",
        media_type="application/javascript",
        headers=_ASSET_HEADERS,
    )

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import COOKIE, client_ip, current_user, require, to_dict
from app.core.config import settings
from app.core.errors import StudioError
from app.core.security import create_session_token, hash_password, verify_password
from app.database.session import get_db
from app.limiter import limiter
from app.models import User
from app.services.audit import audit
from app.services.channels import connect_from_oauth

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = ""


def _set_cookie(resp: Response, user: User) -> None:
    resp.set_cookie(COOKIE, create_session_token(user.id, user.role), httponly=True, samesite="lax",
                    secure=settings.environment == "production", max_age=settings.session_hours * 3600, path="/")


@router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    users = db.scalar(select(func.count(User.id))) or 0
    return {"needs_setup": users == 0, "google_oauth_configured": settings.google_oauth_configured}


@router.post("/register")
@limiter.limit("5/minute")
def register(request: Request, body: Credentials, response: Response, db: Session = Depends(get_db)):
    """First account becomes admin. Afterwards only admins can add users (via /auth/users)."""
    if db.scalar(select(func.count(User.id))):
        raise HTTPException(403, "Setup already completed — ask an admin to create your account")
    user = User(email=body.email.lower(), name=body.name, password_hash=hash_password(body.password), role="admin")
    db.add(user)
    db.flush()
    audit(db, "user.register", user_id=user.id, ip=client_ip(request))
    db.commit()
    _set_cookie(response, user)
    return to_dict(user)


@router.post("/users")
def create_user(body: Credentials, role: str = "editor", admin: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if role not in ("admin", "editor", "viewer"):
        raise HTTPException(400, "invalid role")
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "email already registered")
    user = User(email=body.email.lower(), name=body.name, password_hash=hash_password(body.password), role=role,
                onboarding_completed=True)
    db.add(user)
    audit(db, "user.create", user_id=admin.id, entity_type="user", entity_id=body.email, detail={"role": role})
    db.commit()
    return to_dict(user)


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, body: Credentials, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash) or not user.is_active:
        audit(db, "user.login_failed", detail={"email": body.email}, ip=client_ip(request))
        db.commit()
        raise HTTPException(401, "Invalid email or password")
    audit(db, "user.login", user_id=user.id, ip=client_ip(request))
    db.commit()
    _set_cookie(response, user)
    return to_dict(user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return to_dict(user)


@router.post("/google")
def google_auth_url(user: User = Depends(require("admin"))):
    """Start Google OAuth to connect a YouTube channel. Returns the consent URL to open."""
    from app.integrations.youtube.client import build_auth_url, scopes

    try:
        return {"auth_url": build_auth_url(user.id), "scopes": scopes(), "redirect_uri": settings.oauth_redirect_uri}
    except StudioError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/youtube/callback")
def youtube_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                     db: Session = Depends(get_db)):
    base = settings.public_base_url.rstrip("/")
    if error or not code or not state:
        return RedirectResponse(f"{base}/channels?oauth_error={error or 'missing_code'}")
    try:
        from app.integrations.youtube.client import verify_state

        uid = verify_state(state)
        channels = connect_from_oauth(db, uid, code)
        audit(db, "channel.oauth_connect", user_id=uid, detail={"channels": [c.youtube_channel_id for c in channels]},
              ip=client_ip(request))
        db.commit()
    except StudioError as e:
        log.warning("oauth callback failed: %s", e)
        return RedirectResponse(f"{base}/channels?oauth_error={str(e)[:120]}")
    if not channels:
        return RedirectResponse(f"{base}/channels?oauth_error=no_channel_on_account")
    user = db.get(User, uid)
    target = "channels" if user and user.onboarding_completed else "onboarding"
    return RedirectResponse(f"{base}/{target}?connected={len(channels)}")

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.security import decode_session_token
from app.database.session import get_db
from app.models import User

ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2}
SECRET_FIELDS = {"password_hash", "oauth_token_enc", "api_key_enc", "embedding", "upload_session_url"}
COOKIE = "studio_session"


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    auth = request.headers.get("Authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:]
    payload = decode_session_token(token) if token else None
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    return user


def require(role: str) -> Callable[..., User]:
    def dep(user: User = Depends(current_user)) -> User:
        if ROLE_RANK.get(user.role, -1) < ROLE_RANK[role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {role} role")
        return user

    return dep


def to_dict(obj: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    if obj is None:
        return None  # type: ignore[return-value]
    out: dict[str, Any] = {}
    for col in sa_inspect(obj).mapper.column_attrs:
        k = col.key
        if k in SECRET_FIELDS or (exclude and k in exclude):
            continue
        v = getattr(obj, k)
        if isinstance(v, (datetime, date)):
            v = v.isoformat()
        out[k] = v
    return out


def get_or_404(db: Session, model, id_: int):
    obj = db.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {id_} not found")
    return obj


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require, to_dict
from app.database.session import get_db
from app.integrations.registry import CATALOG
from app.models import AIProvider, AutomationSettings, Channel, User
from app.services.audit import audit
from app.services.catalog import BUDGET_MODES, DEFAULT_TREND_WEIGHTS
from app.services.settings import ensure_automation

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("")
def get_state(user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    return {"completed": user.onboarding_completed, "state": user.onboarding_state or {},
            "channels": db.scalars(select(Channel.id)).all()}


class StatePatch(BaseModel):
    step: int
    data: dict = {}


@router.patch("")
def save_state(body: StatePatch, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    state = dict(user.onboarding_state or {})
    state["step"] = body.step
    state.update(body.data)
    user.onboarding_state = state
    db.commit()
    return {"state": state}


class Complete(BaseModel):
    budget_mode: str = "free"
    monthly_budget_usd: float = 0
    activate: bool = False
    confirm: bool = False
    providers: dict[str, str] = {}  # kind -> provider name


@router.get("/summary")
def summary(user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    from app.api.routes.channels import channel_out

    auto = ensure_automation(db, user)
    defaults = {p.kind: {"name": p.name, "display": p.display_name, "health": p.health_status}
                for p in db.scalars(select(AIProvider).where(AIProvider.is_default.is_(True))).all()}
    return {"channels": [channel_out(c) for c in db.scalars(select(Channel)).all()], "automation": to_dict(auto),
            "providers": defaults}


@router.post("/complete")
def complete(body: Complete, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if not body.confirm:
        raise HTTPException(400, "Please review the summary and confirm before activating")
    if body.budget_mode not in BUDGET_MODES:
        raise HTTPException(400, "invalid budget mode")
    channels = db.scalars(select(Channel).where(Channel.status == "connected")).all()
    if not channels:
        raise HTTPException(400, "Connect at least one channel (or create a sandbox channel) first")
    for ch in channels:
        if not ch.niches:
            raise HTTPException(400, f"Channel '{ch.title}' has no content niche selected")
    auto = ensure_automation(db, user)
    auto.budget_mode = body.budget_mode
    auto.monthly_budget_usd = max(0.0, body.monthly_budget_usd)
    auto.trend_weights = auto.trend_weights or DEFAULT_TREND_WEIGHTS
    valid = {(c["kind"], c["name"]) for c in CATALOG}
    for kind, name in body.providers.items():
        if (kind, name) not in valid:
            raise HTTPException(400, f"unknown provider {kind}/{name}")
        for p in db.scalars(select(AIProvider).where(AIProvider.kind == kind)).all():
            p.is_default = p.name == name
            if p.name == name:
                p.enabled = True
    auto.is_running = body.activate
    auto.paused_reason = None
    if body.activate:
        for ch in channels:
            ch.automation_enabled = True
    user.onboarding_completed = True
    audit(db, "onboarding.complete", user_id=user.id, detail=body.model_dump())
    db.commit()
    return {"ok": True, "automation": to_dict(auto), "completed_at": datetime.now(timezone.utc).isoformat()}

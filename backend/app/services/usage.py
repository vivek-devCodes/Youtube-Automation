"""API cost + quota tracking and the monthly budget guard.

Every paid call goes through `guard()` *before* it is made (with an estimate) and
`record()` after it completes (with actual usage when the provider reports it)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BudgetExceeded, QuotaExceeded
from app.models import ApiUsage, AutomationSettings


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def day_start_pacific(now: datetime | None = None) -> datetime:
    """YouTube quota resets at midnight Pacific Time (approximated as UTC-8)."""
    from datetime import timedelta

    now = now or datetime.now(timezone.utc)
    pt = now - timedelta(hours=8)
    return pt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=8)


def month_to_date_spend(db: Session) -> float:
    total = db.scalar(select(func.coalesce(func.sum(ApiUsage.cost_usd), 0.0)).where(ApiUsage.created_at >= month_start()))
    return float(total or 0.0)


def youtube_quota_used_today(db: Session) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(ApiUsage.units), 0)).where(
            ApiUsage.kind == "youtube_quota", ApiUsage.created_at >= day_start_pacific()
        )
    )
    return int(total or 0)


def get_automation(db: Session) -> AutomationSettings | None:
    return db.scalar(select(AutomationSettings).order_by(AutomationSettings.id).limit(1))


def guard(db: Session, estimated_cost: float, what: str) -> None:
    """Raise BudgetExceeded if this paid operation would push spend past the monthly limit."""
    if estimated_cost <= 0:
        return
    auto = get_automation(db)
    limit = auto.monthly_budget_usd if auto else 0.0
    if auto and auto.budget_mode == "free":
        raise BudgetExceeded(f"{what}: paid providers are disabled in Free/open-source mode")
    spent = month_to_date_spend(db)
    if spent + estimated_cost > limit:
        raise BudgetExceeded(
            f"{what}: estimated ${estimated_cost:.4f} would exceed the monthly budget "
            f"(${spent:.2f} of ${limit:.2f} used)"
        )


def record(
    db: Session,
    *,
    provider: str,
    kind: str,
    model: str = "",
    task: str = "",
    units: float = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    estimated: bool = True,
    channel_id: int | None = None,
    video_id: int | None = None,
    workflow_run_id: int | None = None,
) -> ApiUsage:
    row = ApiUsage(
        provider=provider,
        kind=kind,
        model=model,
        task=task,
        units=units,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        estimated=estimated,
        channel_id=channel_id,
        video_id=video_id,
        workflow_run_id=workflow_run_id,
    )
    db.add(row)
    db.flush()
    return row


def charge_youtube_quota(db: Session, units: int, operation: str, daily_limit: int, channel_id: int | None = None) -> None:
    used = youtube_quota_used_today(db)
    if used + units > daily_limit:
        raise QuotaExceeded(f"YouTube API quota would be exceeded by {operation} ({used}+{units} > {daily_limit})")
    record(db, provider="youtube", kind="youtube_quota", task=operation, units=units, estimated=False, channel_id=channel_id)

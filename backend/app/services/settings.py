from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AutomationSettings, User
from app.services.catalog import DEFAULT_TREND_WEIGHTS


def ensure_automation(db: Session, user: User | None = None) -> AutomationSettings:
    auto = db.scalar(select(AutomationSettings).order_by(AutomationSettings.id).limit(1))
    if auto is None:
        uid = user.id if user else db.scalar(select(User.id).order_by(User.id).limit(1))
        auto = AutomationSettings(user_id=uid, trend_weights=dict(DEFAULT_TREND_WEIGHTS),
                                  notification_prefs={"in_app": True, "critical_only": False})
        db.add(auto)
        db.commit()
    return auto

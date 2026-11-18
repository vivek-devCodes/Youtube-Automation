from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, Notification

log = logging.getLogger(__name__)


def audit(db: Session, action: str, *, user_id: int | None = None, entity_type: str = "", entity_id: Any = "",
          detail: dict | None = None, ip: str | None = None) -> None:
    db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=str(entity_id),
                    detail=detail or {}, ip=ip))


def notify(db: Session, title: str, message: str = "", *, level: str = "info", link: str | None = None,
           user_id: int | None = None) -> None:
    db.add(Notification(user_id=user_id, level=level, title=title, message=message, link=link))
    (log.warning if level != "info" else log.info)("notification: %s — %s", title, message)

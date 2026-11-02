"""Application time. A demo offset lets the time-skip scene move days forward."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .db import Setting


def _offset_days(db: Session) -> int:
    row = db.get(Setting, "clock_offset_days")
    return int(row.value) if row else 0


def now(db: Session) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=_offset_days(db))


def advance(db: Session, days: int) -> int:
    total = _offset_days(db) + days
    db.merge(Setting(key="clock_offset_days", value=total))
    db.commit()
    return total

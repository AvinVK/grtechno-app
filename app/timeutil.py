from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from flask import current_app


def _tz() -> ZoneInfo:
    return ZoneInfo(current_app.config["TIMEZONE"])


def today_local() -> date:
    return datetime.now(_tz()).date()


def to_local(dt: datetime) -> datetime:
    """Convert a naive-UTC datetime from the database to local time."""
    return dt.replace(tzinfo=timezone.utc).astimezone(_tz())


def months_back(today: date, n: int) -> date:
    """The first of the month n months before today's month."""
    y, m = today.year, today.month - n
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def from_local(day: date, at: time) -> datetime:
    """A local calendar day and clock time as a naive-UTC datetime, the way the database stores them (the reverse of to_local)."""
    return datetime.combine(day, at).replace(tzinfo=_tz()).astimezone(timezone.utc).replace(tzinfo=None)

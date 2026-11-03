"""B-18: Centralised timezone-aware UTC helper.

All code that needs the current UTC time should import and call ``utcnow()``
from this module rather than ``datetime.utcnow()`` (which returns a naïve
datetime) or ``datetime.now()`` (which uses local time).
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Return *dt* with tzinfo=UTC.  If already tz-aware, convert; if naïve,
    assume UTC and attach the timezone without conversion.
    """
    if dt is None:
        return utcnow()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

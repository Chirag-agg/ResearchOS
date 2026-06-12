from datetime import datetime, timezone


def get_utc_now() -> datetime:
    """
    Returns the current UTC time as a timezone-naive datetime object.
    SQLite doesn't natively handle timezone offsets cleanly; storing naive UTC datetime
    objects is the standard best practice for databases.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

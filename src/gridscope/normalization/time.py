from datetime import UTC, datetime, timedelta

from gridscope.errors import InvalidQuery

DateInput = str | datetime
RESOLUTIONS = {
    "PT15M": timedelta(minutes=15),
    "PT30M": timedelta(minutes=30),
    "PT60M": timedelta(hours=1),
    "PT1H": timedelta(hours=1),
}


def utc(value: DateInput) -> datetime:
    """Date-only strings mean UTC midnight; datetimes must carry an offset."""
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if len(value) == 10:
                parsed = parsed.replace(tzinfo=UTC)
        else:
            parsed = value
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        # Reject imaginary local times supplied as ZoneInfo datetime objects.
        result = parsed.astimezone(UTC)
        if result.astimezone(parsed.tzinfo).replace(tzinfo=None) != parsed.replace(tzinfo=None):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise InvalidQuery(
            "Use YYYY-MM-DD (UTC) or an ISO datetime with a valid UTC offset."
        ) from None


def date_range(start: DateInput, end: DateInput) -> tuple[datetime, datetime]:
    a, b = utc(start), utc(end)
    if a >= b or b - a > timedelta(days=366):
        raise InvalidQuery("Require start < end and a range of at most 366 days.")
    if any(d.second or d.microsecond for d in (a, b)):
        raise InvalidQuery("Query boundaries must use whole minutes.")
    return a, b


def resolution_delta(resolution: str) -> timedelta:
    try:
        return RESOLUTIONS[resolution]
    except KeyError:
        raise InvalidQuery(f"Unsupported resolution: {resolution}.") from None

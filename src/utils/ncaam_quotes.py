"""Executable NCAAM prices used by the live model and historical replay."""
from datetime import datetime, timedelta, timezone


def recent_retail_quote(quote, as_of):
    book = str(quote.get('book') or '').strip().lower()
    if book in ('', 'open', 'action_open', 'consensus', 'unknown') or book.startswith('action_book_'):
        return False
    try:
        stamp = quote['captured_at']
        if not isinstance(stamp, datetime):
            stamp = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return timedelta(0) <= as_of - stamp <= timedelta(minutes=90)
    except (KeyError, AttributeError, TypeError, ValueError):
        return False

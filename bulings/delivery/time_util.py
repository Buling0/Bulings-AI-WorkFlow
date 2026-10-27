from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable


def format_iso8601(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat(timespec="seconds")

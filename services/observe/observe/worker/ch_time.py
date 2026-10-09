"""ClickHouse datetime strings to unix nanoseconds."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def clickhouse_datetime_to_nano(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(text[:26], fmt).replace(tzinfo=UTC)
            sec = int(dt.timestamp())
            micro = dt.microsecond
            return sec * 1_000_000_000 + micro * 1000
        except ValueError:
            continue
    return 0

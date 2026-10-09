from __future__ import annotations

from observe.worker.ch_time import clickhouse_datetime_to_nano


def test_clickhouse_datetime_to_nano_realistic() -> None:
    nano = clickhouse_datetime_to_nano("2026-03-15 10:30:00.500000")
    assert nano > 1_700_000_000_000_000_000
    assert nano % 1_000_000_000 == 500_000_000

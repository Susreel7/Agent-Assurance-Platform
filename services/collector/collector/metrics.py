"""In-process counters for health and Prometheus-style export."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


@dataclass
class CollectorMetrics:
    ingest_accepted: int = 0
    ingest_rejected_envelope: int = 0
    ingest_idempotent_replay: int = 0
    ingest_quota_denied: int = 0
    sampled_spans_dropped: int = 0
    forward_success: int = 0
    forward_failure: int = 0
    forward_poisoned: int = 0
    spool_pending: int = 0
    spool_quarantine: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def inc(self, name: str, delta: int = 1) -> None:
        with self._lock:
            current = getattr(self, name)
            setattr(self, name, current + delta)

    def set_gauge(self, name: str, value: int) -> None:
        with self._lock:
            setattr(self, name, value)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "ingest_accepted": self.ingest_accepted,
                "ingest_rejected_envelope": self.ingest_rejected_envelope,
                "ingest_idempotent_replay": self.ingest_idempotent_replay,
                "ingest_quota_denied": self.ingest_quota_denied,
                "sampled_spans_dropped": self.sampled_spans_dropped,
                "forward_success": self.forward_success,
                "forward_failure": self.forward_failure,
                "forward_poisoned": self.forward_poisoned,
                "spool_pending": self.spool_pending,
                "spool_quarantine": self.spool_quarantine,
            }

    def prometheus_text(self) -> str:
        snap = self.snapshot()
        lines = []
        for key, value in snap.items():
            lines.append(f"collector_{key} {value}")
        return "\n".join(lines) + "\n"

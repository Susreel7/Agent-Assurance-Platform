"""Durable on-disk spool with atomic writes and crash recovery."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from collector.errors import SpoolQuotaError
from collector.otlp import digest_bytes


@dataclass(slots=True)
class SpoolMetadata:
    envelope_digest: str
    content_type: str
    content_encoding: str
    traceparent: str | None
    tracestate: str | None
    span_count: int
    rejected_span_count: int
    created_at_unix: float
    attempt_count: int = 0
    signal_type: str = "traces"
    event_count: int = 0
    rejected_event_count: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> SpoolMetadata:
        data = json.loads(raw)
        data.setdefault("signal_type", "traces")
        data.setdefault("event_count", 0)
        data.setdefault("rejected_event_count", 0)
        return cls(**data)


class SpoolStore:
    def __init__(self, root: Path, *, disk_quota_bytes: int) -> None:
        self.root = root
        self.disk_quota_bytes = disk_quota_bytes
        self.pending = root / "pending"
        self.inflight = root / "inflight"
        self.quarantine = root / "quarantine"
        for path in (self.pending, self.inflight, self.quarantine):
            path.mkdir(parents=True, exist_ok=True)

    def recover_after_crash(self) -> int:
        """Move orphaned inflight entries back to pending."""
        moved = 0
        for meta_path in sorted(self.inflight.glob("*.meta.json")):
            digest = meta_path.stem.replace(".meta", "")
            self._move_pair(digest, self.inflight, self.pending)
            moved += 1
        for tmp in self.root.rglob("*.tmp"):
            tmp.unlink(missing_ok=True)
        return moved

    def _pair_paths(self, directory: Path, digest: str) -> tuple[Path, Path]:
        safe = digest.replace(":", "_")
        return directory / f"{safe}.bin", directory / f"{safe}.meta.json"

    def _move_pair(self, digest: str, src: Path, dst: Path) -> None:
        safe = digest.replace(":", "_")
        for suffix in (".bin", ".meta.json"):
            path = src / f"{safe}{suffix}"
            if path.exists():
                path.replace(dst / f"{safe}{suffix}")

    def disk_usage_bytes(self) -> int:
        total = 0
        for sub in (self.pending, self.inflight, self.quarantine):
            for path in sub.rglob("*"):
                if path.is_file():
                    total += path.stat().st_size
        return total

    def _fsync_dir(self, directory: Path) -> None:
        try:
            flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                flags |= os.O_DIRECTORY
            fd = os.open(str(directory), flags)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _atomic_write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
        self._fsync_dir(path.parent)

    def put_if_absent(
        self,
        envelope: bytes,
        meta: SpoolMetadata,
    ) -> tuple[bool, str]:
        """Returns (created, digest). Idempotent when digest already spooled."""
        digest = digest_bytes(envelope)
        meta.envelope_digest = digest
        if self._has_digest(digest):
            return False, digest
        pending_bin, pending_meta = self._pair_paths(self.pending, digest)

        projected = self.disk_usage_bytes() + len(envelope) + len(meta.to_json())
        if projected > self.disk_quota_bytes:
            raise SpoolQuotaError("spool disk quota exceeded")

        self._atomic_write(pending_bin, envelope)
        self._atomic_write(pending_meta, meta.to_json().encode("utf-8"))
        return True, digest

    def list_pending_oldest_first(self) -> list[str]:
        metas: list[tuple[float, str]] = []
        for meta_path in self.pending.glob("*.meta.json"):
            meta = SpoolMetadata.from_json(meta_path.read_text(encoding="utf-8"))
            metas.append((meta_path.stat().st_mtime, meta.envelope_digest))
        metas.sort(key=lambda item: item[0])
        return [digest for _, digest in metas]

    def _digest_filename(self, digest: str) -> str:
        return digest.replace(":", "_")

    def _has_digest(self, digest: str) -> bool:
        safe = self._digest_filename(digest)
        for sub in (self.pending, self.inflight, self.quarantine):
            if (sub / f"{safe}.bin").exists():
                return True
        return False

    def claim(self, digest: str) -> SpoolMetadata | None:
        safe = self._digest_filename(digest)
        pending_bin = self.pending / f"{safe}.bin"
        pending_meta = self.pending / f"{safe}.meta.json"
        if not pending_bin.exists() or not pending_meta.exists():
            return None
        inflight_bin = self.inflight / f"{safe}.bin"
        inflight_meta = self.inflight / f"{safe}.meta.json"
        try:
            pending_bin.replace(inflight_bin)
            pending_meta.replace(inflight_meta)
        except OSError:
            return None
        meta = SpoolMetadata.from_json(inflight_meta.read_text(encoding="utf-8"))
        return meta

    def release_success(self, digest: str) -> None:
        safe = self._digest_filename(digest)
        for suffix in (".bin", ".meta.json"):
            path = self.inflight / f"{safe}{suffix}"
            path.unlink(missing_ok=True)

    def release_failure(self, digest: str, *, poison: bool) -> SpoolMetadata:
        safe = self._digest_filename(digest)
        inflight_bin = self.inflight / f"{safe}.bin"
        inflight_meta = self.inflight / f"{safe}.meta.json"
        meta = SpoolMetadata.from_json(inflight_meta.read_text(encoding="utf-8"))
        meta.attempt_count += 1
        target = self.quarantine if poison else self.pending
        self._atomic_write(inflight_meta, meta.to_json().encode("utf-8"))
        inflight_bin.replace(target / f"{safe}.bin")
        inflight_meta.replace(target / f"{safe}.meta.json")
        return meta

    def load_inflight(self, digest: str) -> tuple[bytes, SpoolMetadata]:
        safe = self._digest_filename(digest)
        inflight_bin = self.inflight / f"{safe}.bin"
        inflight_meta = self.inflight / f"{safe}.meta.json"
        return inflight_bin.read_bytes(), SpoolMetadata.from_json(
            inflight_meta.read_text(encoding="utf-8")
        )

    def pending_count(self) -> int:
        return len(list(self.pending.glob("*.meta.json")))

    def quarantine_count(self) -> int:
        return len(list(self.quarantine.glob("*.meta.json")))

    @staticmethod
    def now() -> float:
        return time.time()

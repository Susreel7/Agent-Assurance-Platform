"""Object storage for OTLP envelopes and encrypted payload blobs."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    digest: str
    size: int
    uri: str
    encryption: str | None = None


class ObjectStore(ABC):
    @staticmethod
    def digest(data: bytes) -> str:
        return "sha256:" + hashlib.sha256(data).hexdigest()

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def presign(self, key: str, expires: timedelta) -> str: ...


def tenant_envelope_key(org_id: UUID, project_id: UUID, digest: str) -> str:
    hex_part = digest.removeprefix("sha256:")
    return f"{org_id}/{project_id}/envelopes/{hex_part[:2]}/{hex_part}.bin"


def tenant_payload_key(org_id: UUID, project_id: UUID, digest: str) -> str:
    hex_part = digest.removeprefix("sha256:")
    return f"{org_id}/{project_id}/payloads/{hex_part[:2]}/{hex_part}.enc"


class LocalObjectStore(ObjectStore):
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if ".." in Path(key).parts or Path(key).is_absolute():
            raise ValueError(f"unsafe object key: {key!r}")
        return self._root / key

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(key, self.digest(data), len(data), f"file://{path}")

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def presign(self, key: str, expires: timedelta) -> str:
        return f"/v1/observe/payloads/{key}"

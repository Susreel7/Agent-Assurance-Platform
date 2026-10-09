"""Object storage abstraction for encrypted dataset attachments."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredObject:
    storage_ref: str
    size_bytes: int


class ObjectStoreProvider(ABC):
    @abstractmethod
    def put(
        self,
        *,
        org_id: str,
        project_id: str,
        purpose: str,
        object_id: str,
        data: bytes,
    ) -> StoredObject: ...

    @abstractmethod
    def get(self, storage_ref: str) -> bytes: ...

    @abstractmethod
    def delete(self, storage_ref: str) -> None: ...

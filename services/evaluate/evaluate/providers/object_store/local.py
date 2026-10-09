"""Local filesystem object store."""

from __future__ import annotations

from pathlib import Path

from evaluate.errors import NotFoundError
from evaluate.providers.object_store.base import ObjectStoreProvider, StoredObject


class LocalObjectStore(ObjectStoreProvider):
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def _path_for_ref(self, storage_ref: str) -> Path:
        if not storage_ref.startswith("local:"):
            msg = "invalid local storage ref"
            raise ValueError(msg)
        rel = storage_ref.removeprefix("local:")
        path = self._root / rel
        resolved = path.resolve()
        root_resolved = self._root.resolve()
        if not str(resolved).startswith(str(root_resolved)):
            raise ValueError("object path escapes store root")
        return path

    def put(
        self,
        *,
        org_id: str,
        project_id: str,
        purpose: str,
        object_id: str,
        data: bytes,
    ) -> StoredObject:
        rel = Path(org_id) / project_id / purpose / object_id
        path = self._root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(storage_ref=f"local:{rel.as_posix()}", size_bytes=len(data))

    def get(self, storage_ref: str) -> bytes:
        path = self._path_for_ref(storage_ref)
        if not path.is_file():
            raise NotFoundError("object not found")
        return path.read_bytes()

    def delete(self, storage_ref: str) -> None:
        path = self._path_for_ref(storage_ref)
        if path.is_file():
            path.unlink()

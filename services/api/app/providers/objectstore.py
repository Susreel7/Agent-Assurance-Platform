"""Object storage abstraction.

Accreditation packs, release artifacts and offline bundles are written here. In our cloud
this is S3. In BYOC it is whatever the customer's cloud provides, in their account, in
their region. In air-gapped installs it is a mounted volume or an on-premise
S3-compatible endpoint.

Cloud SDKs are imported lazily so that a BYOC install on Azure does not need the AWS
libraries present, and an air-gapped install needs neither.
"""

from __future__ import annotations

import hashlib
import shutil
from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path

from app.config import ObjectStoreProvider, Settings, get_settings


class StoredObject:
    __slots__ = ("digest", "key", "size", "uri")

    def __init__(self, key: str, digest: str, size: int, uri: str) -> None:
        self.key = key
        self.digest = digest
        self.size = size
        self.uri = uri


class ObjectStore(ABC):
    """Minimal surface. Resist widening it — every method has to work on four backends."""

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def presign(self, key: str, expires: timedelta) -> str:
        """Time-limited read URL. Used by the trust portal so packs are served without
        proxying large files through the API process."""

    @staticmethod
    def digest(data: bytes) -> str:
        return "sha256:" + hashlib.sha256(data).hexdigest()


class LocalObjectStore(ObjectStore):
    """Filesystem backed. Development, and air-gapped installs with a mounted volume."""

    def __init__(self, root: Path, prefix: str = "") -> None:
        self._root = root / prefix if prefix else root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Refuse traversal outright rather than sanitising, so a malformed key is a
        # visible error instead of a silent write to an unexpected location.
        if ".." in Path(key).parts or Path(key).is_absolute():
            raise ValueError(f"unsafe object key: {key!r}")
        return self._root / key

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        shutil.move(str(tmp), str(path))  # atomic within a filesystem
        return StoredObject(key, self.digest(data), len(data), f"file://{path}")

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def presign(self, key: str, expires: timedelta) -> str:
        # No signing possible on a filesystem. The API serves these through an
        # authenticated endpoint instead.
        return f"/v1/artifacts/{key}"


class S3ObjectStore(ObjectStore):
    """AWS S3, or any S3-compatible endpoint (MinIO, on-premise object storage).

    Credentials come from the ambient environment — instance role, IRSA, or the
    customer's own configuration. We never accept access keys through our config.
    """

    def __init__(self, bucket: str, prefix: str = "", endpoint: str | None = None) -> None:
        import boto3  # lazy: not installed in Azure or GCP BYOC images

        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._client = boto3.client("s3", endpoint_url=endpoint)

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._key(key),
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
        return StoredObject(
            key, self.digest(data), len(data), f"s3://{self._bucket}/{self._key(key)}"
        )

    def get(self, key: str) -> bytes:
        obj = self._client.get_object(Bucket=self._bucket, Key=self._key(key))
        return bytes(obj["Body"].read())

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=self._key(key))
            return True
        except ClientError:
            return False

    def presign(self, key: str, expires: timedelta) -> str:
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": self._key(key)},
                ExpiresIn=int(expires.total_seconds()),
            )
        )


class AzureBlobObjectStore(ObjectStore):
    def __init__(self, container: str, prefix: str = "", account_url: str | None = None) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        if not account_url:
            raise ValueError("azblob requires AAP_OBJECT_STORE_ENDPOINT (the account URL)")
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._container = BlobServiceClient(
            account_url, credential=DefaultAzureCredential()
        ).get_container_client(container)

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        from azure.storage.blob import ContentSettings

        self._container.upload_blob(
            self._key(key),
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )
        return StoredObject(key, self.digest(data), len(data), self._key(key))

    def get(self, key: str) -> bytes:
        return bytes(self._container.download_blob(self._key(key)).readall())

    def exists(self, key: str) -> bool:
        return bool(self._container.get_blob_client(self._key(key)).exists())

    def presign(self, key: str, expires: timedelta) -> str:
        # User-delegation SAS requires a credential round trip; the caller wraps this.
        raise NotImplementedError("configure a user-delegation SAS policy for this container")


class GcsObjectStore(ObjectStore):
    def __init__(self, bucket: str, prefix: str = "") -> None:
        from google.cloud import storage

        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._bucket = storage.Client().bucket(bucket)

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        blob = self._bucket.blob(self._key(key))
        blob.upload_from_string(data, content_type=content_type)
        return StoredObject(key, self.digest(data), len(data), f"gs://{self._bucket.name}/{key}")

    def get(self, key: str) -> bytes:
        return bytes(self._bucket.blob(self._key(key)).download_as_bytes())

    def exists(self, key: str) -> bool:
        return bool(self._bucket.blob(self._key(key)).exists())

    def presign(self, key: str, expires: timedelta) -> str:
        return str(self._bucket.blob(self._key(key)).generate_signed_url(expiration=expires))


def build_object_store(settings: Settings | None = None) -> ObjectStore:
    s = settings or get_settings()
    match s.object_store:
        case ObjectStoreProvider.LOCAL:
            return LocalObjectStore(s.object_store_local_path, s.object_store_prefix)
        case ObjectStoreProvider.S3:
            return S3ObjectStore(
                s.object_store_bucket, s.object_store_prefix, s.object_store_endpoint
            )
        case ObjectStoreProvider.AZURE_BLOB:
            return AzureBlobObjectStore(
                s.object_store_bucket, s.object_store_prefix, s.object_store_endpoint
            )
        case ObjectStoreProvider.GCS:
            return GcsObjectStore(s.object_store_bucket, s.object_store_prefix)

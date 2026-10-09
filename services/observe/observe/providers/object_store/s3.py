"""AWS S3 (or S3-compatible) object store."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from observe.providers.object_store.base import ObjectStore, StoredObject


class S3ObjectStore(ObjectStore):
    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        endpoint: str | None = None,
        region: str | None = None,
        sse: str = "AES256",
        kms_key_id: str | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("OBSERVE_OBJECT_STORE_BUCKET is required for S3")
        import boto3

        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._sse = sse
        self._kms_key_id = kms_key_id
        self._client: Any = boto3.client("s3", endpoint_url=endpoint, region_name=region)

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        extra: dict[str, Any] = {"ContentType": content_type}
        if self._kms_key_id:
            extra["ServerSideEncryption"] = "aws:kms"
            extra["SSEKMSKeyId"] = self._kms_key_id
        else:
            extra["ServerSideEncryption"] = self._sse
        self._client.put_object(Bucket=self._bucket, Key=self._key(key), Body=data, **extra)
        uri = f"s3://{self._bucket}/{self._key(key)}"
        return StoredObject(
            key=key,
            digest=self.digest(data),
            size=len(data),
            uri=uri,
            encryption=f"s3:{extra.get('ServerSideEncryption', 'none')}",
        )

    def get(self, key: str) -> bytes:
        obj = self._client.get_object(Bucket=self._bucket, Key=self._key(key))
        return bytes(obj["Body"].read())

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=self._key(key))
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=self._key(key))

    def presign(self, key: str, expires: timedelta) -> str:
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": self._key(key)},
                ExpiresIn=int(expires.total_seconds()),
            )
        )

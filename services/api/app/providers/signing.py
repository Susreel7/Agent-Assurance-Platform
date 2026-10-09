"""Signing abstraction for accreditation packs, release attestations and evidence anchors.

ECDSA over P-256 throughout, matching the algorithm A2A uses for signed AgentCards.
Consistency with the standard we extend is worth more than any marginal preference.

The BYOC trust argument lives in this file. When the signing key is held in the
customer's own KMS, we are *structurally* incapable of signing on their behalf — which is
a materially stronger statement than a policy commitment not to. Say so in security
reviews, and point here.
"""

from __future__ import annotations

import base64
import hashlib
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import Settings, SigningProvider, get_settings


class Signer(ABC):
    @abstractmethod
    def sign(self, payload: bytes) -> str:
        """Return a base64url-encoded signature over ``payload``."""

    @abstractmethod
    def verify(self, payload: bytes, signature: str) -> bool: ...

    @abstractmethod
    def public_key_pem(self) -> str:
        """Published so an auditor can verify a pack without contacting us at all."""

    @property
    @abstractmethod
    def key_id(self) -> str: ...

    @property
    def algorithm(self) -> str:
        return "ES256"

    @staticmethod
    def digest(payload: bytes) -> bytes:
        return hashlib.sha256(payload).digest()


class LocalSigner(Signer):
    """PEM on disk. Development, and air-gapped installs where no KMS is reachable."""

    def __init__(self, key_path: Path) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey

        self._key_path = key_path
        loaded = serialization.load_pem_private_key(key_path.read_bytes(), password=None)

        # ES256 everywhere, so anything else is a misconfiguration. Rejecting it at load
        # time rather than at first use matters: the first use is usually halfway through
        # rendering an accreditation pack, where the failure is far harder to read.
        if not isinstance(loaded, EllipticCurvePrivateKey):
            raise TypeError(
                f"{key_path} holds a {type(loaded).__name__}; "
                "ES256 signing requires an EC P-256 private key"
            )
        self._private = loaded
        self._kid = (
            "local:"
            + hashlib.sha256(
                self._private.public_key().public_bytes(
                    encoding=serialization.Encoding.DER,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            ).hexdigest()[:16]
        )

    def sign(self, payload: bytes) -> str:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
        from cryptography.hazmat.primitives.hashes import SHA256

        sig = self._private.sign(self.digest(payload), ec.ECDSA(Prehashed(SHA256())))
        return base64.urlsafe_b64encode(sig).decode().rstrip("=")

    def verify(self, payload: bytes, signature: str) -> bool:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
        from cryptography.hazmat.primitives.hashes import SHA256

        pad = "=" * (-len(signature) % 4)
        try:
            self._private.public_key().verify(
                base64.urlsafe_b64decode(signature + pad),
                self.digest(payload),
                ec.ECDSA(Prehashed(SHA256())),
            )
            return True
        except InvalidSignature:
            return False

    def public_key_pem(self) -> str:
        from cryptography.hazmat.primitives import serialization

        return (
            self._private.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )

    @property
    def key_id(self) -> str:
        return self._kid


class AwsKmsSigner(Signer):
    """The customer's own KMS key, in their account, under their key policy.

    They can revoke our access at any time, and CloudTrail records every signing
    operation we perform. Both properties are worth stating explicitly in a review.
    """

    def __init__(self, key_ref: str, region: str | None = None) -> None:
        import boto3

        self._key_ref = key_ref
        self._client = boto3.client("kms", region_name=region)

    def sign(self, payload: bytes) -> str:
        resp = self._client.sign(
            KeyId=self._key_ref,
            Message=self.digest(payload),
            MessageType="DIGEST",
            SigningAlgorithm="ECDSA_SHA_256",
        )
        return base64.urlsafe_b64encode(resp["Signature"]).decode().rstrip("=")

    def verify(self, payload: bytes, signature: str) -> bool:
        pad = "=" * (-len(signature) % 4)
        resp = self._client.verify(
            KeyId=self._key_ref,
            Message=self.digest(payload),
            MessageType="DIGEST",
            Signature=base64.urlsafe_b64decode(signature + pad),
            SigningAlgorithm="ECDSA_SHA_256",
        )
        return bool(resp["SignatureValid"])

    def public_key_pem(self) -> str:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.serialization import load_der_public_key

        der = self._client.get_public_key(KeyId=self._key_ref)["PublicKey"]
        return (
            load_der_public_key(der)
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )

    @property
    def key_id(self) -> str:
        return self._key_ref


class AzureKeyVaultSigner(Signer):
    def __init__(self, key_ref: str) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.keys.crypto import CryptographyClient

        self._key_ref = key_ref
        self._client = CryptographyClient(key_ref, credential=DefaultAzureCredential())

    def sign(self, payload: bytes) -> str:
        from azure.keyvault.keys.crypto import SignatureAlgorithm

        result = self._client.sign(SignatureAlgorithm.es256, self.digest(payload))
        return base64.urlsafe_b64encode(result.signature).decode().rstrip("=")

    def verify(self, payload: bytes, signature: str) -> bool:
        from azure.keyvault.keys.crypto import SignatureAlgorithm

        pad = "=" * (-len(signature) % 4)
        return bool(
            self._client.verify(
                SignatureAlgorithm.es256,
                self.digest(payload),
                base64.urlsafe_b64decode(signature + pad),
            ).is_valid
        )

    def public_key_pem(self) -> str:
        raise NotImplementedError("fetch via the Key Vault keys client and export as PEM")

    @property
    def key_id(self) -> str:
        return self._key_ref


class GcpKmsSigner(Signer):
    def __init__(self, key_ref: str) -> None:
        from google.cloud import kms

        self._key_ref = key_ref
        self._client = kms.KeyManagementServiceClient()

    def sign(self, payload: bytes) -> str:
        resp = self._client.asymmetric_sign(
            request={"name": self._key_ref, "digest": {"sha256": self.digest(payload)}}
        )
        return base64.urlsafe_b64encode(resp.signature).decode().rstrip("=")

    def verify(self, payload: bytes, signature: str) -> bool:
        # GCP KMS has no verify operation; verify locally against the public key.
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
        from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
        from cryptography.hazmat.primitives.hashes import SHA256
        from cryptography.hazmat.primitives.serialization import load_pem_public_key

        pad = "=" * (-len(signature) % 4)
        pub = load_pem_public_key(self.public_key_pem().encode())
        if not isinstance(pub, EllipticCurvePublicKey):
            raise TypeError(
                f"KMS key {self._key_ref} is not an EC key; ES256 verification needs one"
            )
        try:
            pub.verify(
                base64.urlsafe_b64decode(signature + pad),
                self.digest(payload),
                ec.ECDSA(Prehashed(SHA256())),
            )
            return True
        except InvalidSignature:
            return False

    def public_key_pem(self) -> str:
        return str(self._client.get_public_key(request={"name": self._key_ref}).pem)

    @property
    def key_id(self) -> str:
        return self._key_ref


def build_signer(settings: Settings | None = None) -> Signer:
    s = settings or get_settings()
    match s.signing_provider:
        case SigningProvider.LOCAL:
            assert s.signing_key_path is not None  # guaranteed by Settings validator
            return LocalSigner(s.signing_key_path)
        case SigningProvider.AWS_KMS:
            assert s.signing_key_ref is not None
            return AwsKmsSigner(s.signing_key_ref, s.cloud_region)
        case SigningProvider.AZURE_KEY_VAULT:
            assert s.signing_key_ref is not None
            return AzureKeyVaultSigner(s.signing_key_ref)
        case SigningProvider.GCP_KMS:
            assert s.signing_key_ref is not None
            return GcpKmsSigner(s.signing_key_ref)

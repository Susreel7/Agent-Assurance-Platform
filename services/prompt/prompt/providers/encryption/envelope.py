"""AES-GCM envelope blob format shared by cloud KMS providers."""

from __future__ import annotations

import os
import struct
from collections.abc import Callable
from enum import IntEnum

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from prompt.errors import EncryptionError

MAGIC = b"AAPENV1"


class KmsVendor(IntEnum):
    AWS = 1
    AZURE = 2
    GCP = 3


def _pack_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def _unpack_string(data: bytes, offset: int) -> tuple[str, int]:
    (length,) = struct.unpack_from(">H", data, offset)
    start = offset + 2
    end = start + length
    return data[start:end].decode("utf-8"), end


def seal_envelope(
    *,
    vendor: KmsVendor,
    key_ref: str,
    encrypted_dek: bytes,
    plaintext: bytes,
    dek: bytes,
) -> bytes:
    nonce = os.urandom(12)
    ciphertext = AESGCM(dek).encrypt(nonce, plaintext, None)
    return b"".join(
        [
            MAGIC,
            struct.pack("B", int(vendor)),
            _pack_string(key_ref),
            struct.pack(">I", len(encrypted_dek)),
            encrypted_dek,
            struct.pack(">H", len(nonce)),
            nonce,
            ciphertext,
        ]
    )


def open_envelope(
    blob: bytes,
    decrypt_dek: Callable[..., bytes],
) -> bytes:
    if not blob.startswith(MAGIC):
        raise EncryptionError("not an envelope ciphertext blob")
    offset = len(MAGIC)
    (vendor_id,) = struct.unpack_from("B", blob, offset)
    offset += 1
    key_ref, offset = _unpack_string(blob, offset)
    (dek_len,) = struct.unpack_from(">I", blob, offset)
    offset += 4
    encrypted_dek = blob[offset : offset + dek_len]
    offset += dek_len
    (nonce_len,) = struct.unpack_from(">H", blob, offset)
    offset += 2
    nonce = blob[offset : offset + nonce_len]
    offset += nonce_len
    ciphertext = blob[offset:]
    dek = decrypt_dek(
        vendor=KmsVendor(vendor_id),
        key_ref=key_ref,
        encrypted_dek=encrypted_dek,
    )
    return AESGCM(dek).decrypt(nonce, ciphertext, None)

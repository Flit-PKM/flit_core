"""AEAD encrypt/decrypt using AES-256-GCM. Ciphertext format: base64(nonce || ciphertext || tag)."""

from __future__ import annotations

import base64
import os
from typing import Optional, Union

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


NONCE_SIZE = 12
TAG_SIZE = 16
KEY_SIZE = 32


def encrypt_plaintext(
    plaintext: bytes,
    key: bytes,
    aad: Optional[bytes] = None,
) -> bytes:
    """Encrypt with AES-256-GCM. Returns base64(nonce || ciphertext || tag)."""
    if len(key) != KEY_SIZE:
        raise ValueError(f"Key must be {KEY_SIZE} bytes")
    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
    # ciphertext is already (ciphertext || tag)
    combined = nonce + ciphertext
    return base64.b64encode(combined)


def decrypt_ciphertext(
    ciphertext: Union[bytes, str],
    key: bytes,
    aad: Optional[bytes] = None,
) -> bytes:
    """Decrypt ciphertext from encrypt_plaintext. Input: base64 str/bytes (from DB) or raw bytes."""
    if len(key) != KEY_SIZE:
        raise ValueError(f"Key must be {KEY_SIZE} bytes")
    if isinstance(ciphertext, str):
        raw = base64.b64decode(ciphertext.encode("utf-8") if ciphertext else b"", validate=True)
    else:
        raw = ciphertext
        if len(raw) > NONCE_SIZE + TAG_SIZE and not raw.startswith(b"\x00"):
            try:
                raw = base64.b64decode(ciphertext, validate=True)
            except Exception:
                pass
    if len(raw) < NONCE_SIZE + TAG_SIZE:
        raise ValueError("Ciphertext too short")
    nonce = raw[:NONCE_SIZE]
    encrypted = raw[NONCE_SIZE:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, encrypted, aad)

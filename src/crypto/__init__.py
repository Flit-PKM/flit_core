"""Crypto utilities for encryption at rest (AEAD)."""

from .aead import decrypt_ciphertext, encrypt_plaintext

__all__ = ["encrypt_plaintext", "decrypt_ciphertext"]

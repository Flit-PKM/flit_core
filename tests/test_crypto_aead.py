"""Unit tests for AEAD encrypt/decrypt."""

import base64
import os
import pytest

from crypto.aead import decrypt_ciphertext, encrypt_plaintext, KEY_SIZE


def test_encrypt_decrypt_roundtrip():
    key = os.urandom(KEY_SIZE)
    plaintext = b"hello world"
    ciphertext = encrypt_plaintext(plaintext, key)
    assert ciphertext != plaintext
    decrypted = decrypt_ciphertext(ciphertext, key)
    assert decrypted == plaintext


def test_encrypt_decrypt_empty_string():
    key = os.urandom(KEY_SIZE)
    plaintext = b""
    ciphertext = encrypt_plaintext(plaintext, key)
    decrypted = decrypt_ciphertext(ciphertext, key)
    assert decrypted == plaintext


def test_encrypt_decrypt_with_aad():
    key = os.urandom(KEY_SIZE)
    aad = b"note:title"
    plaintext = b"secret title"
    ciphertext = encrypt_plaintext(plaintext, key, aad=aad)
    decrypted = decrypt_ciphertext(ciphertext, key, aad=aad)
    assert decrypted == plaintext


def test_decrypt_ciphertext_accepts_base64_string():
    key = os.urandom(KEY_SIZE)
    plaintext = b"foo"
    ciphertext = encrypt_plaintext(plaintext, key)
    # Pass as string (as from DB)
    b64_str = ciphertext.decode("utf-8")
    decrypted = decrypt_ciphertext(b64_str, key)
    assert decrypted == plaintext


def test_wrong_key_fails():
    key = os.urandom(KEY_SIZE)
    plaintext = b"secret"
    ciphertext = encrypt_plaintext(plaintext, key)
    other_key = os.urandom(KEY_SIZE)
    with pytest.raises(Exception):
        decrypt_ciphertext(ciphertext, other_key)


def test_wrong_aad_fails():
    key = os.urandom(KEY_SIZE)
    aad = b"note:title"
    plaintext = b"secret"
    ciphertext = encrypt_plaintext(plaintext, key, aad=aad)
    with pytest.raises(Exception):
        decrypt_ciphertext(ciphertext, key, aad=b"note:content")


def test_key_must_be_32_bytes():
    with pytest.raises(ValueError, match="32 bytes"):
        encrypt_plaintext(b"x", b"short")
    with pytest.raises(ValueError, match="32 bytes"):
        decrypt_ciphertext(b"x" * 50, b"short")

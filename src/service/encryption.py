"""Encryption at rest: per-user DEK and field-level encrypt/decrypt for notes and chunks."""

from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from crypto.aead import decrypt_ciphertext, encrypt_plaintext
from models.chunk import Chunk
from models.note import Note
from models.plan_subscription import PlanSubscription
from models.user_encryption_key import UserEncryptionKey

logger = logging.getLogger(__name__)

ENCRYPTION_VERSION = 1


def _get_master_key_bytes() -> Optional[bytes]:
    """Return the master key as 32 bytes, or None if encryption is disabled."""
    if not settings.encryption_enabled or not settings.ENCRYPTION_MASTER_KEY:
        return None
    return base64.b64decode(settings.ENCRYPTION_MASTER_KEY, validate=True)


def _aad_for_user(user_id: int) -> bytes:
    """Additional authenticated data for DEK encryption."""
    return f"user_id:{user_id}".encode("utf-8")


def _encryption_product_ids() -> set[str]:
    """Product IDs that entitle the user to encryption (from config)."""
    ids: set[str] = set()
    for pid in (
        getattr(settings, "DODO_PAYMENTS_MONTHLY_CORE_AI_ENCRYPTION", None),
        getattr(settings, "DODO_PAYMENTS_ANNUAL_CORE_AI_ENCRYPTION", None),
    ):
        if pid and isinstance(pid, str) and pid.strip():
            ids.add(pid.strip())
    return ids


async def user_has_encryption_plan(session: AsyncSession, user_id: int) -> bool:
    """True iff the user has an active PlanSubscription whose product_id is an encryption plan."""
    allowed = _encryption_product_ids()
    if not allowed:
        return False
    result = await session.execute(
        select(PlanSubscription).where(
            PlanSubscription.user_id == user_id,
            PlanSubscription.status == "active",
            PlanSubscription.product_id.isnot(None),
        )
    )
    row = result.scalar_one_or_none()
    if not row or not row.product_id:
        return False
    return row.product_id.strip() in allowed


async def is_encryption_enabled_for_user(session: AsyncSession, user_id: int) -> bool:
    """True when encryption is configured and the user has an active encryption plan."""
    if not settings.encryption_enabled:
        return False
    return await user_has_encryption_plan(session, user_id)


async def get_or_create_dek(session: AsyncSession, user_id: int) -> Optional[bytes]:
    """
    Return the DEK for the user (decrypted). If missing, create and persist one.
    Returns None when encryption is disabled or user does not have an encryption plan.
    """
    master = _get_master_key_bytes()
    if not master:
        return None
    if not await user_has_encryption_plan(session, user_id):
        return None

    result = await session.execute(
        select(UserEncryptionKey).where(UserEncryptionKey.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row:
        raw = base64.b64decode(row.encrypted_dek, validate=True)
        dek = decrypt_ciphertext(raw, master, aad=_aad_for_user(user_id))
        return dek

    dek = os.urandom(32)
    encrypted_dek_b64 = base64.b64encode(
        encrypt_plaintext(dek, master, aad=_aad_for_user(user_id))
    ).decode("utf-8")
    new_row = UserEncryptionKey(
        user_id=user_id,
        encrypted_dek=encrypted_dek_b64,
        key_version=ENCRYPTION_VERSION,
    )
    session.add(new_row)
    await session.flush()
    logger.debug("Created DEK for user_id=%s", user_id)
    return dek


async def encrypt_note_fields(
    session: AsyncSession,
    user_id: int,
    title: str,
    content: str,
) -> tuple[str, str]:
    """Encrypt title and content; return (encrypted_title_b64, encrypted_content_b64). No-op if encryption disabled."""
    dek = await get_or_create_dek(session, user_id)
    if not dek:
        return title, content
    title_b = title.encode("utf-8")
    content_b = content.encode("utf-8")
    enc_title = encrypt_plaintext(title_b, dek, aad=b"note:title")
    enc_content = encrypt_plaintext(content_b, dek, aad=b"note:content")
    return enc_title.decode("utf-8"), enc_content.decode("utf-8")


async def decrypt_note_fields(session: AsyncSession, note: Note) -> None:
    """Decrypt note title and content in place if encryption_version == 1. No-op if disabled or plaintext."""
    if getattr(note, "encryption_version", None) != ENCRYPTION_VERSION:
        return
    dek = await get_or_create_dek(session, note.user_id)
    if not dek:
        return
    try:
        note.title = decrypt_ciphertext(note.title, dek, aad=b"note:title").decode("utf-8")
        note.content = decrypt_ciphertext(note.content, dek, aad=b"note:content").decode("utf-8")
    except Exception as e:
        # Decryption can fail if value is already plaintext (e.g. same object from identity map)
        logger.debug("Decrypt note id=%s skipped: %s", getattr(note, "id", None), e)


async def encrypt_chunk_summary(
    session: AsyncSession,
    user_id: int,
    summary: str,
) -> str:
    """Encrypt summary; return encrypted base64 string. No-op if encryption disabled."""
    dek = await get_or_create_dek(session, user_id)
    if not dek:
        return summary
    enc = encrypt_plaintext(summary.encode("utf-8"), dek, aad=b"chunk:summary")
    return enc.decode("utf-8")


async def decrypt_chunk_summary(session: AsyncSession, chunk: Chunk) -> None:
    """Decrypt chunk summary in place if encryption_version == 1. Resolves user_id from note."""
    if getattr(chunk, "encryption_version", None) != ENCRYPTION_VERSION:
        return
    from models.note import Note
    result = await session.execute(select(Note).where(Note.id == chunk.note_id))
    note = result.scalar_one_or_none()
    if not note:
        return
    dek = await get_or_create_dek(session, note.user_id)
    if not dek:
        return
    try:
        chunk.summary = decrypt_ciphertext(chunk.summary, dek, aad=b"chunk:summary").decode("utf-8")
    except Exception as e:
        logger.debug("Decrypt chunk id=%s skipped: %s", getattr(chunk, "id", None), e)


def is_encryption_enabled() -> bool:
    """Deprecated: use is_encryption_enabled_for_user(session, user_id) for plan-gated encryption."""
    return False

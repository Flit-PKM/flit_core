from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user
from database.session import get_async_session
from logging_config import get_logger
from models.user import User
from schemas.vault_markdown import VaultMarkdownImportResult
from service.vault_markdown import export_vault_markdown, import_vault_markdown

logger = get_logger(__name__)

router = APIRouter(
    prefix="/vault",
    tags=["vault"],
)


@router.get(
    "/markdown-export",
    response_class=Response,
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "ZIP archive of per-note Markdown files",
        },
        400: {"description": "No active notes to export"},
    },
)
async def markdown_export(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Export the user's active notes as a Flit markdown ZIP backup.

    One UTF-8 `.md` file per note at the archive root. Does not include soft-deleted
    notes, embeddings, or pin state.
    """
    zip_bytes, zip_name = await export_vault_markdown(db, current_user.id)
    logger.info("User %s exported vault markdown (%s)", current_user.id, zip_name)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_name}"',
        },
    )


@router.post(
    "/markdown-import",
    response_model=VaultMarkdownImportResult,
    responses={
        400: {"description": "Invalid or unreadable import file"},
    },
)
async def markdown_import(
    file: UploadFile = File(..., description="ZIP backup or single .md note file"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Merge notes from a Flit markdown backup into the vault.

    Always inserts new notes; never updates or deletes existing notes by title or
    filename. Relationships resolve only against notes created in this import batch.
    """
    data = await file.read()
    if not data:
        raise BusinessLogicError("unreadable input")
    result = await import_vault_markdown(
        db,
        current_user.id,
        data,
        filename=file.filename,
    )
    logger.info(
        "User %s imported vault markdown: notes=%s rels=%s skipped=%s",
        current_user.id,
        result.notes_imported,
        result.relationships_imported,
        result.relationships_skipped,
    )
    return result

"""
FastAPI routes for Internet Archive operations.

Each endpoint maps 1:1 to a function in ia_service.py.
All endpoints are protected by the Bearer token auth.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse

from app.auth import verify_api_key
from app.ia_service import (
    delete_file,
    delete_item,
    rename_file,
    trigger_derive,
    update_metadata,
    upload_to_ia,
)
from app.schemas import (
    DeleteFileRequest,
    DeleteItemRequest,
    DeriveRequest,
    RenameRequest,
    RenameResult,
    StatusResponse,
    UpdateMetadataRequest,
    UploadResult,
)

logger = logging.getLogger("fikreislam-ia.routes")

ia_router = APIRouter()

UPLOAD_DIR = "uploads"


# ─── Upload ──────────────────────────────────────────────────────────────

@ia_router.post(
    "/upload",
    response_model=UploadResult,
    summary="Upload a file to Internet Archive",
)
async def upload_file(
    file: UploadFile = File(...),
    metadata: str = Form(...),
    coverFile: Optional[UploadFile] = File(None),
    existingIdentifier: Optional[str] = Form(None),
    _api_key: str = Depends(verify_api_key),
):
    """
    Accepts multipart form data identical to the existing Next.js API route:
      - file:               The main media file
      - metadata:           JSON string  { title, speaker?, media_type?, contentType? }
      - coverFile?:         Optional cover image
      - existingIdentifier?: Reuse an existing IA item
    """
    try:
        try:
            meta = json.loads(metadata)
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Invalid metadata JSON"}
            )

        title = meta.get("title")
        if not title:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Missing metadata title"}
            )

        # Check if we have a file or if we're just updating an existing item
        has_main_file = False
        try:
            if file and file.filename:
                # Some starlette versions might not have .size or it might be None
                # We check the spool file size if .size is missing
                file_size = getattr(file, "size", None)
                if file_size is None:
                    file.file.seek(0, os.SEEK_END)
                    file_size = file.file.tell()
                    file.file.seek(0)
                
                if file_size > 0:
                    has_main_file = True
        except Exception as e:
            logger.warning("Error checking main file size: %s", e)

        if not existingIdentifier and not has_main_file:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Missing file for new upload"}
            )

        # Save to temp files so the IA library can read from disk
        file_path = None
        cover_path = None

        try:
            if has_main_file:
                file_path = os.path.join(UPLOAD_DIR, file.filename or "upload")
                with open(file_path, "wb") as f:
                    shutil.copyfileobj(file.file, f)
                logger.info("Saved temp main file: %s", file_path)

            if coverFile and coverFile.filename:
                cover_size = getattr(coverFile, "size", None)
                if cover_size is None:
                    coverFile.file.seek(0, os.SEEK_END)
                    cover_size = coverFile.file.tell()
                    coverFile.file.seek(0)
                
                if cover_size > 0:
                    cover_path = os.path.join(UPLOAD_DIR, f"cover_{coverFile.filename}")
                    with open(cover_path, "wb") as f:
                        shutil.copyfileobj(coverFile.file, f)
                    logger.info("Saved temp cover file: %s", cover_path)

            result = upload_to_ia(
                file_path=file_path,
                original_filename=file.filename if file else "upload",
                title=title,
                content_type=meta.get("contentType"),
                speaker=meta.get("speaker"),
                media_type_subject=meta.get("media_type"),
                cover_path=cover_path,
                existing_identifier=existingIdentifier,
            )
            return result

        except Exception as e:
            import traceback
            logger.error("Upload operation failed: %s\n%s", e, traceback.format_exc())
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": f"IA Backend Error: {str(e)}"}
            )
        finally:
            # Clean up temp files
            for p in (file_path, cover_path):
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError as e:
                        logger.warning("Failed to remove temp file %s: %s", p, e)

    except Exception as e:
        logger.error("Global upload route error: %s", e)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": f"Unexpected server error: {str(e)}"}
        )


# ─── Metadata ────────────────────────────────────────────────────────────

@ia_router.patch(
    "/metadata",
    response_model=StatusResponse,
    summary="Update item metadata",
)
async def update_item_metadata(
    body: UpdateMetadataRequest,
    _api_key: str = Depends(verify_api_key),
):
    ok = update_metadata(
        ia_url=body.ia_url,
        title=body.title,
        speaker=body.speaker,
        media_type_subject=body.media_type,
        content_type=body.contentType,
    )
    if not ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Metadata update failed")
    return StatusResponse(success=True, message="Metadata updated")


# ─── Rename ──────────────────────────────────────────────────────────────

@ia_router.post(
    "/rename",
    response_model=RenameResult,
    summary="Rename a file inside an IA item",
)
async def rename_ia_file(
    body: RenameRequest,
    _api_key: str = Depends(verify_api_key),
):
    result = rename_file(body.ia_url, body.new_title)
    if result is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Rename failed")
    return RenameResult(**result)


# ─── Delete file ─────────────────────────────────────────────────────────

@ia_router.delete(
    "/file",
    response_model=StatusResponse,
    summary="Delete a single file from an IA item",
)
async def delete_ia_file(
    body: DeleteFileRequest,
    _api_key: str = Depends(verify_api_key),
):
    ok = delete_file(body.ia_url)
    if not ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "File deletion failed")
    return StatusResponse(success=True, message="File deleted")


# ─── Delete item ─────────────────────────────────────────────────────────

@ia_router.delete(
    "/item",
    response_model=StatusResponse,
    summary="Delete all files from an IA item",
)
async def delete_ia_item(
    body: DeleteItemRequest,
    _api_key: str = Depends(verify_api_key),
):
    ok = delete_item(body.identifier)
    if not ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Item deletion failed")
    return StatusResponse(success=True, message="Item deleted")


# ─── Derive ──────────────────────────────────────────────────────────────

@ia_router.post(
    "/derive",
    response_model=StatusResponse,
    summary="Trigger IA derive for an item",
)
async def trigger_ia_derive(
    body: DeriveRequest,
    _api_key: str = Depends(verify_api_key),
):
    ok = trigger_derive(body.identifier)
    if not ok:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Derive trigger failed")
    return StatusResponse(success=True, message="Derive triggered")

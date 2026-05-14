"""
FastAPI routes for Internet Archive operations.

Each endpoint maps 1:1 to a function in ia_service.py.
All endpoints are protected by the Bearer token auth.
"""

from __future__ import annotations

import json
import logging
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
from app.ia_helpers import is_valid_identifier
from app.route_helpers import (
    raise_operation_error,
    remove_file_safely,
    save_upload_to_temp,
    upload_size,
    upload_temp_dir,
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


# ─── Upload ──────────────────────────────────────────────────────────────

@ia_router.post(
    "/upload",
    response_model=UploadResult,
    summary="Upload a file to Internet Archive",
)
async def upload_file(
    file: Optional[UploadFile] = File(None),
    metadata: str = Form(...),
    coverFile: Optional[UploadFile] = File(None),
    existingIdentifier: Optional[str] = Form(None),
    _api_key: str = Depends(verify_api_key),
):
    """
    Accepts multipart form data identical to the existing Next.js API route:
      - file:               The main media file
      - metadata:           JSON string  { title, speaker? }
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
        has_cover_file = False
        try:
            if file and file.filename:
                has_main_file = upload_size(file) > 0
        except Exception as e:
            logger.warning("Error checking main file size: %s", e)

        try:
            if coverFile and coverFile.filename:
                has_cover_file = upload_size(coverFile) > 0
        except Exception as e:
            logger.warning("Error checking cover file size: %s", e)

        if not has_main_file and not (existingIdentifier and has_cover_file):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Missing file for upload"}
            )

        if existingIdentifier and not is_valid_identifier(existingIdentifier):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Invalid existingIdentifier"}
            )

        # Save to unique temp files so the IA library can read from disk.
        file_path = None
        cover_path = None

        try:
            with upload_temp_dir() as temp_dir:
                if has_main_file:
                    file_path = save_upload_to_temp(file, "main-", temp_dir)
                    logger.info("Saved temp main file: %s", file_path)

                if coverFile and coverFile.filename and has_cover_file:
                    cover_path = save_upload_to_temp(coverFile, "cover-", temp_dir)
                    logger.info("Saved temp cover file: %s", cover_path)

                result = upload_to_ia(
                    file_path=file_path,
                    original_filename=file.filename if file else "upload",
                    title=title,
                    speaker=meta.get("speaker"),
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
                try:
                    remove_file_safely(p)
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
    result = delete_file(body.ia_url)
    if not result["success"]:
        raise_operation_error(result, "File deletion failed")
    return StatusResponse(**result)


# ─── Delete item ─────────────────────────────────────────────────────────

@ia_router.delete(
    "/item",
    response_model=StatusResponse,
    summary="Remove an Internet Archive item",
)
async def delete_ia_item(
    body: DeleteItemRequest,
    _api_key: str = Depends(verify_api_key),
):
    if not body.confirm:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Set confirm=true to remove/deaccession this Internet Archive item",
        )

    result = delete_item(body.identifier)
    if not result["success"]:
        raise_operation_error(result, "Item deletion failed")
    return StatusResponse(**result)


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
    result = trigger_derive(body.identifier)
    if not result["success"]:
        raise_operation_error(result, "Derive trigger failed")
    return StatusResponse(**result)

"""
Core Internet Archive service using the official `internetarchive` Python library.

Every public function in this module mirrors an operation from the old
TypeScript `internetArchive.ts` but uses the official library's session,
upload, modify_metadata, delete, and task-submission APIs.
"""

from __future__ import annotations

import logging
import os
from typing import Optional
from urllib.parse import quote

import internetarchive as ia

from app.config import settings
from app.ia_helpers import (
    extract_identifier,
    extract_identifier_and_filename,
    generate_identifier,
    get_session,
    is_valid_identifier,
    response_text,
    sanitize_filename,
    submit_task_with_retry,
)

logger = logging.getLogger("fikreislam-ia.service")

IA_UPLOAD_HEADERS = {
    "x-archive-interactive-priority": "1",
    "x-archive-keep-old-version": "0",
    "x-archive-queue-derive": "0",
}


def _has_file(path: str | None) -> bool:
    return bool(path and os.path.exists(path) and os.path.getsize(path) > 0)


def _upload_main_file(
    identifier: str,
    file_path: str,
    safe_filename: str,
    metadata: dict,
) -> tuple[str, str]:
    responses = ia.upload(
        identifier,
        files={safe_filename: file_path},
        metadata=metadata,
        access_key=settings.ia_access_key,
        secret_key=settings.ia_secret_key,
        queue_derive=False,
        retries=3,
        retries_sleep=2,
        headers=IA_UPLOAD_HEADERS,
    )

    for resp in responses:
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"IA upload failed ({resp.status_code}): {resp.text[:500]}")

    logger.info("Uploaded main file: %s → %s", safe_filename, identifier)
    return (
        f"ia://{identifier}/{safe_filename}",
        f"https://archive.org/download/{identifier}/{quote(safe_filename)}",
    )


def _upload_cover_file(identifier: str, cover_path: str) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    cover_ext = os.path.splitext(cover_path)[1] or ".jpg"
    cover_remote = f"cover{cover_ext}"

    try:
        logger.info("Starting cover upload for %s: %s", identifier, cover_remote)
        responses = ia.upload(
            identifier,
            files={cover_remote: cover_path},
            access_key=settings.ia_access_key,
            secret_key=settings.ia_secret_key,
            queue_derive=False,
            retries=2,
            retries_sleep=2,
            headers=IA_UPLOAD_HEADERS,
        )
        for resp in responses:
            if resp.status_code in (200, 201):
                logger.info("Uploaded cover successfully: %s → %s", cover_remote, identifier)
                return f"ia://{identifier}/{cover_remote}", warnings

            warning = f"Cover upload failed ({resp.status_code})"
            warnings.append(warning)
            logger.warning("%s for %s: %s", warning, identifier, response_text(resp))
    except Exception as e:
        warning = f"Cover upload failed: {e}"
        warnings.append(warning)
        logger.warning("Cover upload non-fatal error: %s", e)

    return None, warnings


def _derive_upload(identifier: str) -> tuple[bool, int | None, str | None, list[str]]:
    logger.info("Triggering derive task for %s...", identifier)
    result = trigger_derive(identifier)
    derive_triggered = result["success"]
    if derive_triggered:
        logger.info("Derive task triggered for %s", identifier)
    else:
        logger.warning("Upload succeeded but derive did not trigger for %s", identifier)
    return (
        derive_triggered,
        result.get("taskStatusCode"),
        result.get("taskResponse"),
        result.get("warnings", []),
    )


# ─── Upload ──────────────────────────────────────────────────────────────

def upload_to_ia(
    file_path: Optional[str],
    original_filename: str,
    title: str,
    speaker: str | None = None,
    cover_path: str | None = None,
    existing_identifier: str | None = None,
) -> dict:
    """
    Upload a file (and optional cover) to Internet Archive.

    Uses `internetarchive.upload()` which handles:
      • Auto bucket creation
      • Retries on 503 / SlowDown
      • Proper S3 auth headers

    Returns the same shape as the TS IAUploadResult.
    """
    identifier = existing_identifier or generate_identifier(speaker)
    if not is_valid_identifier(identifier):
        raise RuntimeError("Invalid Internet Archive identifier")

    safe_filename = sanitize_filename(original_filename)
    warnings: list[str] = []
    metadata = {
        "title": title,
        "creator": "فکر اسلام",
    }

    ia_url = ""
    download_url = ""

    if _has_file(file_path):
        try:
            ia_url, download_url = _upload_main_file(
                identifier,
                file_path,
                safe_filename,
                metadata,
            )
        except Exception as e:
            logger.error("Main file upload failed for %s: %s", identifier, e)
            raise RuntimeError(f"Internet Archive upload failed: {str(e)}")
    elif not existing_identifier:
        raise RuntimeError("No file provided for new upload")

    # Upload cover image
    cover_ia_url = None
    if _has_file(cover_path):
        cover_ia_url, cover_warnings = _upload_cover_file(identifier, cover_path)
        warnings.extend(cover_warnings)

    # Trigger a derive task to ensure thumbnails and player assets are updated
    derive_triggered = False
    derive_task_status_code = None
    derive_task_response = None
    if _has_file(file_path) or cover_ia_url:
        (
            derive_triggered,
            derive_task_status_code,
            derive_task_response,
            derive_warnings,
        ) = _derive_upload(identifier)
        warnings.extend(derive_warnings)

    logger.info(
        "audit action=upload identifier=%s file=%s cover_uploaded=%s derive_triggered=%s warnings=%d",
        identifier,
        safe_filename,
        bool(cover_ia_url),
        derive_triggered,
        len(warnings),
    )
    return {
        "identifier": identifier,
        "fileName": safe_filename,
        "iaUrl": ia_url,
        "downloadUrl": download_url,
        "coverIaUrl": cover_ia_url,
        "deriveTriggered": derive_triggered,
        "deriveTaskStatusCode": derive_task_status_code,
        "deriveTaskResponse": derive_task_response,
        "warnings": warnings,
    }


# ─── Update metadata ────────────────────────────────────────────────────

def update_metadata(
    ia_url: str,
    title: str | None = None,
) -> bool:
    """Update item metadata using official modify_metadata (JSON Patch)."""
    identifier = extract_identifier(ia_url)
    if not is_valid_identifier(identifier):
        return False

    md: dict = {
        "creator": "فکر اسلام"
    }
    if title:
        md["title"] = title

    try:
        resp = ia.modify_metadata(
            identifier,
            metadata=md,
            access_key=settings.ia_access_key,
            secret_key=settings.ia_secret_key,
        )
        if resp.status_code == 200:
            logger.info("Metadata updated: %s", identifier)
            trigger_derive(identifier)
            return True
        # "no changes" is still a success
        if resp.status_code == 400 and "no changes" in resp.text.lower():
            return True
        logger.warning("Metadata update status %d: %s", resp.status_code, resp.text[:300])
        return False
    except Exception as e:
        logger.error("Error updating metadata for %s: %s", identifier, e)
        return False


# ─── Rename file ─────────────────────────────────────────────────────────

def rename_file(ia_url: str, new_title: str) -> dict | None:
    """
    Rename a file inside an IA item (copy → delete old).
    
    Uses the official library's item.copy_file() approach via the S3 API
    since the library doesn't expose copy natively — we fall back to
    session-based raw copy.
    """
    identifier, old_filename = extract_identifier_and_filename(ia_url)
    if not identifier or not old_filename:
        return None
    ext = old_filename.rsplit(".", 1)[-1] if "." in old_filename else ""
    new_filename = f"{sanitize_filename(new_title)}.{ext}" if ext else sanitize_filename(new_title)

    if old_filename == new_filename:
        return {
            "iaUrl": f"ia://{identifier}/{old_filename}",
            "downloadUrl": f"https://archive.org/download/{identifier}/{quote(old_filename)}",
        }

    try:
        session = get_session()
        # Use S3 copy (PUT with x-amz-copy-source header)
        copy_url = f"https://s3.us.archive.org/{identifier}/{quote(new_filename)}"
        copy_source = f"/{identifier}/{quote(old_filename)}"

        resp = session.put(
            copy_url,
            headers={
                "Authorization": f"LOW {settings.ia_access_key}:{settings.ia_secret_key}",
                "x-amz-copy-source": copy_source,
                "x-amz-auto-make-bucket": "1",
                "x-archive-keep-old-version": "0",
                "x-archive-queue-derive": "0",
                "x-archive-interactive-priority": "1",
            },
        )

        if resp.status_code not in (200, 201):
            logger.error("Copy failed (%d): %s", resp.status_code, resp.text[:300])
            return None

        # Delete old file
        delete_result = delete_file(ia_url)
        warnings = delete_result.get("warnings", [])

        logger.info("Renamed %s → %s in %s", old_filename, new_filename, identifier)
        derive_result = trigger_derive(identifier)
        warnings.extend(derive_result.get("warnings", []))
        return {
            "iaUrl": f"ia://{identifier}/{new_filename}",
            "downloadUrl": f"https://archive.org/download/{identifier}/{quote(new_filename)}",
            "deriveTriggered": derive_result["success"],
            "warnings": warnings,
        }
    except Exception as e:
        logger.error("Error renaming file in %s: %s", identifier, e)
        return None


# ─── Delete file ─────────────────────────────────────────────────────────

def delete_file(ia_url: str) -> dict:
    """Delete a single file from an IA item."""
    identifier, filename = extract_identifier_and_filename(ia_url)
    if not identifier or not filename:
        return {
            "success": False,
            "message": "Invalid Internet Archive file URL",
            "warnings": ["Invalid Internet Archive file URL"],
        }

    try:
        resp = ia.delete(
            identifier,
            files=[filename],
            access_key=settings.ia_access_key,
            secret_key=settings.ia_secret_key,
        )
        logger.info("Deleted file %s from %s", filename, identifier)
        derive_result = trigger_derive(identifier)
        logger.info(
            "audit action=delete_file identifier=%s file=%s derive_triggered=%s warnings=%d",
            identifier,
            filename,
            derive_result["success"],
            len(derive_result.get("warnings", [])),
        )
        return {
            "success": True,
            "identifier": identifier,
            "fileName": filename,
            "message": "File deleted",
            "deleteResponse": response_text(resp),
            "deriveTriggered": derive_result["success"],
            "warnings": derive_result.get("warnings", []),
        }
    except Exception as e:
        logger.error("Error deleting file %s from %s: %s", filename, identifier, e)
        return {
            "success": False,
            "identifier": identifier,
            "fileName": filename,
            "message": "File deletion failed",
            "warnings": [str(e)],
        }


# ─── Delete entire item ─────────────────────────────────────────────────


def delete_item(identifier: str) -> dict:
    """Remove/deaccession an IA item (matches the web UI "Remove Items" button).

    Submits a ``make_dark.php`` task — this is the same mechanism the
    archive.org web UI uses to deaccession an item and remove it from
    uploads, search results, and public listings.
    """
    result = submit_task_with_retry(
        identifier,
        cmd="make_dark.php",
        comment="remove item via fikreislam backend",
    )
    if result["success"]:
        logger.info("make_dark task submitted for %s — item will be removed from uploads", identifier)
        logger.info(
            "audit action=delete_item identifier=%s task_status=%s",
            identifier,
            result.get("taskStatusCode"),
        )
        result["message"] = "Item removal task submitted"
    return result


# ─── Trigger derive ─────────────────────────────────────────────────────

def trigger_derive(identifier: str) -> dict:
    """Submit a derive task for the item."""
    result = submit_task_with_retry(
        identifier,
        cmd="derive.php",
        comment="force derive via fikreislam backend",
        attempts=2,
    )
    if result["success"]:
        logger.info("Derive triggered for %s", identifier)
        result["message"] = "Derive triggered"
    else:
        logger.error("Error triggering derive for %s: %s", identifier, result.get("message"))
    return result

"""
Core Internet Archive service using the official `internetarchive` Python library.

Every public function in this module mirrors an operation from the old
TypeScript `internetArchive.ts` but uses the official library's session,
upload, modify_metadata, delete, and task-submission APIs.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Optional
from urllib.parse import quote

import internetarchive as ia

from app.config import settings
from app.schemas import CONTENT_TYPE_TO_MEDIATYPE

logger = logging.getLogger("fikreislam-ia.service")


# ─── Helpers ─────────────────────────────────────────────────────────────

def _get_session() -> ia.ArchiveSession:
    """Create an authenticated IA session from env credentials."""
    settings.validate_ia_credentials()
    config = {
        "s3": {
            "access": settings.ia_access_key,
            "secret": settings.ia_secret_key,
        }
    }
    return ia.get_session(config=config)


def sanitize_filename(name: str) -> str:
    """Match the TypeScript sanitizeFileName behaviour."""
    name = re.sub(r"\s+", "_", name)
    # Keep word chars, dots, hyphens, and Arabic/Urdu characters
    name = re.sub(r"[^\w.\-\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]", "_", name)
    name = re.sub(r"_+", "_", name)
    return name


def generate_identifier(speaker_slug: Optional[str] = None) -> str:
    """Generate a unique IA item identifier (mirrors TS generateItemIdentifier)."""
    short_id = uuid.uuid4().hex[:10]
    if speaker_slug:
        # Strictly ASCII for the identifier bucket name
        slug = re.sub(r"[^a-zA-Z0-9\s-]", "", speaker_slug)
        slug = re.sub(r"\s+", "-", slug)
        slug = re.sub(r"-+", "-", slug)
        slug = slug.lower().strip("-")[:40]
        if len(slug) >= 3:
            return f"fikreislam-{slug}-{short_id}"
    return f"fikreislam-media-{short_id}"


def extract_identifier(url: str | None) -> str | None:
    """Extract an IA identifier from ia://, download, or details URLs."""
    if not url:
        return None
    if url.startswith("ia://"):
        return url.replace("ia://", "").split("/")[0]
    if "archive.org/download/" in url:
        return url.split("archive.org/download/")[1].split("/")[0]
    if "archive.org/details/" in url:
        return url.split("archive.org/details/")[1].split("/")[0]
    return None


def _resolve_mediatype(content_type: str | None) -> str:
    """Map Urdu content type to IA mediatype string."""
    if content_type and content_type in CONTENT_TYPE_TO_MEDIATYPE:
        return CONTENT_TYPE_TO_MEDIATYPE[content_type]
    return "audio"


# ─── Upload ──────────────────────────────────────────────────────────────

def upload_to_ia(
    file_path: Optional[str],
    original_filename: str,
    title: str,
    content_type: str | None = None,
    speaker: str | None = None,
    media_type_subject: str | None = None,
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
    session = _get_session()
    identifier = existing_identifier or generate_identifier(speaker)
    safe_filename = sanitize_filename(original_filename)
    mediatype = _resolve_mediatype(content_type)

    metadata = {
        "mediatype": mediatype,
        "collection": "opensource",
        "title": title,
        "description": f"Content from Fikr-e-Islam: {title}",
    }
    if speaker:
        metadata["creator"] = speaker
    if media_type_subject:
        metadata["subject"] = media_type_subject

    ia_url = ""
    download_url = ""

    # Upload main file
    if file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        # Prepare file dict with remote name as key
        files = {safe_filename: file_path}

        try:
            responses = ia.upload(
                identifier,
                files=files,
                metadata=metadata,
                access_key=settings.ia_access_key,
                secret_key=settings.ia_secret_key,
                queue_derive=False,
                retries=3,
                retries_sleep=2,
                headers={
                    "x-archive-interactive-priority": "1",
                    "x-archive-keep-old-version": "0",
                    "x-archive-queue-derive": "0",
                },
            )

            # Check for errors
            for resp in responses:
                if resp.status_code not in (200, 201):
                    raise RuntimeError(
                        f"IA upload failed ({resp.status_code}): {resp.text[:500]}"
                    )
            
            ia_url = f"ia://{identifier}/{safe_filename}"
            download_url = f"https://archive.org/download/{identifier}/{quote(safe_filename)}"
            logger.info("Uploaded main file: %s → %s", safe_filename, identifier)
        except Exception as e:
            logger.error("Main file upload failed for %s: %s", identifier, e)
            raise RuntimeError(f"Internet Archive upload failed: {str(e)}")
    elif not existing_identifier:
        raise RuntimeError("No file provided for new upload")

    # Upload cover image
    cover_ia_url = None
    if cover_path and os.path.exists(cover_path) and os.path.getsize(cover_path) > 0:
        try:
            cover_ext = os.path.splitext(cover_path)[1] or ".jpg"
            cover_remote = f"cover{cover_ext}"
            cover_files = {cover_remote: cover_path}
            logger.info("Starting cover upload for %s: %s", identifier, cover_remote)

            cover_responses = ia.upload(
                identifier,
                files=cover_files,
                access_key=settings.ia_access_key,
                secret_key=settings.ia_secret_key,
                queue_derive=False,
                retries=2,
                retries_sleep=2,
                headers={
                    "x-archive-interactive-priority": "1",
                    "x-archive-keep-old-version": "0",
                    "x-archive-queue-derive": "0",
                },
            )
            for resp in cover_responses:
                if resp.status_code in (200, 201):
                    cover_ia_url = f"ia://{identifier}/{cover_remote}"
                    logger.info("Uploaded cover successfully: %s → %s", cover_remote, identifier)
        except Exception as e:
            logger.warning("Cover upload non-fatal error: %s", e)

    # Trigger a derive task to ensure thumbnails and player assets are updated
    if (file_path and os.path.exists(file_path)) or cover_ia_url:
        logger.info("Triggering derive task for %s...", identifier)
        trigger_derive(identifier)
        logger.info("Derive task triggered for %s", identifier)

    return {
        "identifier": identifier,
        "fileName": safe_filename,
        "iaUrl": ia_url,
        "downloadUrl": download_url,
        "coverIaUrl": cover_ia_url,
    }


# ─── Update metadata ────────────────────────────────────────────────────

def update_metadata(
    ia_url: str,
    title: str | None = None,
    speaker: str | None = None,
    media_type_subject: str | None = None,
    content_type: str | None = None,
) -> bool:
    """Update item metadata using official modify_metadata (JSON Patch)."""
    identifier = extract_identifier(ia_url)
    if not identifier:
        return False

    mediatype = _resolve_mediatype(content_type)

    md: dict = {"mediatype": mediatype}
    if title:
        md["title"] = title
        md["description"] = f"Content from Fikr-e-Islam: {title}"
    if speaker:
        md["creator"] = speaker
    if media_type_subject:
        md["subject"] = media_type_subject

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
    if not ia_url or not ia_url.startswith("ia://"):
        return None

    path = ia_url.replace("ia://", "")
    parts = path.split("/")
    if len(parts) < 2:
        return None

    identifier = parts[0]
    old_filename = parts[1]
    ext = old_filename.rsplit(".", 1)[-1] if "." in old_filename else ""
    new_filename = f"{sanitize_filename(new_title)}.{ext}" if ext else sanitize_filename(new_title)

    if old_filename == new_filename:
        return {
            "iaUrl": f"ia://{identifier}/{old_filename}",
            "downloadUrl": f"https://archive.org/download/{identifier}/{quote(old_filename)}",
        }

    try:
        session = _get_session()
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
        delete_file(ia_url)

        logger.info("Renamed %s → %s in %s", old_filename, new_filename, identifier)
        trigger_derive(identifier)
        return {
            "iaUrl": f"ia://{identifier}/{new_filename}",
            "downloadUrl": f"https://archive.org/download/{identifier}/{quote(new_filename)}",
        }
    except Exception as e:
        logger.error("Error renaming file in %s: %s", identifier, e)
        return None


# ─── Delete file ─────────────────────────────────────────────────────────

def delete_file(ia_url: str) -> bool:
    """Delete a single file from an IA item."""
    if not ia_url or not ia_url.startswith("ia://"):
        return False

    path = ia_url.replace("ia://", "")
    slash_idx = path.index("/") if "/" in path else -1
    if slash_idx == -1:
        return False

    identifier = path[:slash_idx]
    filename = path[slash_idx + 1:]

    try:
        ia.delete(
            identifier,
            files=[filename],
            access_key=settings.ia_access_key,
            secret_key=settings.ia_secret_key,
        )
        logger.info("Deleted file %s from %s", filename, identifier)
        trigger_derive(identifier)
        return True
    except Exception as e:
        logger.error("Error deleting file %s from %s: %s", filename, identifier, e)
        return False


# ─── Delete entire item ─────────────────────────────────────────────────

def delete_item(identifier: str) -> bool:
    """Delete all files in an IA item (effectively removing the item)."""
    if not identifier:
        return False

    try:
        ia.delete(
            identifier,
            cascade_delete=True,
            access_key=settings.ia_access_key,
            secret_key=settings.ia_secret_key,
        )
        logger.info("Deleted entire item %s", identifier)
        return True
    except Exception as e:
        logger.error("Error deleting item %s: %s", identifier, e)
        return False


# ─── Trigger derive ─────────────────────────────────────────────────────

def trigger_derive(identifier: str) -> bool:
    """Submit a derive task for the item."""
    if not identifier:
        return False

    try:
        session = _get_session()
        resp = session.submit_task(
            identifier,
            cmd="derive.php",
            comment="force derive via fikreislam backend",
        )
        ok = resp.status_code in (200, 201)
        if ok:
            logger.info("Derive triggered for %s", identifier)
        return ok
    except Exception as e:
        logger.error("Error triggering derive for %s: %s", identifier, e)
        return False

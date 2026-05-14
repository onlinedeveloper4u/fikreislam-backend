"""
Shared helpers for Internet Archive operations.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import internetarchive as ia

from app.config import settings

logger = logging.getLogger("fikreislam-ia.helpers")

IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,99}$")


def get_session() -> ia.ArchiveSession:
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
    name = re.sub(r"[^\w.\-\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("._") or "upload"


def generate_identifier(speaker_slug: Optional[str] = None) -> str:
    """Generate a unique IA item identifier."""
    short_id = uuid.uuid4().hex[:10]
    if speaker_slug:
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
        return url.replace("ia://", "", 1).split("/")[0]
    if "archive.org/download/" in url:
        return url.split("archive.org/download/")[1].split("/")[0]
    if "archive.org/details/" in url:
        return url.split("archive.org/details/")[1].split("/")[0]
    return None


def is_valid_identifier(identifier: str | None) -> bool:
    """Validate an Internet Archive item identifier before task/S3 calls."""
    return bool(identifier and IDENTIFIER_RE.fullmatch(identifier))


def extract_identifier_and_filename(ia_url: str | None) -> tuple[str | None, str | None]:
    """Extract identifier and file path from an ia:// or archive.org download URL."""
    if not ia_url:
        return None, None

    if ia_url.startswith("ia://"):
        path = ia_url.replace("ia://", "", 1)
    else:
        parsed = urlparse(ia_url)
        if parsed.netloc not in {"archive.org", "www.archive.org"}:
            return None, None
        prefix = "/download/"
        if not parsed.path.startswith(prefix):
            return None, None
        path = parsed.path[len(prefix):]

    if "/" not in path:
        return None, None

    identifier, filename = path.split("/", 1)
    filename = unquote(filename)
    if not is_valid_identifier(identifier) or not filename:
        return None, None
    return identifier, filename


def response_text(resp: Any, limit: int = 300) -> str:
    return str(getattr(resp, "text", "") or "")[:limit]


def submit_task_with_retry(
    identifier: str,
    cmd: str,
    comment: str,
    attempts: int = 3,
    sleep_seconds: float = 2,
) -> dict:
    """Submit an IA task with small retries for transient failures."""
    if not is_valid_identifier(identifier):
        return {
            "success": False,
            "identifier": identifier,
            "taskSubmitted": False,
            "message": "Invalid Internet Archive identifier",
            "warnings": ["Invalid Internet Archive identifier"],
        }

    last_status = None
    last_text = ""
    for attempt in range(1, attempts + 1):
        try:
            resp = get_session().submit_task(identifier, cmd=cmd, comment=comment)
            last_status = resp.status_code
            last_text = response_text(resp)
            if resp.status_code in (200, 201):
                return {
                    "success": True,
                    "identifier": identifier,
                    "taskSubmitted": True,
                    "taskStatusCode": resp.status_code,
                    "taskResponse": last_text,
                    "warnings": [],
                }

            retryable = resp.status_code in (408, 429, 500, 502, 503, 504)
            logger.warning(
                "Task %s attempt %d/%d returned %s for %s: %s",
                cmd,
                attempt,
                attempts,
                resp.status_code,
                identifier,
                last_text,
            )
            if not retryable:
                break
        except Exception as e:
            last_text = str(e)
            logger.warning(
                "Task %s attempt %d/%d failed for %s: %s",
                cmd,
                attempt,
                attempts,
                identifier,
                e,
            )

        if attempt < attempts:
            time.sleep(sleep_seconds)

    warning = f"{cmd} task was not accepted"
    if last_status:
        warning = f"{warning} ({last_status})"
    return {
        "success": False,
        "identifier": identifier,
        "taskSubmitted": False,
        "taskStatusCode": last_status,
        "taskResponse": last_text,
        "message": warning,
        "warnings": [warning],
    }

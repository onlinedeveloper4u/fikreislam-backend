"""
Small helpers for FastAPI route handlers.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from typing import Iterator

from fastapi import HTTPException, UploadFile, status


UPLOAD_DIR = "uploads"


@contextmanager
def upload_temp_dir() -> Iterator[str]:
    """Create and clean up a per-request upload temp directory."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    temp_dir = tempfile.mkdtemp(prefix="ia-upload-", dir=UPLOAD_DIR)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def save_upload_to_temp(upload: UploadFile, prefix: str, temp_dir: str) -> str:
    suffix = os.path.splitext(upload.filename or "")[1]
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=temp_dir,
        prefix=prefix,
        suffix=suffix,
    ) as tmp:
        shutil.copyfileobj(upload.file, tmp)
        return tmp.name


def remove_file_safely(path: str | None) -> None:
    if path and os.path.exists(path):
        os.remove(path)


def upload_size(upload: UploadFile) -> int:
    file_size = getattr(upload, "size", None)
    if file_size is None:
        upload.file.seek(0, os.SEEK_END)
        file_size = upload.file.tell()
        upload.file.seek(0)
    return file_size or 0


def raise_operation_error(result: dict, fallback_message: str) -> None:
    status_code = (
        status.HTTP_400_BAD_REQUEST
        if "Invalid" in result.get("message", "")
        else status.HTTP_502_BAD_GATEWAY
    )
    raise HTTPException(status_code, result.get("message", fallback_message))

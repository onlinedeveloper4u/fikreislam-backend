"""
Pydantic models (request / response schemas).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── Content type mapping ─────────────────────────────────────────────────
CONTENT_TYPE_TO_MEDIATYPE = {
    "آڈیو": "audio",
    "ویڈیو": "movies",
    "book": "texts",
}


# ── Request models ───────────────────────────────────────────────────────
class UploadMetadata(BaseModel):
    """Metadata sent alongside an upload."""

    title: str
    speaker: Optional[str] = None
    media_type: Optional[str] = None          # subject tag
    contentType: Optional[Literal["آڈیو", "ویڈیو", "book"]] = "آڈیو"


class UpdateMetadataRequest(BaseModel):
    """Body for PATCH /metadata."""

    ia_url: str = Field(..., description="ia:// URL or archive.org URL")
    title: Optional[str] = None
    speaker: Optional[str] = None
    media_type: Optional[str] = None
    contentType: Optional[Literal["آڈیو", "ویڈیو", "book"]] = None


class RenameRequest(BaseModel):
    ia_url: str
    new_title: str


class DeleteFileRequest(BaseModel):
    ia_url: str


class DeleteItemRequest(BaseModel):
    identifier: str


class DeriveRequest(BaseModel):
    identifier: str


# ── Response models ──────────────────────────────────────────────────────
class UploadResult(BaseModel):
    identifier: str
    fileName: str
    iaUrl: str
    downloadUrl: str
    coverIaUrl: Optional[str] = None


class RenameResult(BaseModel):
    iaUrl: str
    downloadUrl: str


class StatusResponse(BaseModel):
    success: bool
    message: str = ""

"""
Pydantic models (request / response schemas).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── Request models ───────────────────────────────────────────────────────
class UploadMetadata(BaseModel):
    """Metadata sent alongside an upload."""

    title: str
    speaker: Optional[str] = None
    contentType: Optional[Literal["آڈیو", "ویڈیو", "کتاب"]] = "آڈیو"


class UpdateMetadataRequest(BaseModel):
    """Body for PATCH /metadata."""

    ia_url: str = Field(..., description="ia:// URL or archive.org URL")
    title: Optional[str] = None
    contentType: Optional[Literal["آڈیو", "ویڈیو", "کتاب"]] = None


class RenameRequest(BaseModel):
    ia_url: str
    new_title: str


class DeleteFileRequest(BaseModel):
    ia_url: str


class DeleteItemRequest(BaseModel):
    identifier: str
    confirm: bool = Field(
        False,
        description="Must be true to confirm IA item removal/deaccession",
    )


class DeriveRequest(BaseModel):
    identifier: str


# ── Response models ──────────────────────────────────────────────────────
class UploadResult(BaseModel):
    identifier: str
    fileName: str
    iaUrl: str
    downloadUrl: str
    coverIaUrl: Optional[str] = None
    deriveTriggered: bool = False
    deriveTaskStatusCode: Optional[int] = None
    deriveTaskResponse: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class RenameResult(BaseModel):
    iaUrl: str
    downloadUrl: str


class StatusResponse(BaseModel):
    success: bool
    message: str = ""
    identifier: Optional[str] = None
    fileName: Optional[str] = None
    taskSubmitted: Optional[bool] = None
    taskStatusCode: Optional[int] = None
    taskResponse: Optional[str] = None
    deriveTriggered: Optional[bool] = None
    warnings: list[str] = Field(default_factory=list)

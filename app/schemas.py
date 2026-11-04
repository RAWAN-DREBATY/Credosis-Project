from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import config
from .models import UploadStatus


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["Rawan"])
    email: str = Field(max_length=255, examples=["rawan@example.com"])

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or v.startswith("@") or v.endswith("@") or " " in v:
            raise ValueError("invalid email address")
        return v

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty")
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    created_at: datetime


class UserCreated(UserOut):
    api_key: str = Field(description="Send this in the X-API-Key header. Shown only once.")


class UploadCreate(BaseModel):
    file_name: str = Field(min_length=1, max_length=255, examples=["thesis.pdf"])
    total_size: int = Field(gt=0, le=config.MAX_FILE_SIZE, examples=[1048576])
    total_chunks: int = Field(gt=0, le=config.MAX_CHUNKS, examples=[4])
    sha256: str | None = Field(
        default=None, min_length=64, max_length=64, description="Optional SHA-256 of the whole file"
    )

    @field_validator("file_name")
    @classmethod
    def safe_name(cls, v: str) -> str:
        v = v.strip()
        if not v or "/" in v or "\\" in v or v in {".", ".."}:
            raise ValueError("file_name must be a plain file name (no slashes)")
        return v


class UploadStatusOut(BaseModel):
    id: int
    file_name: str
    total_size: int
    total_chunks: int
    status: UploadStatus
    received_chunks: list[int]
    missing_chunks: list[int]
    progress_percent: float
    created_at: datetime


class UploadSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    file_name: str
    total_size: int
    total_chunks: int
    status: UploadStatus
    created_at: datetime


class ChunkAck(BaseModel):
    upload_id: int
    chunk_number: int
    size: int
    already_received: bool = Field(description="True if this chunk was sent before (safe retry)")
    received_count: int
    total_chunks: int


class ErrorOut(BaseModel):
    detail: str

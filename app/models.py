import enum
import secrets
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UploadStatus(str, enum.Enum):
    in_progress = "in_progress"
    completed = "completed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    api_key: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=lambda: secrets.token_hex(24)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    uploads: Mapped[list["Upload"]] = relationship(back_populates="user")


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    total_size: Mapped[int] = mapped_column(Integer)
    total_chunks: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)  # whole-file hash (optional)
    status: Mapped[UploadStatus] = mapped_column(Enum(UploadStatus), default=UploadStatus.in_progress)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="uploads")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="upload", cascade="all, delete-orphan"
    )


class Chunk(Base):
    __tablename__ = "chunks"
    # One row per (upload, chunk number): this is what makes retries safe.
    __table_args__ = (UniqueConstraint("upload_id", "chunk_number", name="uq_upload_chunk"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id"), index=True)
    chunk_number: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    upload: Mapped[Upload] = relationship(back_populates="chunks")

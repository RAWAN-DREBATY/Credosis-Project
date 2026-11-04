from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config, storage
from ..auth import get_current_user
from ..database import get_db
from ..models import Chunk, Upload, UploadStatus, User
from ..schemas import (
    ChunkAck,
    ErrorOut,
    UploadCreate,
    UploadStatusOut,
    UploadSummary,
)

router = APIRouter(prefix="/uploads", tags=["Uploads"])

COMMON_ERRORS = {
    401: {"model": ErrorOut, "description": "Missing or invalid API key"},
    404: {"model": ErrorOut, "description": "Upload not found"},
}


# ---------- helpers ----------
def get_own_upload(upload_id: int, user: User, db: Session) -> Upload:
    """Return the upload only if it belongs to the current user (else 404, so ids don't leak)."""
    upload = db.get(Upload, upload_id)
    if upload is None or upload.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    return upload


def received_numbers(upload: Upload, db: Session) -> list[int]:
    rows = db.scalars(
        select(Chunk.chunk_number).where(Chunk.upload_id == upload.id).order_by(Chunk.chunk_number)
    )
    return list(rows)


def build_status(upload: Upload, db: Session) -> UploadStatusOut:
    received = received_numbers(upload, db)
    have = set(received)
    missing = [n for n in range(upload.total_chunks) if n not in have]
    return UploadStatusOut(
        id=upload.id,
        file_name=upload.file_name,
        total_size=upload.total_size,
        total_chunks=upload.total_chunks,
        status=upload.status,
        received_chunks=received,
        missing_chunks=missing,
        progress_percent=round(100 * len(received) / upload.total_chunks, 1),
        created_at=upload.created_at,
    )


# ---------- endpoints ----------
@router.post(
    "",
    response_model=UploadStatusOut,
    status_code=status.HTTP_201_CREATED,
    responses={401: COMMON_ERRORS[401]},
    summary="1. Start a new upload",
)
def create_upload(
    payload: UploadCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # A chunk can't be bigger than the limit, so the file must fit in total_chunks chunks.
    if payload.total_size > payload.total_chunks * config.MAX_CHUNK_SIZE:
        raise HTTPException(
            422,
            f"total_chunks is too small: each chunk can be at most {config.MAX_CHUNK_SIZE} bytes",
        )
    if payload.total_chunks > payload.total_size:
        raise HTTPException(
            422, "total_chunks cannot be larger than total_size"
        )
    upload = Upload(
        user_id=user.id,
        file_name=payload.file_name,
        total_size=payload.total_size,
        total_chunks=payload.total_chunks,
        sha256=payload.sha256.lower() if payload.sha256 else None,
    )
    db.add(upload)
    db.commit()
    return build_status(upload, db)


@router.get(
    "",
    response_model=list[UploadSummary],
    responses={401: COMMON_ERRORS[401]},
    summary="List my uploads",
)
def list_uploads(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return list(
        db.scalars(select(Upload).where(Upload.user_id == user.id).order_by(Upload.id.desc()))
    )


@router.get(
    "/{upload_id}",
    response_model=UploadStatusOut,
    responses=COMMON_ERRORS,
    summary="2. Check progress (which chunks arrived, which are missing)",
)
def get_upload(
    upload_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return build_status(get_own_upload(upload_id, user, db), db)


@router.put(
    "/{upload_id}/chunks/{chunk_number}",
    response_model=ChunkAck,
    responses={
        **COMMON_ERRORS,
        400: {"model": ErrorOut, "description": "Bad chunk (empty, too big, or checksum mismatch)"},
        409: {"model": ErrorOut, "description": "Upload already completed, or chunk number was sent with different data"},
    },
    summary="3. Send one chunk (safe to retry)",
    description=(
        "Send the raw bytes of one chunk as the request body. "
        "**Idempotent:** sending the same chunk again returns `already_received: true` and changes nothing. "
        "Optionally send `X-Chunk-SHA256` so the server can verify the data was not corrupted."
    ),
)
def upload_chunk(
    upload_id: int,
    chunk_number: Annotated[int, Path(ge=0)],
    data: Annotated[bytes, Body(media_type="application/octet-stream")],
    x_chunk_sha256: Annotated[
        str | None, Header(description="Optional SHA-256 hex of this chunk, for integrity check")
    ] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    upload = get_own_upload(upload_id, user, db)

    if upload.status == UploadStatus.completed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Upload is already completed")
    if chunk_number >= upload.total_chunks:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"chunk_number must be between 0 and {upload.total_chunks - 1}",
        )
    if len(data) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Chunk is empty")
    if len(data) > config.MAX_CHUNK_SIZE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Chunk too large (max {config.MAX_CHUNK_SIZE} bytes)"
        )

    digest = storage.sha256_bytes(data)
    if x_chunk_sha256 and x_chunk_sha256.lower() != digest:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Checksum mismatch: chunk was corrupted in transit, please resend"
        )

    def count_received() -> int:
        return db.scalar(select(func.count()).select_from(Chunk).where(Chunk.upload_id == upload.id)) or 0

    def ack(already: bool, size: int) -> ChunkAck:
        return ChunkAck(
            upload_id=upload.id,
            chunk_number=chunk_number,
            size=size,
            already_received=already,
            received_count=count_received(),
            total_chunks=upload.total_chunks,
        )

    def check_existing(existing: Chunk) -> ChunkAck:
        # Same data again -> it's a retry, answer OK. Different data -> real conflict.
        if existing.sha256 == digest:
            return ack(True, existing.size)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Chunk {chunk_number} was already received with different data",
        )

    existing = db.scalar(
        select(Chunk).where(Chunk.upload_id == upload.id, Chunk.chunk_number == chunk_number)
    )
    if existing:
        return check_existing(existing)

    # New chunk: write the file first, then record it in the database.
    storage.save_chunk(upload.id, chunk_number, data)
    db.add(Chunk(upload_id=upload.id, chunk_number=chunk_number, size=len(data), sha256=digest))
    try:
        db.commit()
    except IntegrityError:
        # Two identical requests arrived at the same moment; the other one won. That's fine.
        db.rollback()
        existing = db.scalar(
            select(Chunk).where(Chunk.upload_id == upload.id, Chunk.chunk_number == chunk_number)
        )
        if existing:
            return check_existing(existing)
        raise
    return ack(False, len(data))


@router.post(
    "/{upload_id}/complete",
    response_model=UploadStatusOut,
    responses={
        **COMMON_ERRORS,
        409: {"model": ErrorOut, "description": "Some chunks are still missing"},
        422: {"model": ErrorOut, "description": "Assembled file doesn't match the declared size or hash"},
    },
    summary="4. Finish the upload (assembles the file)",
)
def complete_upload(
    upload_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    upload = get_own_upload(upload_id, user, db)
    if upload.status == UploadStatus.completed:  # calling it twice is harmless
        return build_status(upload, db)

    st = build_status(upload, db)
    if st.missing_chunks:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot complete: {len(st.missing_chunks)} chunk(s) missing, e.g. {st.missing_chunks[:10]}",
        )

    path, digest, size = storage.assemble(upload.id, upload.file_name, upload.total_chunks)
    if size != upload.total_size or (upload.sha256 and upload.sha256 != digest):
        path.unlink(missing_ok=True)
        raise HTTPException(
            422,
            "Assembled file does not match the declared total_size / sha256. Check your chunks and start again.",
        )

    upload.status = UploadStatus.completed
    upload.sha256 = digest
    db.commit()
    storage.cleanup_chunks(upload.id)
    return build_status(upload, db)


@router.get(
    "/{upload_id}/download",
    responses={**COMMON_ERRORS, 409: {"model": ErrorOut, "description": "Upload not completed yet"}},
    summary="Download the finished file",
)
def download_upload(
    upload_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    upload = get_own_upload(upload_id, user, db)
    if upload.status != UploadStatus.completed:
        raise HTTPException(status.HTTP_409_CONFLICT, "Upload is not completed yet")
    path = storage.final_path(upload.id, upload.file_name)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File is missing from storage")
    return FileResponse(path, filename=upload.file_name)


@router.delete(
    "/{upload_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=COMMON_ERRORS,
    summary="Delete an upload and its data",
)
def delete_upload(
    upload_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    upload = get_own_upload(upload_id, user, db)
    storage.delete_all(upload.id, upload.file_name)
    db.delete(upload)
    db.commit()

"""File storage on disk. Chunks are written to temporary files, then assembled."""
import hashlib
import os
import shutil
from pathlib import Path

from . import config


def upload_dir(upload_id: int) -> Path:
    return config.STORAGE_DIR / f"upload_{upload_id}"


def chunk_path(upload_id: int, chunk_number: int) -> Path:
    return upload_dir(upload_id) / f"chunk_{chunk_number:06d}.part"


def final_path(upload_id: int, file_name: str) -> Path:
    return config.STORAGE_DIR / "completed" / f"{upload_id}_{file_name}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_chunk(upload_id: int, chunk_number: int, data: bytes) -> None:
    """Write atomically: temp file first, then rename, so a crash never leaves a half chunk."""
    path = chunk_path(upload_id, chunk_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def assemble(upload_id: int, file_name: str, total_chunks: int) -> tuple[Path, str, int]:
    """Join all chunks in order. Returns (path, sha256, size)."""
    out = final_path(upload_id, file_name)
    out.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    size = 0
    tmp = out.with_suffix(out.suffix + ".tmp")
    with open(tmp, "wb") as f:
        for n in range(total_chunks):
            data = chunk_path(upload_id, n).read_bytes()
            f.write(data)
            h.update(data)
            size += len(data)
    os.replace(tmp, out)
    return out, h.hexdigest(), size


def cleanup_chunks(upload_id: int) -> None:
    shutil.rmtree(upload_dir(upload_id), ignore_errors=True)


def delete_all(upload_id: int, file_name: str) -> None:
    cleanup_chunks(upload_id)
    final_path(upload_id, file_name).unlink(missing_ok=True)

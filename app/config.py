"""App settings. Values can be overridden with environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'uploads.db'}")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", BASE_DIR / "storage"))

# Limits (validation)
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB per file
MAX_CHUNK_SIZE = 5 * 1024 * 1024   # 5 MB per chunk
MAX_CHUNKS = 10_000

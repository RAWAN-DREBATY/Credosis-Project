from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

# auto_error=False so we can return our own clear 401 message.
# This also adds the "Authorize" button to Swagger UI.
api_key_header = APIKeyHeader(
    name="X-API-Key", auto_error=False, description="API key returned by POST /users"
)


def get_current_user(
    api_key: str | None = Depends(api_key_header),
    db: Session = Depends(get_db),
) -> User:
    """Very simple auth: the X-API-Key header identifies the user."""
    if not api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key header")
    user = db.scalar(select(User).where(User.api_key == api_key))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return user

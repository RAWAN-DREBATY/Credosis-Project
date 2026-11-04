from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import User
from ..schemas import ErrorOut, UserCreate, UserCreated, UserOut

router = APIRouter(prefix="/users", tags=["Users"])


@router.post(
    "",
    response_model=UserCreated,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorOut, "description": "Email already registered"}},
    summary="Create a user and get an API key",
)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(name=payload.name, email=payload.email)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two requests with the same email at the same time
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    return user


@router.get("/me", response_model=UserOut, summary="Who am I? (checks your API key)")
def me(user: User = Depends(get_current_user)):
    return user

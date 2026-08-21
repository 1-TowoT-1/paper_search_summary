from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.db import User
from app.models.schemas import AuthToken, UserCreate, UserLogin, UserRead

router = APIRouter()


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    try:
        existing = db.query(User).filter((User.username == payload.username) | (User.email == payload.email)).first()
        if existing:
            raise HTTPException(status_code=409, detail="Username or email already exists")

        user = User(
            id=uuid4(),
            username=payload.username,
            email=payload.email,
            password_hash=hash_password(payload.password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username or email already exists") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc


@router.post("/login", response_model=AuthToken)
def login(payload: UserLogin, db: Session = Depends(get_db)) -> AuthToken:
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return AuthToken(access_token=create_access_token(subject=str(user.id)), token_type="bearer")

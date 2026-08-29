from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user_id, get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.db import User
from app.models.schemas import (
    AuthToken,
    EmailChangeRequest,
    EmailVerificationRequest,
    EmailVerificationResponse,
    MessageResponse,
    PasswordChangeRequest,
    UserCreate,
    UserLogin,
    UserRead,
)
from app.services.email_verification_service import email_verification_service

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


@router.get("/me", response_model=UserRead)
def get_me(db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)) -> User:
    user = db.get(User, UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/email/verification-code", response_model=EmailVerificationResponse)
def request_email_verification_code(payload: EmailVerificationRequest) -> EmailVerificationResponse:
    code = email_verification_service.create_code(str(payload.email))
    return EmailVerificationResponse(
        email=payload.email,
        message="Verification code generated. Development mode returns dev_code directly.",
        dev_code=code,
    )


@router.patch("/me/email", response_model=UserRead)
def change_email(
    payload: EmailChangeRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> User:
    if not email_verification_service.verify_code(str(payload.new_email), payload.verification_code):
        raise HTTPException(status_code=400, detail="Invalid or expired email verification code")

    user = db.get(User, UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.query(User).filter(User.email == str(payload.new_email), User.id != user.id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")

    user.email = str(payload.new_email)
    try:
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already exists") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc


@router.patch("/me/password", response_model=MessageResponse)
def change_password(
    payload: PasswordChangeRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> MessageResponse:
    user = db.get(User, UUID(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Old password is incorrect")

    user.password_hash = hash_password(payload.new_password)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
    return MessageResponse(message="Password updated successfully")

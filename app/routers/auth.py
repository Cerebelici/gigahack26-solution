import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import create_token, current_user, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _normalize_email(value: str) -> str:
    value = value.strip().lower()
    if not EMAIL_PATTERN.fullmatch(value):
        raise ValueError("Enter a valid email address.")
    return value


Email = Annotated[str, Field(max_length=320), AfterValidator(_normalize_email)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Password = Annotated[str, Field(min_length=8, max_length=256)]


class SignupRequest(BaseModel):
    email: Email
    password: Password
    name: Name


class LoginRequest(BaseModel):
    email: Annotated[str, AfterValidator(lambda v: v.strip().lower())]
    password: str


class UpdateMeRequest(BaseModel):
    name: Name | None = None
    password: Password | None = None


class UserOut(BaseModel):
    id: int
    email: str
    name: str


class AuthResponse(BaseModel):
    token: str
    user: UserOut


def user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name)


@router.post("/signup", status_code=201)
def signup(body: SignupRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = User(email=body.email, name=body.name, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    return AuthResponse(token=create_token(user.id), user=user_out(user))


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.scalar(select(User).where(User.email == body.email))
    if not verify_password(user.password_hash if user else None, body.password) or user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return AuthResponse(token=create_token(user.id), user=user_out(user))


@router.get("/me")
def read_me(user: User = Depends(current_user)) -> UserOut:
    return user_out(user)


@router.patch("/me")
def update_me(body: UpdateMeRequest, user: User = Depends(current_user), db: Session = Depends(get_db)) -> UserOut:
    if body.name is not None:
        user.name = body.name
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    db.commit()
    return user_out(user)

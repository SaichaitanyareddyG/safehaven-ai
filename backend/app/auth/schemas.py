import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["admin", "clinician"]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    # Length only, deliberately — this is a prototype-stage floor against
    # trivially weak passwords, not a full complexity policy (no forced
    # mixed-case/digit/symbol rules, which mostly push users toward
    # predictable substitutions rather than actually stronger passwords).
    password: str = Field(min_length=10)
    full_name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: str
    must_change_password: bool = False
    tour_completed: bool = True


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)


class AdminUserRead(BaseModel):
    """A row on the admin Users page."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: str
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime


class AdminUserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    role: Role = "clinician"


class AdminUserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class InviteResponse(BaseModel):
    """After adding a user or sending a reset: the link, and whether it was
    emailed. The link is returned so an admin can pass it on another way if
    email failed; it is never shown again."""

    user: AdminUserRead
    link: str
    link_expires_at: datetime
    emailed: bool
    email_problem: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class PasswordLinkInfo(BaseModel):
    """What the set-password page shows before the password is chosen."""

    purpose: Literal["invite", "reset"]
    email: EmailStr
    full_name: str


class SetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=10)

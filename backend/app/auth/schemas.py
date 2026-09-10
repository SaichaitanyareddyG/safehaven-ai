import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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

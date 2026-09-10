from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.config import get_settings


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str
    full_name: str
    role: str


class AuthError(Exception):
    """Raised for any failed login or invalid/expired token, regardless of provider."""


class AuthProvider(Protocol):
    """Everything auth-dependent business logic needs. A CognitoAuthProvider can
    implement this later — routes and dependencies never import a concrete provider."""

    def authenticate(self, email: str, password: str) -> AuthenticatedUser: ...

    def create_token(self, user: AuthenticatedUser) -> str: ...

    def verify_token(self, token: str) -> AuthenticatedUser: ...


def get_auth_provider(db: Session) -> AuthProvider:
    settings = get_settings()
    if settings.auth_provider == "dev":
        from app.auth.dev_provider import DevAuthProvider

        return DevAuthProvider(db)
    raise NotImplementedError(f"Auth provider '{settings.auth_provider}' is not implemented in Phase 1")

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.provider import AuthenticatedUser, AuthError, get_auth_provider
from app.core.db import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_signed_in_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> AuthenticatedUser:
    """Any valid session, even one still holding an admin-issued one-time
    password. Only the routes that let such a user finish signing in
    (/auth/me, /auth/change-password) take this directly."""
    provider = get_auth_provider(db)
    try:
        return provider.verify_token(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(user: Annotated[AuthenticatedUser, Depends(get_signed_in_user)]) -> AuthenticatedUser:
    # Enforced here, not just in the dashboard: a one-time password an admin
    # read out must not open patient records until its owner replaces it.
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Choose a new password to continue")
    return user


def require_admin(user: Annotated[AuthenticatedUser, Depends(get_current_user)]) -> AuthenticatedUser:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins only")
    return user

import uuid

from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.provider import AuthenticatedUser, AuthError
from app.auth.security import create_access_token, decode_access_token, verify_password


class DevAuthProvider:
    """Local-DB credentials + a self-signed JWT. Satisfies the same AuthProvider
    protocol a future CognitoAuthProvider would, so route code never changes."""

    def __init__(self, db: Session):
        self.db = db

    def authenticate(self, email: str, password: str) -> AuthenticatedUser:
        user = self.db.query(User).filter(User.email == email).first()
        if user is None or not verify_password(password, user.hashed_password):
            raise AuthError("Invalid email or password")
        return _to_authenticated_user(user)

    def create_token(self, user: AuthenticatedUser) -> str:
        return create_access_token(subject=user.id, extra_claims={"email": user.email, "role": user.role})

    def verify_token(self, token: str) -> AuthenticatedUser:
        try:
            payload = decode_access_token(token)
            user_id = uuid.UUID(payload["sub"])
        except Exception as exc:
            raise AuthError("Invalid or expired token") from exc

        user = self.db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise AuthError("User no longer exists")
        return _to_authenticated_user(user)


def _to_authenticated_user(user: User) -> AuthenticatedUser:
    return AuthenticatedUser(id=str(user.id), email=user.email, full_name=user.full_name, role=user.role)

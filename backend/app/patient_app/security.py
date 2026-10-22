"""Patient-app session tokens.

Signed with the same key as staff tokens but marked typ=patient, which the
staff provider refuses (app/auth/dev_provider.py) and which is the only kind
this module accepts — so neither kind of token opens the other's routes.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings

TOKEN_TYPE = "patient"


class InvalidPatientTokenError(Exception):
    pass


def create_patient_token(patient_id: uuid.UUID, account_id: uuid.UUID, session_version: int) -> tuple[str, datetime]:
    """sub is whose care this opens; acc is whose login (patient or caregiver)."""
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.patient_session_days)
    payload = {
        "sub": str(patient_id),
        "acc": str(account_id),
        "typ": TOKEN_TYPE,
        "sv": session_version,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm), expires_at


def decode_patient_token(token: str) -> tuple[uuid.UUID, uuid.UUID | None, int]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("typ") != TOKEN_TYPE:
            raise InvalidPatientTokenError()
        account_id = uuid.UUID(payload["acc"]) if payload.get("acc") else None
        return uuid.UUID(payload["sub"]), account_id, int(payload["sv"])
    except InvalidPatientTokenError:
        raise
    except Exception as exc:
        raise InvalidPatientTokenError() from exc

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.conditions.router import router as conditions_router
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.encounters.router import router as encounters_router
from app.instructions.router import router as instructions_router
from app.medication_verification.router import router as medication_verification_router
from app.patient_access.router import router as patient_access_router
from app.patient_chat.router import router as patient_chat_router
from app.patients.router import router as patients_router

settings = get_settings()

app = FastAPI(title="SafeHaven AI", version="0.1.0")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    # Explicit, not "*" — allow_credentials=True means a wildcard here would
    # apply to every allowed origin; keep both lists exactly matching what
    # the frontend actually sends (see frontend/src/lib/api-client.ts) so
    # this stays safe even as cors_origins grows beyond one entry later.
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(auth_router)
app.include_router(patients_router)
app.include_router(instructions_router)
app.include_router(patient_access_router)
app.include_router(audit_router)
app.include_router(conditions_router)
app.include_router(patient_chat_router)
app.include_router(encounters_router)
app.include_router(medication_verification_router)


@app.get("/health")
def health(db: Annotated[Session, Depends(get_db)]) -> dict:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {"status": "ok", "db": db_status}

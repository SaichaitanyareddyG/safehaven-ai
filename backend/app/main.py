import asyncio
import logging
import contextlib
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.allergies.router import router as allergies_router
from app.appointments.router import router as appointments_router
from app.reports.router import router as reports_router
from app.audit.router import router as audit_router
from app.auth.admin_router import router as admin_users_router
from app.auth.router import router as auth_router
from app.conditions.router import router as conditions_router
from app.core import error_alerts
from app.core.client_errors import router as client_errors_router
from app.core.config import get_settings
from app.core.db import get_db
from app.core.rate_limit import limiter
from app.encounters.router import router as encounters_router
from app.instructions.router import router as instructions_router
from app.medication_verification.router import router as medication_verification_router
from app.wearables.device_router import router as wearable_device_api_router
from app.wearables.router import router as wearables_router
from app.wearables.sweeper import run_offline_sweeper
from app.patient_access.router import router as patient_access_router
from app.patient_app.router import router as patient_app_router
from app.patient_app.router import internal_router as patient_app_internal_router
from app.patient_app.router import staff_router as patient_app_staff_router
from app.patient_chat.router import router as patient_chat_router
from app.patients.router import router as patients_router

settings = get_settings()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # A silent band must alert whether or not a dashboard is open.
    task = None
    if settings.offline_sweep_interval_seconds > 0:
        task = asyncio.create_task(run_offline_sweeper(settings.offline_sweep_interval_seconds))
    yield
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="SafeHaven AI",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)

app.state.limiter = limiter


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Any error no route handled: a plain message with a reference for the
    person, a log line and a (throttled) alert to the admins — never the
    stack trace, which would leak internals."""
    reference = error_alerts.new_reference()
    route = getattr(request.scope.get("route"), "path", None) or "unknown route"
    logger.exception("Unhandled error ref=%s", reference)
    error_alerts.report("server", f"{request.method} {route}", type(exc).__name__, error_alerts.app_frame(exc), reference)
    response = JSONResponse(
        status_code=500,
        content={"detail": f"Something went wrong on our side. If it keeps happening, quote reference {reference}."},
    )
    # This response is built outside the CORS middleware; without these the
    # browser hides it and the person only sees "couldn't reach SafeHaven".
    origin = request.headers.get("origin")
    if origin and origin in settings.cors_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response
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
app.include_router(client_errors_router)
app.include_router(admin_users_router)
app.include_router(patients_router)
app.include_router(instructions_router)
app.include_router(patient_access_router)
app.include_router(patient_app_staff_router)
# The patient's own API: its own token type, refused on every staff route.
app.include_router(patient_app_router)
app.include_router(patient_app_internal_router)
app.include_router(audit_router)
app.include_router(conditions_router)
app.include_router(allergies_router)
app.include_router(patient_chat_router)
app.include_router(encounters_router)
app.include_router(appointments_router)
app.include_router(reports_router)
app.include_router(medication_verification_router)
app.include_router(wearables_router)
# Separate router, separate path prefix, separate auth dependency: a device
# credential must never be usable on a clinician route (see
# app/wearables/dependencies.py).
app.include_router(wearable_device_api_router)


@app.get("/health")
def health(db: Annotated[Session, Depends(get_db)]) -> dict:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {"status": "ok", "db": db_status}

"""Errors that happen in a person's browser (a page that crashed), reported
the same way as server errors: kind and place only, throttled."""

import re
from typing import Literal

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from app.core import error_alerts
from app.core.rate_limit import limiter

router = APIRouter(tags=["client-errors"], include_in_schema=False)

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


class ClientError(BaseModel):
    app: Literal["staff", "patient", "care-link"]
    # A page path; ids are replaced before anything is stored or sent.
    path: str = Field(max_length=200)
    error_type: str = Field(max_length=80)


@router.post("/client-errors", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/minute")
def report_client_error(request: Request, payload: ClientError) -> dict:
    route = _UUID.sub("{id}", payload.path.split("?", 1)[0].split("#", 1)[0])
    error_type = re.sub(r"[^A-Za-z0-9_.]", "", payload.error_type)[:80] or "Error"
    reference = error_alerts.new_reference()
    error_alerts.report(f"{payload.app} page", route, error_type, "browser", reference)
    return {"reference": reference}

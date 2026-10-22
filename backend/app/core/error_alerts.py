"""Tell the admins when the live server or a page breaks.

No third-party error service: those receive request data, and request data
here can be patient data. The alert says only when, where (the route
pattern, never the full URL), what kind of error, the code line it came
from, and a reference the person who hit it was shown. Never the request
body, query string or exception message, which can carry values.

Throttled per (kind, route) so one broken page cannot flood an inbox.
"""

import logging
import secrets
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)

APP_ROOT = Path(__file__).resolve().parents[1]
_SAME_ERROR_EVERY_S = 30 * 60
_MAX_PER_HOUR = 10

_lock = threading.Lock()
_last_sent: dict[str, float] = {}
_suppressed: dict[str, int] = {}
_sent_times: deque[float] = deque()


def new_reference() -> str:
    return secrets.token_hex(3).upper()


def app_frame(exc: BaseException) -> str:
    """The deepest line of OUR code in the traceback ("patient_app/doses.py:120")."""
    where = "unknown"
    for frame in traceback.extract_tb(exc.__traceback__):
        try:
            relative = Path(frame.filename).resolve().relative_to(APP_ROOT)
        except ValueError:
            continue
        where = f"{relative}:{frame.lineno}"
    return where


def _should_send(key: str) -> tuple[bool, int]:
    now = time.monotonic()
    with _lock:
        while _sent_times and now - _sent_times[0] > 3600:
            _sent_times.popleft()
        if now - _last_sent.get(key, -1e9) < _SAME_ERROR_EVERY_S or len(_sent_times) >= _MAX_PER_HOUR:
            _suppressed[key] = _suppressed.get(key, 0) + 1
            return False, 0
        _last_sent[key] = now
        _sent_times.append(now)
        return True, _suppressed.pop(key, 0)


def _admin_emails() -> list[str]:
    from app.auth.models import ROLE_ADMIN, User
    from app.core.db import SessionLocal

    db = SessionLocal()
    try:
        return [e for (e,) in db.query(User.email).filter(User.role == ROLE_ADMIN, User.is_active.is_(True)).all()]
    finally:
        db.close()


def _send(kind: str, route: str, error_type: str, where: str, reference: str, repeats: int) -> None:
    from app.core import email as email_module

    try:
        recipients = _admin_emails()
    except Exception:  # the database may be what is broken
        logger.warning("Error alert not sent: could not read admin addresses")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"When: {stamp}",
        f"Where: {route}",
        f"Error: {error_type} at {where}",
        f"Reference shown to the user: {reference}",
    ]
    if repeats:
        lines.append(f"Also happened {repeats} more time(s) since the last alert.")
    text = (
        f"SafeHaven hit an unexpected {kind} error.\n\n" + "\n".join(lines)
        + "\n\nNo patient information is included. Check the server logs (search for the reference) for details."
    )
    html = "<p>" + "<br>".join(escape(line) for line in [f"SafeHaven hit an unexpected {kind} error.", "", *lines]) + "</p>"
    for to in recipients:
        email_module.send_email(to, f"[SafeHaven] {kind} error: {error_type} on {route}", text, html)


def report(kind: str, route: str, error_type: str, where: str, reference: str) -> None:
    """Log always; email the admins (throttled) when email is set up."""
    logger.error("Unexpected %s error ref=%s route=%s type=%s at=%s", kind, reference, route, error_type, where)
    if not get_settings().resend_api_key or not get_settings().error_alerts_enabled:
        return
    send, repeats = _should_send(f"{kind}|{route}|{error_type}")
    if send:
        _dispatch(_send, kind, route, error_type, where, reference, repeats)


def _dispatch(fn, *args) -> None:
    # Off the request path: an email outage must not slow the error page.
    threading.Thread(target=fn, args=args, daemon=True).start()

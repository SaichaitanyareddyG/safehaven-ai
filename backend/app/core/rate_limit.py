"""Per-IP rate limiting for unauthenticated, brute-forceable endpoints
(/auth/login, /auth/register). Nothing else in the app needs this today —
every other route requires a valid JWT already, which is a much stronger
gate than an IP-based limit."""

from slowapi import Limiter
from starlette.requests import Request


def client_address(request: Request) -> str:
    """The address the hosting proxy saw, not one the client wrote.

    uvicorn runs with --forwarded-allow-ips='*' (behind Render's proxy), so
    request.client is the LEFTMOST X-Forwarded-For entry, which the caller
    controls: a random value per request made every limit here unlimited.
    The proxy appends the address it actually saw at the RIGHT end, so that
    is the one to key on. Without the header (local runs), the socket address.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=client_address)

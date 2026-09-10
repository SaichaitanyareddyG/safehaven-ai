"""Per-IP rate limiting for unauthenticated, brute-forceable endpoints
(/auth/login, /auth/register). Nothing else in the app needs this today —
every other route requires a valid JWT already, which is a much stronger
gate than an IP-based limit."""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

"""Rate limits key on the address the proxy saw, never one the caller wrote."""

from starlette.requests import Request

from app.core.rate_limit import client_address


def _request(headers: dict[str, str], client=("10.0.0.9", 1234)) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": client})


def test_a_forged_forwarded_for_does_not_change_the_key():
    honest = _request({"X-Forwarded-For": "203.0.113.7"})
    forged = _request({"X-Forwarded-For": "1.2.3.4, 203.0.113.7"})
    assert client_address(honest) == client_address(forged) == "203.0.113.7"


def test_without_a_proxy_the_socket_address_is_used():
    assert client_address(_request({})) == "10.0.0.9"

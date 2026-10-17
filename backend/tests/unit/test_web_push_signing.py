"""The real pywebpush path signs and encrypts with our key format; only the
HTTP call to the push service is replaced."""

import base64
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import get_settings
from app.patient_app.models import PushSubscription
from app.patient_app.push import send_to_subscription
from scripts.generate_vapid_keys import generate


class _Response:
    status_code = 201
    text = ""


class _FakeDb:
    def delete(self, _):
        raise AssertionError("must not delete a working subscription")


def test_webpush_encrypts_and_signs(monkeypatch):
    public_key, private_key = generate()
    settings = get_settings()
    monkeypatch.setattr(settings, "vapid_public_key", public_key)
    monkeypatch.setattr(settings, "vapid_private_key", private_key)

    browser_key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    subscription = PushSubscription(
        endpoint="https://fcm.googleapis.com/fcm/send/abc", p256dh=b64(browser_key), auth=b64(os.urandom(16))
    )

    captured = {}

    def fake_post(url, data=None, headers=None, timeout=None, **_):
        captured.update(url=url, data=data, headers=headers)
        return _Response()

    monkeypatch.setattr("pywebpush.requests.post", fake_post)
    assert send_to_subscription(_FakeDb(), subscription, {"title": "t", "body": "b"}) is True
    assert captured["url"] == subscription.endpoint
    assert captured["headers"]["content-encoding"] == "aes128gcm"
    assert "vapid" in captured["headers"]["authorization"].lower()
    assert b'"title"' not in captured["data"]  # encrypted, not plain JSON

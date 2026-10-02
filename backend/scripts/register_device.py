#!/usr/bin/env python3
"""SAFEHAVEN Module 3 — register a physical wearable and get its enrolment code.

Staff-side counterpart to the device's `enroll` serial command. There is no UI
for this yet, so this script does what that screen will: log in as a clinician,
POST /wearable-devices, and print the one-time enrolment code.

Standard library only — no new dependencies, per the project's house rule.

    python3 scripts/register_device.py --device-code SH-WEAR-001
    # no account yet (development only): create one first, then continue
    python3 scripts/register_device.py --device-code SH-WEAR-001 --create-account
    # or, for a device that is already registered but not yet enrolled
    # (or whose code expired):
    python3 scripts/register_device.py --device-code SH-WEAR-001 --new-code

Then, on the device's serial monitor:  enroll <CODE>

The password is read from SAFEHAVEN_PASSWORD or prompted for, never taken on
the command line (it would land in shell history).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:8000"


def request(method: str, url: str, body: dict | None = None, token: str | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"cannot reach {url}: {exc.reason}\nIs the backend running?"
        ) from exc


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--email", default=os.environ.get("SAFEHAVEN_EMAIL"), help="clinician login")
    p.add_argument("--device-code", required=True, help="the label on the hardware, e.g. SH-WEAR-001")
    p.add_argument("--new-code", action="store_true", help="device exists: mint a fresh enrolment code")
    p.add_argument(
        "--create-account",
        action="store_true",
        help="development only: create a clinician account first (uses POST /auth/register)",
    )
    args = p.parse_args()

    base = args.base_url.rstrip("/")
    email = args.email or input("Clinician email: ").strip()
    if args.create_account:
        full_name = input("Your name: ").strip() or "Bench Clinician"
        password = getpass.getpass("Choose a password (10+ characters): ")
        if password != getpass.getpass("Repeat password: "):
            raise SystemExit("passwords do not match")
        request("POST", f"{base}/auth/register", {"email": email, "password": password, "full_name": full_name})
        print(f"Account created for {email} - use it to log in to the SAFEHAVEN web app too.")
    else:
        password = os.environ.get("SAFEHAVEN_PASSWORD") or getpass.getpass("Password: ")
    token = request("POST", f"{base}/auth/login", {"email": email, "password": password})["access_token"]

    code = args.device_code.strip().upper()
    if args.new_code:
        devices = request("GET", f"{base}/wearable-devices", token=token).get("results", [])
        match = [d for d in devices if d.get("device_code") == code]
        if not match:
            raise SystemExit(f"no registered device with code {code}")
        result = request("POST", f"{base}/wearable-devices/{match[0]['id']}/enrollment-code", token=token)
    else:
        result = request("POST", f"{base}/wearable-devices", {"device_code": code}, token=token)

    print()
    print(f"Device:          {result['device']['device_code']}")
    print(f"Enrolment code:  {result['enrollment_code']}")
    print(f"Expires:         {result['enrollment_expires_at']}  (single use)")
    print()
    print(f"On the device's serial monitor, type:  enroll {result['enrollment_code']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

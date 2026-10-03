"""End-to-end check of a deployed SafeHaven server, from outside it.

Plays a nurse (dashboard API) and a band (device API) against the running
server: sign up, add a patient and a band, pair it, check in, report a fall,
see the alert, ask the voice assistant, report charging. Standard library
only, so it runs from any machine with Python.

    python3 deploy/smoke_test.py http://127.0.0.1:8000 http://127.0.0.1:8080
    python3 deploy/smoke_test.py https://box.tailnet.ts.net:8443 https://box.tailnet.ts.net

Creates test records (a clinician, a patient "Smoke Test", a band
SMOKE-<time>). Run it against a demo server, not one with data you care about.
"""

import json
import sys
import time
import urllib.error
import urllib.request

API, WEB = sys.argv[1].rstrip("/"), sys.argv[2].rstrip("/")
STAMP = str(int(time.time()))
FAILED = []
# Cloudflare answers Python's default "Python-urllib" user agent with 403.
UA = "Mozilla/5.0 (compatible; SafeHaven-smoke-test/1.0)"


def call(method, path, body=None, token=None, raw=False):
    req = urllib.request.Request(API + path, method=method, headers={"User-Agent": UA})
    if body is not None:
        req.data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
            return r.status, (data if raw else json.loads(data or b"null")), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:200], {}


def check(ok, what, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + what + (f"   ({detail})" if detail and not ok else ""))
    if not ok:
        FAILED.append(what)


print(f"SafeHaven smoke test: api {API}, dashboard {WEB}")

# Dashboard is served, and a deep link falls back to the app.
for path in ("/", "/patients"):
    try:
        with urllib.request.urlopen(urllib.request.Request(WEB + path, headers={"User-Agent": UA}), timeout=15) as r:
            check(r.status == 200 and b'id="root"' in r.read(), f"dashboard serves {path}")
    except Exception as e:  # noqa: BLE001
        check(False, f"dashboard serves {path}", str(e))

# Nurse: account, patient, band.
email = f"smoke{STAMP}@example.com"
call("POST", "/auth/register", {"email": email, "password": "supersecret123", "full_name": "Smoke Test"})
code, body, _ = call("POST", "/auth/login", {"email": email, "password": "supersecret123"})
check(code == 200, "clinician can sign in", body)
nurse = body["access_token"] if code == 200 else None
code, patient, _ = call("POST", "/patients", {"first_name": "Smoke", "last_name": "Test", "date_of_birth": "1950-01-01",
                                              "preferred_language": "ENGLISH", "room_number": "101"}, nurse)
check(code in (200, 201), "patient created", patient)
code, reg, _ = call("POST", "/wearable-devices", {"device_code": f"SMOKE-{STAMP}"}, nurse)
check(code in (200, 201), "band registered", reg)

# Band: enrol, get assigned, check in.
code, enrolled, _ = call("POST", "/device-api/enroll", {"enrollment_code": reg["enrollment_code"], "hardware_id": f"HW-{STAMP}"})
check(code == 200, "band enrols", enrolled)
band = enrolled["device_secret"]
code, _, _ = call("POST", f"/patients/{patient['id']}/wearable-assignment",
                  {"device_id": reg["device"]["id"], "monitoring_profile": "FALL_RISK"}, nurse)
check(code in (200, 201), "band assigned to the patient")
code, beat, _ = call("POST", "/device-api/heartbeat", {"battery_percent": 80, "firmware_version": "smoke"}, band)
check(code == 200 and bool(beat.get("assignment")), "band checks in and learns its assignment", beat)

# A fall reaches the nurse.
code, ev, _ = call("POST", "/device-api/events", {"device_event_id": f"smoke-{STAMP}", "event_type": "POSSIBLE_FALL",
                                                  "occurred_at_ms": int(time.time() * 1000),
                                                  "metrics": {"peak_g": 4.2, "fall_score": 4}}, band)
check(code == 201, "band reports a fall", ev)
code, alerts, _ = call("GET", "/safety-alerts", token=nurse)
mine = [a for a in alerts.get("results", []) if a["device_code"] == f"SMOKE-{STAMP}"] if code == 200 else []
check(any(a["alert_type"] == "POSSIBLE_FALL" and a["priority"] == "HIGH" for a in mine), "nurse sees the fall alert (HIGH)")

# The voice assistant answers (typed question, raw band audio back).
t0 = time.time()
code, audio, headers = call("POST", "/device-api/talk?format=pcm", {"text": "What does this band do?"}, band, raw=True)
reply = urllib.request.unquote(headers.get("X-Talk-Reply", headers.get("x-talk-reply", "")))
check(code == 200 and len(audio) > 8000 and reply, "voice assistant answers with speech",
      f"HTTP {code}, {len(audio) if isinstance(audio, bytes) else 0} bytes")
print(f"        reply in {time.time() - t0:.1f} s (server: {headers.get('X-Talk-Timings', headers.get('x-talk-timings', '?'))}): {reply!r}")

# Charging is shown to staff.
call("POST", "/device-api/heartbeat", {"battery_percent": 60, "firmware_version": "smoke", "charging": True}, band)
code, devices, _ = call("GET", "/wearable-devices", token=nurse)
dev = [d for d in devices.get("results", []) if d["device_code"] == f"SMOKE-{STAMP}"] if code == 200 else []
check(bool(dev) and dev[0]["charging"], "charging band shown as charging")

print(f"\nBand {f'SMOKE-{STAMP}'} has now stopped checking in.")
print("RESULT:", "PASS" if not FAILED else f"FAIL ({len(FAILED)}): " + "; ".join(FAILED))
sys.exit(1 if FAILED else 0)

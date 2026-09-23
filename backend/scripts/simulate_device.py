#!/usr/bin/env python3
"""SAFEHAVEN Module 3 — wearable device simulator / event injector.

Stage 0 deliverable (MODULE_3_IMPLEMENTATION_PLAN.md §27). Pretends to be an
M5StickS3 so the whole of Module 3's backend, rules engine and nurse UI can be
built and demonstrated before any hardware arrives.

Standard library only — no new dependencies, per the project's house rule.

The payload shape here is the device -> backend contract and must stay in
lockstep with firmware/include/core/EventJson.h. If you change a field in one,
change it in the other.

PRIVACY: the payload carries device identity and motion metrics only. Never a
patient name, patient_code, DOB, diagnosis or room — the backend resolves
device -> active assignment -> patient on its own (§19).

Typical use
-----------
    # Works today, before any endpoint exists: print what would be sent.
    python3 simulate_device.py --dry-run scenario fall

    # Once Stage 1 exists:
    python3 simulate_device.py enroll --enrollment-code ABC12345
    python3 simulate_device.py --secret "$SECRET" heartbeat
    python3 simulate_device.py --secret "$SECRET" scenario fall

    # False-alert check: 20 fall events in 3s must produce ONE alert (§16).
    python3 simulate_device.py --secret "$SECRET" burst --count 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

DEFAULT_BASE_URL = "http://localhost:8000"
FIRMWARE_VERSION = "0.1.0"

# The five V1 event types. Deliberately short — "do not add dozens of alert
# categories" (§19). DEVICE_OFFLINE is never sent BY a device; the backend
# derives it from a missing heartbeat, so it is not in this list.
EVENT_TYPES = (
    "POSSIBLE_FALL",
    "ABNORMAL_MOVEMENT",
    "UNEXPECTED_MOBILITY",
    "DEVICE_LOW_BATTERY",
)


def empty_metrics() -> dict[str, Any]:
    """Every metrics key the firmware emits, so the contract is identical
    whichever side produced the payload."""
    return {
        "fall_score": 0,
        "peak_g": 0.0,
        "tilt_delta_deg": 0.0,
        "freefall_ms": 0,
        "inactive_ms": 0,
        "duration_s": 0.0,
        "dom_freq_hz": 0.0,
        "magnitude": 0.0,
        "periodicity": 0.0,
        "stages_seen": [],
    }


# Metric values below are taken from an actual run of `make replay` in
# firmware/native, so the simulator reproduces what the real detection core
# produced for the same scenario rather than inventing plausible numbers.
def fall_metrics() -> dict[str, Any]:
    m = empty_metrics()
    m.update(
        fall_score=4,
        peak_g=4.025,
        tilt_delta_deg=90.2,
        freefall_ms=160,
        inactive_ms=2520,
        stages_seen=["freefall", "impact", "orientation", "inactivity"],
    )
    return m


def weak_fall_metrics() -> dict[str, Any]:
    """Impact only — the score the core produces for 'sat down hard'. The
    backend should NOT raise an alert from this; it is here so that rule can be
    tested from the outside."""
    m = empty_metrics()
    m.update(fall_score=1, peak_g=3.0, stages_seen=["impact"])
    return m


def abnormal_metrics() -> dict[str, Any]:
    m = empty_metrics()
    m.update(duration_s=20.0, dom_freq_hz=3.85, magnitude=0.376, periodicity=0.971)
    return m


def mobility_metrics() -> dict[str, Any]:
    m = empty_metrics()
    m.update(duration_s=60.0, dom_freq_hz=2.00, magnitude=0.436, periodicity=1.000)
    return m


@dataclass
class Step:
    """One thing the simulated device does."""

    kind: str  # "event" | "heartbeat" | "wait"
    event_type: str = ""
    metrics: dict[str, Any] = field(default_factory=empty_metrics)
    battery: int = 73
    seconds: float = 0.0
    note: str = ""
    # Seconds subtracted from "now" — used to simulate a queued/delayed event
    # that was detected while the network was down (§18).
    age_seconds: float = 0.0


def scenario_steps(name: str) -> list[Step]:
    """Demo scenarios from §29. Names match the plan's scenario numbering."""
    if name == "normal":
        # Scenario 2. The most important negative case: ordinary movement must
        # produce nothing at all.
        return [
            Step("heartbeat", note="ordinary movement — expect NO alert"),
            Step("wait", seconds=1.0),
            Step("heartbeat"),
        ]
    if name == "fall":
        # Scenario 3.
        return [
            Step("heartbeat", note="baseline"),
            Step(
                "event",
                event_type="POSSIBLE_FALL",
                metrics=fall_metrics(),
                note="full 4-stage sequence — expect ONE high-priority alert",
            ),
        ]
    if name == "weak-fall":
        return [
            Step(
                "event",
                event_type="POSSIBLE_FALL",
                metrics=weak_fall_metrics(),
                note="impact only, score 1 — expect NO alert",
            )
        ]
    if name == "abnormal":
        # Scenario 4.
        return [
            Step(
                "event",
                event_type="ABNORMAL_MOVEMENT",
                metrics=abnormal_metrics(),
                note="sustained 4Hz repetitive movement — no diagnosis in the alert",
            )
        ]
    if name == "mobility":
        # Scenario 5. Requires the assignment to be RESTRICTED_MOBILITY.
        return [
            Step(
                "event",
                event_type="UNEXPECTED_MOBILITY",
                metrics=mobility_metrics(),
                note="sustained gait — expect MEDIUM alert, wording must not say 'left bed'",
            )
        ]
    if name == "lowbattery":
        return [
            Step("heartbeat", battery=18, note="crosses the 20% threshold"),
            Step(
                "event",
                event_type="DEVICE_LOW_BATTERY",
                battery=18,
                note="edge-triggered — repeat heartbeats must not re-alert",
            ),
            Step("heartbeat", battery=17, note="still low — expect NO second alert"),
        ]
    if name == "delayed":
        # Scenario from §18: event detected while offline, delivered late.
        return [
            Step(
                "event",
                event_type="POSSIBLE_FALL",
                metrics=fall_metrics(),
                age_seconds=900,
                note="detected 15 min ago — backend should mark it delayed but still alert",
            )
        ]
    if name == "offline":
        # Scenario 6: the device simply stops. Nothing to send — that is the point.
        return [
            Step("heartbeat", note="last heartbeat before going silent"),
        ]
    raise SystemExit(
        f"unknown scenario {name!r}; choose from: normal, fall, weak-fall, "
        f"abnormal, mobility, lowbattery, delayed, offline"
    )


class DeviceSimulator:
    def __init__(self, base_url: str, secret: str | None, dry_run: bool):
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.dry_run = dry_run
        self.seq = 0
        # Stable per-run prefix so a re-run does not collide with earlier
        # device_event_ids, while a retry inside one run reuses the same id.
        self.run_id = uuid.uuid4().hex[:8]

    def next_event_id(self) -> str:
        self.seq += 1
        return f"{self.run_id}-{self.seq:04d}"

    def _post(self, path: str, body: dict[str, Any]) -> None:
        payload = json.dumps(body, separators=(",", ":"))
        if self.dry_run:
            print(f"  -> POST {path}")
            print(f"     {payload}")
            return

        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self.secret:
            req.add_header("Authorization", f"Bearer {self.secret}")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("utf-8", "replace")
                print(f"  -> POST {path}  [{resp.status}] {text[:200]}")
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            if exc.code == 404:
                print(
                    f"  -> POST {path}  [404] endpoint does not exist yet — "
                    f"this is expected until Stage 1/3 is built"
                )
            else:
                print(f"  -> POST {path}  [{exc.code}] {text[:200]}")
        except urllib.error.URLError as exc:
            raise SystemExit(
                f"cannot reach {self.base_url}: {exc.reason}\n"
                f"start the backend, or use --dry-run to print payloads only"
            ) from exc

    # ── device API calls ───────────────────────────────────────────────────

    def enroll(self, enrollment_code: str, hardware_id: str) -> None:
        print("Enrolling device (one time only)")
        self._post(
            "/device-api/enroll",
            {"enrollment_code": enrollment_code, "hardware_id": hardware_id},
        )
        print(
            "\nThe response contains the device secret exactly once. Save it and "
            "pass it as --secret; it is stored only as a hash and cannot be "
            "retrieved again."
        )

    def heartbeat(self, battery: int) -> None:
        self._post(
            "/device-api/heartbeat",
            {
                "battery_percent": battery,
                "firmware_version": FIRMWARE_VERSION,
                "rssi": -58,
                "sensor_ok": True,
                "queue_depth": 0,
            },
        )

    def send_event(
        self,
        event_type: str,
        metrics: dict[str, Any],
        battery: int,
        age_seconds: float = 0.0,
        event_id: str | None = None,
    ) -> str:
        eid = event_id or self.next_event_id()
        occurred_ms = int((time.time() - age_seconds) * 1000)
        self._post(
            "/device-api/events",
            {
                "device_event_id": eid,
                "event_type": event_type,
                "occurred_at_ms": occurred_ms,
                "battery_percent": battery,
                "firmware_version": FIRMWARE_VERSION,
                "metrics": metrics,
            },
        )
        return eid

    # ── drivers ────────────────────────────────────────────────────────────

    def run_scenario(self, name: str) -> None:
        steps = scenario_steps(name)
        print(f"\nScenario: {name}")
        print("─" * 60)
        for step in steps:
            if step.note:
                print(f"  # {step.note}")
            if step.kind == "wait":
                if not self.dry_run:
                    time.sleep(step.seconds)
                continue
            if step.kind == "heartbeat":
                self.heartbeat(step.battery)
                continue
            self.send_event(
                step.event_type, step.metrics, step.battery, step.age_seconds
            )
        if name == "offline":
            print(
                "\n  Now simply stop. After the configured offline threshold the "
                "backend should derive DEVICE_OFFLINE for this assigned device."
            )
        print()

    def run_burst(self, event_type: str, count: int) -> None:
        """One physical event should never become `count` alerts (§16 layer 4)."""
        print(f"\nBurst: {count} x {event_type} as fast as possible")
        print("─" * 60)
        print("  Expected: exactly ONE alert. Distinct event ids, so this")
        print("  exercises the alert dedupe window, not idempotency.\n")
        for _ in range(count):
            self.send_event(event_type, fall_metrics(), 73)
        print()

    def run_duplicate(self, event_type: str, count: int) -> None:
        """The same device_event_id resent: idempotency (§22)."""
        print(f"\nDuplicate: the SAME device_event_id sent {count} times")
        print("─" * 60)
        print("  Expected: first 201, the rest 200 no-op, exactly ONE alert.\n")
        eid = self.next_event_id()
        for _ in range(count):
            self.send_event(event_type, fall_metrics(), 73, event_id=eid)
        print()


def main() -> int:
    p = argparse.ArgumentParser(
        description="Simulate a SAFEHAVEN wearable device.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--secret", help="per-device credential from enrolment")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print payloads without sending; works before the API exists",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("enroll", help="one-time device enrolment")
    e.add_argument("--enrollment-code", required=True)
    e.add_argument("--hardware-id", default="SIM-" + uuid.uuid4().hex[:12])

    h = sub.add_parser("heartbeat", help="send one heartbeat")
    h.add_argument("--battery", type=int, default=73)

    s = sub.add_parser("scenario", help="run a named demo scenario")
    s.add_argument(
        "name",
        choices=[
            "normal",
            "fall",
            "weak-fall",
            "abnormal",
            "mobility",
            "lowbattery",
            "delayed",
            "offline",
        ],
    )

    b = sub.add_parser("burst", help="many distinct events fast (dedupe test)")
    b.add_argument("--type", dest="event_type", default="POSSIBLE_FALL",
                   choices=EVENT_TYPES)
    b.add_argument("--count", type=int, default=20)

    d = sub.add_parser("duplicate", help="resend one event id (idempotency test)")
    d.add_argument("--type", dest="event_type", default="POSSIBLE_FALL",
                   choices=EVENT_TYPES)
    d.add_argument("--count", type=int, default=3)

    args = p.parse_args()

    if args.cmd != "enroll" and not args.secret and not args.dry_run:
        print(
            "warning: no --secret given; the device API will reject this. "
            "Use --dry-run to just print payloads.",
            file=sys.stderr,
        )

    sim = DeviceSimulator(args.base_url, args.secret, args.dry_run)

    if args.cmd == "enroll":
        sim.enroll(args.enrollment_code, args.hardware_id)
    elif args.cmd == "heartbeat":
        sim.heartbeat(args.battery)
    elif args.cmd == "scenario":
        sim.run_scenario(args.name)
    elif args.cmd == "burst":
        sim.run_burst(args.event_type, args.count)
    elif args.cmd == "duplicate":
        sim.run_duplicate(args.event_type, args.count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

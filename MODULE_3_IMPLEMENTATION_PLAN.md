# Module 3 — Wearable Patient-Safety Monitoring

**Status: DESIGN / PLAN ONLY. Nothing in this document has been implemented.**

Written after direct inspection of the current repository (not from prior documentation), plus
official-source verification of the candidate hardware. Every claim about existing code cites a
real path. Section markers follow house style: ✅ already built and reusable · ⚠️ gap found ·
🆕 new scope · ❗ correction to the brief.

Module 3 is the first module with a hardware component, the first with a real-time requirement,
and the first whose trigger data does not come from a clinician's keyboard. Those three firsts are
where the risk is concentrated.

---

## 0. ❗ Corrections to the brief

The brief asked me not to trust it. Six things in it are wrong or need adjusting. Listed first
because two of them change the plan's shape.

| # | Brief said | Actual | Impact |
|---|---|---|---|
| 1 | "Verify the M5StickS3 — do not assume it exists" | **It exists and is current.** `M5StickS3`, $21.50, in stock. It is the vendor-sanctioned replacement for the **now-EOL** M5StickC PLUS2 | None — your device choice is correct. My initial skepticism was unfounded |
| 2 | "Do not automatically infer... room" (implied room may be missing) | `Patient.room_number` **already exists** (`app/patients/models.py`). `ARCHITECTURE_REVIEW.md §10` says "room, if added" — it has since been added | Alert cards can show room with zero schema work |
| 3 | Wearable QR "may eventually resolve into the existing Module 2 workflow" | `ARCHITECTURE_REVIEW.md §4/§10` and `MODULE_2_FREEZE_REPORT.md §8` state Module 3 "should **not** depend on Module 2 at all" | **Module 2 interop is dropped from V1.** See §11 |
| 4 | Implies a background scheduler for offline detection | **No scheduler, no Redis, no Celery, no APScheduler, and `main.py` has no `lifespan` hook at all** | Offline detection is computed on read instead. See §17 |
| 5 | Suggests WebSocket/SSE for real-time | Real-time is possible with zero new deps, but the app is **sync SQLAlchemy** and in-process push **silently breaks with >1 uvicorn worker** (no Redis for fan-out) | **Polling recommended for V1.** See §21 |
| 6 | "Buzzer/speaker if available" | StickS3 has **no simple buzzer**. It has a full ES8311 codec + AW8737 amp + speaker. The EOL PLUS2 had the simple buzzer | Audio is a WAV/I2S task, not a `tone()` call. Slightly more firmware work |

One further correction to my own earlier assumption, recorded because it affects §19: the audit
table's `event_type` is a `String(64)`, **not** a native Postgres enum — new event types need no
migration. But a guard test fails the build if an event type has no frontend label
(`DOCUMENTATION.md §3.6`).

---

## 1. ✅ Current reusable SAFEHAVEN infrastructure

Verified by inspection, not from documentation.

| Piece | Location | Reusable for Module 3? |
|---|---|---|
| `Patient` (UUID PK, `patient_code`, `room_number`, `admission_status`) | `app/patients/models.py` | ✅ Directly. Identity + room for alert cards |
| `Encounter` (`status` OPEN/CLOSED, `admission_date`) | `app/encounters/models.py` | ✅ As assignment context |
| `record_event()` + `AuditEventType` | `app/audit/service.py`, `models.py` | ✅ Exactly as-is. Do not build a second audit system |
| **Hashed opaque bearer token pattern** | `app/patient_access/` | ✅ **The single most important reuse.** Copy wholesale for device credentials — see §9 |
| `get_current_user` JWT dependency | `app/auth/dependencies.py` | ✅ For all staff endpoints |
| Orchestration layer (cross-module ops) | `app/orchestration/patient_ops.py` | ✅ The one discharge extension point |
| `slowapi` rate limiter | `app/core/rate_limit.py` | ✅ Apply to the device API |
| Boot-time config validators | `app/core/config.py` | ✅ Pattern for new Module 3 settings |
| Sync `Session` / `Base` / `get_db` | `app/core/db.py` | ✅ Follow exactly. No async path exists |
| pytest + real-Alembic test schema | `backend/tests/conftest.py` | ✅ Including the savepoint-rollback `db_session` fixture |
| react-query, shadcn/ui, Tailwind, `sonner` toast, `lucide-react` | `frontend/` | ✅ Everything the alert UI needs already present |
| `@zxing/browser` QR scanner + generic `ScanOrManualEntry` | `frontend/src/components/BarcodeScanner.tsx`, `features/medication-verification/` | ✅ If staff-side scanning is ever needed |
| `websockets` 17.1 + `starlette` 0.46.2 | installed transitively via `uvicorn[standard]` | ✅ Available — but see §21 for why V1 should not use it |

### ⚠️ Gaps that Module 3 is the first to hit

| Gap | Evidence | Consequence |
|---|---|---|
| No real-time/push anything | Zero matches for `websocket\|EventSource\|StreamingResponse` in `app/` **and** `frontend/src` | §21 must introduce the first mechanism |
| No background task/scheduler of any kind | No Celery/APScheduler/Redis/cron; `main.py` has no `lifespan` | §17 must avoid needing one |
| No role checks anywhere | `User.role` is stored and never branched on in any router | Any "who may assign a device" rule is the first RBAC in the codebase |
| No `qrcode` Python library, and no new deps allowed | Absent from `requirements.txt` and `.venv` | QR must be rendered **on the device**, not server-side. See §11 |
| No audible alert capability | No `<audio>`/Web Audio usage in `frontend/src` | New, but needs no dependency |
| `AuditEventType.PATIENT_DISCHARGED` exists but is **never emitted** | `patient_ops.update_patient` only emits token-revocation events | Module 3 should not hang logic off a discharge audit event |
| `Patient.admission_status` and `Encounter.status` are **independent, unlinked** state machines | Nothing wires them together | Assignment lifecycle must pick one as authoritative — see §10 |

---

## 2. Module 3 product definition

> A reusable low-cost wrist wearable samples motion locally, sends only compact candidate-event
> summaries over Wi-Fi to SAFEHAVEN, which resolves the device to its currently assigned patient,
> applies deterministic rules, and raises a prioritised nurse alert that describes what was
> *observed* — never a diagnosis.

---

## 3. Requirements

### Functional
1. Staff enrol a physical device once; it receives an individually revocable credential.
2. Staff assign/unassign a device to a patient with a monitoring profile (`STANDARD`, `FALL_RISK`, `RESTRICTED_MOBILITY`).
3. Device detects candidate events locally and uploads compact summaries.
4. Backend resolves `device → active assignment → patient → room/encounter`.
5. Deterministic rules produce `SafetyAlert` rows with a priority.
6. Nurse dashboard surfaces open alerts within a few seconds, with audible + visual notification.
7. Nurse acknowledges and resolves alerts; both actions audited.
8. Device health (battery, last-seen) is visible; a silently-offline assigned device raises an alert.
9. Device survives temporary Wi-Fi loss without losing events, without duplicating them.
10. Discharge ends the assignment and invalidates the assignment token.
11. Device returns to a safe `UNASSIGNED` state and is reusable.

### Non-functional
| Requirement | Target | Rationale |
|---|---|---|
| Event → nurse visible | ≤ 5 s p95 | Brief says "a few seconds"; polling at 3 s meets this |
| New Python/JS dependencies | **Zero** | House rule, verified against `requirements.txt` / `package.json` |
| New infrastructure services | **Zero** | Repo runs one Postgres in docker-compose, nothing else |
| Module 1 / Module 2 files changed | **Zero** | See §5 of both freeze reports |
| PHI transmitted by device | **None** | Device sends `device_id` + motion metrics only |
| PHI in QR payload | **None** | Opaque token only |
| Duplicate alerts from one physical event | **0** | Idempotency + cooldown, §16 |
| Detection logic requiring an LLM | **None** | Module 3 V1 is deterministic end-to-end |

### Explicit non-goals
No camera, no video, no diagnosis (no seizure/medication-reaction/neurological claim), no ECG,
no SpO2, no continuous vitals, no indoor GPS, no BLE gateway, no MQTT broker, no Kafka, no
Kubernetes, no ML classifier, no FHIR device integration, no raw-telemetry data lake, no fleet
management.

---

## 4. Hardware requirements (minimum capability)

| # | Capability | Why it is required |
|---|---|---|
| H1 | 2.4 GHz Wi-Fi station | Chosen transport (§7) |
| H2 | 6-axis IMU (accel + gyro) | Orientation change is a required fall-sequence stage (§13) |
| H3 | Accel range ≥ ±8 g | A fall impact saturates ±2 g; a saturated signal cannot be staged |
| H4 | Accel ODR ≥ 100 Hz | Impact spikes are ~tens of ms |
| H5 | Display | `UNASSIGNED` vs `ACTIVE` state + QR (§11) |
| H6 | Internal battery + USB-C charge | Reusable, no wiring at bedside |
| H7 | ≥ 1 programmable button | Local acknowledge / enrolment trigger |
| H8 | Audible or haptic output | Device-side confirmation (nice-to-have, not required) |
| H9 | Per-device secure credential storage | §9 forbids a shared global key |
| H10 | Wrist-wearable size/weight | Worn for hours |
| H11 | Currently purchasable, low cost | Prototype must be orderable now |
| H12 | **No camera** | Fixed product constraint |

---

## 5. Hardware validation — M5StickS3

Verified against `docs.m5stack.com/en/core/StickS3`, `shop.m5stack.com`, `docs.espressif.com`,
and the Bosch BMI270 datasheet (rev 1.6).

**❗ The brief's device name is correct.** `M5StickS3` is real, current, and in stock at **$21.50**.
It is the successor to the **M5StickC PLUS2, which M5Stack has marked EOL** with its store page
redirecting to the StickS3. If any older spec doc names the PLUS2, update it.

Beware family-name inference: `M5StampS3` and `M5NanoC6` are genuine M5Stack products with
**no IMU and no display** — they do not meet H2 or H5 despite the similar naming.

### Verdict per requirement

| # | Requirement | Verdict | Detail |
|---|---|---|---|
| H1 | 2.4 GHz Wi-Fi | ✅ SUPPORTED | ESP32-S3-PICO-1-N8R8, 2.4 GHz only |
| H1b | **WPA2-Enterprise** | ⚠️ **UNCERTAIN** | Supported in ESP-IDF (`esp_eap_client_*`, EAP-TLS/PEAP/TTLS) but **not exposed by Arduino/M5Unified defaults**. Needs code-level work + a test against the real RADIUS server. **This is the #1 hardware-adjacent risk** |
| H2 | 6-axis IMU | ✅ SUPPORTED | **BMI270** (Bosch), accel + gyro, I2C |
| H3 | ≥ ±8 g | ✅ SUPPORTED | ±2/4/8/16 g configurable — **configure ±16 g** |
| H4 | ≥ 100 Hz ODR | ✅ SUPPORTED | BMI270 accel ODR up to 1.6 kHz |
| H5 | Display | ✅ SUPPORTED | 1.14" TFT, 135×240, ST7789P3, colour |
| H5b | **QR scannable on that display** | ⚠️ **UNCERTAIN — NEEDS REAL-HARDWARE TEST** | 135 px ÷ 29 modules ≈ 4.7 px/module ≈ **0.49 mm/module**. Marginal-but-plausible at 3–6 cm. Requires short payload (QR v1–2), high contrast, no glare. **Do not assume from pixel maths** |
| H6 | Battery + USB-C | ✅ SUPPORTED | **250 mAh**, USB-C charge/program |
| H6b | **Runtime** | ⚠️ **UNCERTAIN — vendor publishes none** | Estimate **~1.5–3 h** continuous Wi-Fi + IMU; ~4–6 h with modem-sleep/duty-cycling. A full nursing shift is **not** achievable. See §32 R1 |
| H7 | Buttons | ✅ SUPPORTED | 2 programmable (KEY1/KEY2) |
| H8 | Audible output | ✅ SUPPORTED (differently) | ES8311 codec + AW8737 amp + 8 Ω speaker + MEMS mic. **No simple buzzer** — I2S audio, more firmware work than `tone()` |
| H9 | Secure credential storage | ✅ SUPPORTED (SoC-internal) | Secure Boot v2 (RSA-3072), Flash Encryption (AES-XTS), **NVS Encryption**, HW crypto, eFuse unique ID |
| H9b | Discrete secure element | ❌ **NOT SUPPORTED** | No ATECC608-class chip on any candidate. Acceptable for a prototype; would need an external I2C part for a compliance claim |
| H10 | Wrist-wearable | ✅ SUPPORTED (size) | 48×24×15 mm, 20 g |
| H10b | **Official wrist strap for this exact SKU** | ⚠️ **UNCERTAIN** | "Stick Watch Accessory Kit" pictures the **PLUS2** and says "M5Stick devices" generically; StickS3 not named. Dimensions differ by 1.5 mm so likely fits — **physical fit-check required** |
| H11 | Current + low cost | ✅ SUPPORTED | $21.50, in stock, not EOL |
| H12 | No camera | ✅ SUPPORTED | No camera on this SKU |

### Alternatives considered
| Device | Verdict |
|---|---|
| **M5AtomS3R** ($17.50) | Better sensors (BMI270 + BMM150), smaller — but **no battery and no strap**. Only if building a custom enclosure |
| M5StickC PLUS2 | **EOL — do not spec** |
| M5StampS3 / M5NanoC6 | No IMU, no display. Not candidates |
| Seeed XIAO ESP32-S3 Sense | Has a camera (violates H12), no integrated display/IMU/battery in base kit |

**Conclusion: M5StickS3 is suitable for the prototype.** Buy **two** (one worn, one bench/spare).
Two capability claims must not be made until hardware is in hand: **battery runtime** and
**QR scan reliability**.

---

## 6. 🆕 Device architecture (firmware modules)

One generic firmware image for every device. No per-patient build. Patient identity arrives only
via backend assignment.

| Module | Responsibility |
|---|---|
| `DeviceIdentity` | eFuse hardware ID; load/store credential in encrypted NVS; factory-reset |
| `WifiManager` | SoftAP provisioning portal, connect, exponential-backoff reconnect, RSSI |
| `TimeSync` | SNTP; monotonic-clock fallback so queued events keep correct `occurred_at` |
| `SensorSampler` | BMI270 at fixed ODR into a ring buffer; feeds detectors only |
| `DetectionCore` | **Pure, platform-free logic** — `FallDetector`, `MovementDetector`, `MobilityDetector` |
| `EventQueue` | Bounded persistent FIFO (see §18) |
| `ApiClient` | TLS, bearer credential, JSON POST, retry, clock-skew tolerance |
| `ConfigStore` | Backend-pushed thresholds, profile, heartbeat interval |
| `DisplayUI` | State screens: `PROVISIONING` / `UNASSIGNED` / `ACTIVE` / `OFFLINE` / `LOW BATTERY` |
| `QrRenderer` | Renders assignment token as QR (§11) |
| `PowerMonitor` | Battery %, low-battery threshold crossing |
| `StateMachine` | Top-level device state; guarantees a safe `UNASSIGNED` state |

`DetectionCore` contains **no** `#include <M5*>`, no Wi-Fi, no display calls. That is what makes
§26 and §25 possible.

---

## 7. 🆕 Wi-Fi architecture

**Prototype decision: direct device → hospital Wi-Fi → backend. No phone/tablet/BLE gateway.**
The brief's reasoning holds: a ward with many patients should not depend on one phone maintaining
many BLE sessions.

But the brief asked me not to assume Wi-Fi is automatically correct for production. Honest evaluation:

| Dimension | Assessment |
|---|---|
| **Scalability** | ✅ Fine. Sparse events + one heartbeat/30–60 s. A 30-bed ward is a trivial load for one FastAPI process. Wi-Fi *association* count, not bandwidth, is the real ward-level constraint |
| **Hospital network restrictions** | ⚠️ **The biggest production risk.** Real hospital SSIDs typically need WPA2-Enterprise (802.1X) + MDM/NAC registration. ESP-IDF supports it; Arduino/M5Unified does not expose it by default. Medical-device VLANs often need per-MAC allowlisting — an IT process, not a code change |
| **Provisioning** | ⚠️ SoftAP captive portal is fine for a prototype; it does not scale to 200 devices and it puts Wi-Fi credentials through a browser form. Production wants bulk provisioning/MDM |
| **Battery** | ❌ **Wi-Fi is the dominant cost.** ~1.5–3 h continuous vs. days for BLE. Mitigate with modem-sleep + duty-cycled reporting; do not claim shift-length runtime |
| **Roaming** | ⚠️ ESP32 roaming between APs is workable but not seamless; expect brief drops. §18's queue is the mitigation, not an optimisation |
| **Temporary loss** | ✅ Handled by design (§18) |
| **Security** | ✅ TLS + per-device credential (§9). Device must validate the server cert — pin a CA bundle, do not use `setInsecure()` |

**Recommendation: direct Wi-Fi for the prototype — no serious blocker. State plainly in any demo
that battery life and WPA2-Enterprise onboarding are the two unresolved production questions.**

---

## 8. 🆕 Communication protocol — HTTPS REST for V1

| | HTTPS REST | MQTT over TLS |
|---|---|---|
| New backend dependency | **None** | `paho-mqtt` — **not installed, not allowed** |
| New infrastructure | **None** | A broker (Mosquitto/EMQX) — breaks the one-Postgres rule |
| Fits existing FastAPI router pattern | ✅ One `include_router` line | ❌ Separate consumer process |
| Reuses `get_db`, `record_event`, `slowapi` | ✅ Directly | ⚠️ Needs re-plumbing |
| Idempotency | Natural (§22) | Needs QoS reasoning |
| Efficiency at scale | Weaker (per-request TLS) | Better (persistent session) |
| Backend → device push | Needs polling | Native subscribe |

**Recommendation: HTTPS REST.** MQTT's advantages are all scale advantages this prototype does not
have, and it requires both a forbidden dependency and a forbidden service. Assignment changes reach
the device by **piggybacking on the heartbeat response** (§20) — no push needed.

Keep `ApiClient` behind an interface (§26) so MQTT stays a firmware-side swap later.

---

## 9. 🆕 Device security model

**Copy `app/patient_access/` almost verbatim.** It is already exactly the right shape: an
unguessable secret held by something at the bedside that is not a logged-in clinician, stored only
as a SHA-256 hash, individually revocable.

**Do not use JWT for devices.** `DevAuthProvider`'s JWTs have no denylist and are not revocable —
the brief requires independent revocability.

### Enrolment (one time per physical device)

```
Staff creates device record in SAFEHAVEN UI  (device_code = "SH-WEAR-001")
        ↓
backend mints a short single-use enrollment_code, short TTL, stored hashed
        ↓
device in factory state → SoftAP portal → staff enters Wi-Fi creds + enrollment_code
        ↓
device POSTs /device-api/enroll { enrollment_code, hardware_id }   [TLS]
        ↓
backend: code unused? unexpired? hardware_id unseen?
        ↓
backend generates device_secret = secrets.token_urlsafe(32)   (256-bit)
  stores ONLY sha256(device_secret); marks enrollment_code consumed
        ↓
returns raw device_secret EXACTLY ONCE  →  device writes to encrypted NVS
```

Thereafter every device call carries `Authorization: Bearer <device_secret>`; the backend does a
single indexed `sha256` lookup.

### Backend must verify on every device request
1. Credential hash exists → else 401
2. `device.status == ACTIVE` → else 401
3. (For event submission) an active assignment exists → else accept-and-discard (§20)

All four failure reasons return an **identical generic 401**, matching
`InvalidCareAccessTokenError`'s deliberate design so probing cannot distinguish them.

### Revocation / rotation
| Action | Mechanism |
|---|---|
| Revoke one device | `status = DISABLED`, null the hash. Other devices unaffected |
| Rotate | Re-enrol; old hash overwritten |
| Lost device | Revoke + end assignment |

Compromise of `SH-WEAR-001` never affects any other device — the brief's requirement, satisfied
structurally.

### Boundary rules (all three auth types stay separate)
| Actor | Credential | Endpoints |
|---|---|---|
| Clinician | JWT (`get_current_user`) | `/wearable-devices/*`, `/safety-alerts/*` |
| Patient | care-link token | `/care-plan*` (untouched) |
| **Device** | **per-device secret** | **`/device-api/*`** |

A device credential must never be accepted on a staff route, and vice versa. Apply `slowapi` limits
to `/device-api/*`. Add a boot-time validator rejecting a placeholder device-API TLS setting, mirroring
`_reject_placeholder_jwt_secret`.

**Not overbuilt:** no PKI, no client certificates, no CA. Deliberate — flagged in §33 as revisitable.

---

## 10. 🆕 Patient assignment lifecycle

```
WearableDevice(status=ACTIVE)  +  Patient(admission_status=ACTIVE)
        ↓  staff picks monitoring_profile
DeviceAssignment row created  (unassigned_at = NULL  ⇒  ACTIVE)
        ↓  assignment_token minted, hash stored
device learns of assignment on next heartbeat → renders QR, shows ACTIVE
        ↓
        ├── staff unassigns  ─┐
        └── patient discharged ┤
                               ↓
        unassigned_at = now(); assignment token hash nulled
        device's next heartbeat returns assignment=null → clears QR → UNASSIGNED
        old SensorEvents / SafetyAlerts / audit rows retained
```

Design decisions, each with a reason:

- **`active` is derived, not stored.** `unassigned_at IS NULL` is the single source of truth. A
  stored boolean would be a second one that can disagree. (The brief proposed an `active` column —
  I recommend against it.)
- **Two partial unique indexes** enforce the invariants in the database, not just in Python:
  `WHERE unassigned_at IS NULL` on `device_id`, and the same on `patient_id`. One active assignment
  per device; one per patient.
- **`Patient.admission_status` is authoritative for discharge**, not `Encounter.status`. Those two
  are currently unlinked (§1) and `admission_status` is what the discharge path actually sets.
  `encounter_id` is recorded as context only.
- **Discharge auto-unassigns.** Recommended over requiring staff confirmation: the brief asks for
  the safer prototype behaviour, and a device still believing it monitors a discharged patient is
  the worse failure. It exactly mirrors the existing `revoke_all_tokens_for_patient` cascade, and
  goes in the **same** `if data.admission_status == DISCHARGED:` branch in
  `app/orchestration/patient_ops.py::update_patient` — the only discharge extension point that exists.

### Monitoring profiles
| Profile | POSSIBLE_FALL | ABNORMAL_MOVEMENT | UNEXPECTED_MOBILITY |
|---|---|---|---|
| `STANDARD` | ✅ | ✅ | ❌ |
| `FALL_RISK` | ✅ (priority escalated) | ✅ | ❌ |
| `RESTRICTED_MOBILITY` | ✅ (priority escalated) | ✅ | ✅ |

`UNEXPECTED_MOBILITY` fires **only** on explicit `RESTRICTED_MOBILITY` configuration — never
inferred from a diagnosis or procedure name. This also satisfies `ARCHITECTURE_REVIEW.md §10`:
a MOBILITY `CareInstruction` may be displayed as context on an alert, but is **never** a trigger input.

---

## 11. 🆕 Dynamic QR design

### Recommendation: **(B) auxiliary identifier. The hospital wristband stays authoritative.**

Three independent reasons:
1. `US_HOSPITAL_MARKET_STANDARDS_GAP_ANALYSIS.md` item 1 — one identifier is not sufficient for
   clinical action; Joint Commission requires two. A wearable QR cannot replace the wristband.
2. A wearable is removable and reassignable. A wristband is not. The more mutable identifier must
   not be the authoritative one.
3. The brief's own rule: do not create two conflicting patient identities.

### ❗ Module 2 interoperability is dropped from V1

The brief suggests the QR might later resolve into Module 2's medication flow. The repo forbids it:
`MODULE_2_FREEZE_REPORT.md §8` — Module 3 "should **not** depend on Module 2 at all."

There is also a concrete trap. Module 2's scanner resolves a raw `patient_code` string
(`"P1001"`) via `get_patient_by_code`. So:

- If the wearable QR contained `patient_code`, Module 2 would work **unchanged** — but a patient
  identifier would then be rendered on a device display, and the wearable would have become a second
  bedside identity. Rejected.
- If it contains an **opaque token** (correct per the brief), Module 2 could not resolve it without
  changing Module 2. Forbidden.

**Therefore V1: the QR encodes an opaque assignment token, and Module 2 is not touched.** Note in
§33 as a future decision.

### Payload
```
Contents:  an opaque, high-entropy assignment token — nothing else
Example:   SH:a7Fq2LmXpZ...        (short prefix + token, QR version 1–2)
Never:     name · DOB · MRN · diagnosis · medications · patient_code · room
Lifetime:  bound to the assignment; invalid the moment unassigned_at is set
Resolution: POST /wearable-assignments/resolve  (staff JWT only)
```
The token is stored hashed, exactly like the credential. A scanned token resolves **server-side**
to the patient; the QR itself carries no meaning to anyone without SAFEHAVEN access.

Short payload is also a hardware necessity, not just a privacy one — §5 H5b shows the display only
supports a low-version QR.

### Display states
| Device state | Screen |
|---|---|
| `UNASSIGNED` | `SAFEHAVEN` / `UNASSIGNED` / no QR |
| `ACTIVE` | `SAFEHAVEN` / `MONITORING` / QR |
| `OFFLINE` | `ACTIVE` + a no-network indicator (QR stays — assignment is still valid) |

**Recommended safest display: render the QR and no human-readable patient identifier at all.**
The brief floats showing `P1001*`; I recommend against it. It provides nothing the QR does not, and
turns a glanceable wrist device into a patient identifier readable by every visitor in the room.
If staff need human confirmation, they scan.

**❗ QR is generated on-device.** No `qrcode` library exists in the backend and none may be added;
a firmware QR library is required instead (new firmware dependency — §33 D6).

---

## 12. 🆕 Sensor pipeline

```
BMI270 @ 50 Hz, ±16 g                      ← range set so impacts don't saturate
        ↓
ring buffer (a few seconds, on-device)
        ↓
feature extraction per window: |a|, jerk, variance, dominant frequency, tilt delta
        ↓
┌───────────────────────────────────────────────┐
│  normal movement  →  NOTHING SENT             │   ← the default path, by design
└───────────────────────────────────────────────┘
        ↓ candidate event only
compact JSON event (~200 bytes; no raw stream)
        ↓  HTTPS POST  /device-api/events
backend: authenticate → resolve assignment → deterministic rules → dedupe → SafetyAlert
        ↓
nurse dashboard
```

**No continuous raw IMU upload.** Optionally, a short pre/post-event window (~2 s, decimated) may be
attached to a fall event for debugging, behind a config flag, **off by default**.

Heartbeats are **not** stored as `SensorEvent` rows — they update `WearableDevice.last_seen_at` and
`battery_percent` in place. Storing one row per device per 30 s would be exactly the historical
sensor-data lake the brief forbids.

---

## 13. 🆕 Fall detection V1 — state machine

Not a single threshold. A **sequence within a bounded window**.

```
STATE IDLE
  on each sample window:
    if |a| < FREEFALL_G  for >= FREEFALL_MS:        → CANDIDATE_FREEFALL   (start timer)
    elif |a| > IMPACT_G:                             → CANDIDATE_IMPACT     (freefall not required)
    else: stay IDLE

STATE CANDIDATE_FREEFALL                              (timeout FREEFALL_WINDOW_MS → IDLE)
    if |a| > IMPACT_G:                               → CANDIDATE_IMPACT

STATE CANDIDATE_IMPACT                                (timeout IMPACT_WINDOW_MS → IDLE)
    record tilt_before (pre-impact), begin post-window
    if |tilt_now - tilt_before| > ORIENT_DEG:        → CANDIDATE_SETTLED
    elif post-window elapsed:                        → CANDIDATE_SETTLED (orientation unconfirmed)

STATE CANDIDATE_SETTLED
    observe INACTIVITY_WINDOW_MS
    inactive = variance(|a|) < INACTIVITY_VAR for >= INACTIVITY_MS

    score = (freefall_seen ? 1:0) + (impact_seen ? 1:0)
          + (orientation_changed ? 1:0) + (inactive ? 1:0)     # impact always 1 here

    if score >= MIN_FALL_SCORE (default 3):
        emit POSSIBLE_FALL { score, peak_g, tilt_delta_deg,
                             freefall_ms, inactive_ms, stages_seen[] }
        → COOLDOWN(FALL_COOLDOWN_S)
    else:
        → IDLE                                        # deliberately silent
```

A **score**, not a rigid all-stages-required chain: the brief notes not every stage will be reliably
observable on a wrist. Score + `stages_seen[]` also gives the backend and any reviewer the evidence
behind the alert rather than a bare boolean — the Module-3 analogue of Module 2's
`checks: {passed, detail}` structure.

Prototype starting values, **all configurable, none medically validated**:

| Constant | Default | Note |
|---|---|---|
| `FREEFALL_G` | 0.4 g | Wrist free-fall is short and shallow |
| `FREEFALL_MS` | 80 ms | |
| `IMPACT_G` | 2.5 g | Needs real-hardware tuning |
| `ORIENT_DEG` | 45° | |
| `INACTIVITY_MS` | 1500 ms | |
| `MIN_FALL_SCORE` | 3 | Raise to 4 if false positives dominate |
| `FALL_COOLDOWN_S` | 60 s | |

> **Every threshold here is an engineering guess for a prototype. None is clinically validated, and
> the alert wording must never imply otherwise.**

---

## 14. 🆕 Abnormal repetitive movement V1 — state machine

Deliberately a **separate** algorithm; a fall is a transient, this is a persistence problem.

```
rolling window ABN_WINDOW_S (default 10 s), evaluated every 1 s

  magnitude  = mean(| |a| - 1g |)
  variance   = var(|a|)
  dom_freq   = dominant frequency of |a| in 1–8 Hz band
  periodicity= autocorrelation peak at dom_freq

  window_is_abnormal =
        magnitude  > ABN_MAG
    AND variance   > ABN_VAR
    AND dom_freq  in [ABN_FMIN, ABN_FMAX]      (default 2–6 Hz)
    AND periodicity > ABN_PERIODICITY          (rhythmic, not random)

STATE IDLE
    if window_is_abnormal: → ACCUMULATING (consecutive = 1)

STATE ACCUMULATING
    if window_is_abnormal: consecutive += 1
    else: consecutive -= 1; if consecutive <= 0 → IDLE     # decay, not instant reset

    if consecutive * 1s >= ABN_SUSTAIN_S (default 20 s):
        if NOT gait_like(window):                          # see exclusions
            emit ABNORMAL_MOVEMENT { duration_s, dom_freq, magnitude, periodicity }
            → COOLDOWN(ABN_COOLDOWN_S, default 300 s)
```

### Required exclusions (the brief's explicit list)
| Confounder | Guard |
|---|---|
| **Normal walking** | `gait_like()`: 1.4–2.5 Hz + strong vertical periodicity + progressive tilt → suppress. Walking is *more* rhythmic than the target signal, so periodicity alone cannot separate them — frequency band + tilt progression must |
| Adjusting blanket, brushing teeth | `ABN_SUSTAIN_S` = 20 s; these are shorter or non-periodic |
| Normal arm movement | Magnitude + periodicity floors |
| **Device removed / shaken / handled** | Very high magnitude + erratic tilt + no orientation stability → classify `DEVICE_HANDLING`, suppress. Also suppress within 60 s of an assignment change |

**Wording is fixed: "Abnormal repetitive movement detected — patient check recommended."**
Never "seizure", never "medication reaction", never any diagnosis. This is a hard product rule and
should be enforced by a test asserting the alert-label table contains no diagnostic term.

---

## 15. 🆕 Unexpected mobility V1 — state machine and limitations

### ⚠️ State the limitation first

**A wrist IMU alone cannot prove a patient left a bed.** It sees arm motion. A patient reaching for
a cup and a patient standing up produce overlapping wrist signatures. Sustained walking-like gait is
the *one* reasonably separable signal, and even that is inferential.

Consequences, all deliberate:
- Alert wording is **"Unexpected mobility detected — assistance may be required."**
  Never "patient left bed."
- Only enabled for explicit `RESTRICTED_MOBILITY`.
- Priority `MEDIUM` by default, not `HIGH` — an inferential signal should not outrank a fall.

```
enabled only if assignment.monitoring_profile == RESTRICTED_MOBILITY

rolling window MOB_WINDOW_S (default 15 s)

  gait_score = periodicity in 1.4–2.5 Hz          (step cadence band)
  upright    = tilt consistent with vertical forearm
  sustained  = gait_score > MOB_GAIT for >= MOB_SUSTAIN_S (default 30 s)

STATE RESTING
    if sustained AND upright:  → CANDIDATE_MOBILITY

STATE CANDIDATE_MOBILITY
    re-confirm over MOB_CONFIRM_S (default 15 s)      # second look, cheap
    if still sustained:
        emit UNEXPECTED_MOBILITY { gait_score, duration_s, cadence_hz }
        → COOLDOWN(MOB_COOLDOWN_S, default 600 s)
    else: → RESTING
```

If real-hardware testing shows wrist gait detection is unreliable, the honest options are to raise
`MOB_SUSTAIN_S`, or to defer the feature — **not** to loosen the wording. Recorded in §33 as D4.

---

## 16. 🆕 False-positive controls

`DOCUMENTATION.md §7` rule 6: *"An alert that fires on correct work is a safety problem, because it
teaches people to click through."* Fall detection is notoriously false-positive-prone, so this is
Module 3's central design problem, not a finishing touch.

Five layers, device → backend:

| Layer | Where | Mechanism |
|---|---|---|
| 1. Sequence/persistence requirement | Device | Multi-stage score (§13); sustain windows (§14/§15). Single spikes never alert |
| 2. Per-detector cooldown | Device | No re-emit of the same type within `*_COOLDOWN_S` |
| 3. Idempotency | Backend | `UNIQUE (device_id, device_event_id)` — retries can never duplicate (§22) |
| 4. **Alert-level dedupe window** | Backend | If an **OPEN or ACKNOWLEDGED** alert of the same `alert_type` exists for the patient within `ALERT_DEDUPE_S` (default 120 s), attach the event to it and **do not** create a second alert |
| 5. Suppression on state change | Backend | Discard events with no active assignment, for discharged patients, or within 60 s of assignment change (handling artefacts) |

Layers 3 and 4 are distinct and both necessary: 3 stops *one* event arriving twice; 4 stops *twenty
genuinely different* events from one physical fall becoming twenty alerts — the brief's explicit
"20 identical alerts in 3 seconds" requirement.

Dedupe intentionally keys on `OPEN or ACKNOWLEDGED`, not just `OPEN`: a nurse who has acknowledged
and is walking to the room should not get a fresh alert for the same ongoing episode.

Precedent for the window approach: `MODULE_2_EDGE_CASE_REVIEW.md §6`'s duplicate-administration
window.

---

## 17. 🆕 Device health

```
every HEARTBEAT_S (default 30 s):
  POST /device-api/heartbeat { battery_percent, firmware_version, rssi, sensor_ok, queue_depth }
        ↓
  UPDATE wearable_devices SET last_seen_at = now(), battery_percent = ..., firmware_version = ...
        ↓
  response: { assignment: {...} | null, config: {...} }      ← how assignments reach the device
```

### ❗ Offline detection without a scheduler

There is no scheduler, no `lifespan` hook, and no Redis. Rather than introduce the codebase's first
background worker, **offline status is derived on read**:

```
device_is_offline  ⇔  last_seen_at < now() - OFFLINE_AFTER_S   (default 120s)
```

Because the nurse dashboard polls every ~3 s (§21), **the poll is the sweep**. On any alert-list
read, any assigned device found newly offline gets a `DEVICE_OFFLINE` alert persisted (subject to
§16 layer 4), so the transition is recorded rather than merely displayed.

Trade-off, stated plainly: if nobody has the dashboard open, a `DEVICE_OFFLINE` row is created late
(on next read) though `last_seen_at` still shows the true time. For a prototype that is a fair
exchange for adding zero infrastructure. A `lifespan` asyncio sweep is the Stage-11 upgrade if
needed (§29).

| Signal | Trigger | Alert type |
|---|---|---|
| Low battery | `battery_percent <= LOW_BATTERY_PCT` (default 20), edge-triggered | `DEVICE_LOW_BATTERY` |
| Offline | derived, assigned devices only | `DEVICE_OFFLINE` |
| Sensor failure | `sensor_ok == false` | `DEVICE_OFFLINE` (same nurse action: check the device) |

Edge-triggered, not level-triggered — otherwise every heartbeat at 19% re-alerts.

---

## 18. 🆕 Network failure handling

```
event detected
   ↓
POST → success?  ── yes →  done
   ↓ no
append to bounded persistent queue (NVS/flash ring, MAX_QUEUE = 50)
   ↓
if full: drop the OLDEST NON-FALL event first; never drop a POSSIBLE_FALL
   ↓
on reconnect: drain oldest-first, ORIGINAL occurred_at preserved
   ↓
backend: if (received_at - occurred_at) > DELAYED_AFTER_S (300s) → delayed = true
```

| Protection | Mechanism |
|---|---|
| Infinite storage | Hard cap 50 events; fall events have drop priority |
| Duplicate delivery | `(device_id, device_event_id)` uniqueness (§22) — queue may safely resend |
| Stale events | `delayed` flag; UI labels them "delayed — detected HH:MM, received HH:MM" |
| Reconnect flood | Exponential backoff with jitter (1 s → 60 s cap); drain rate-limited |
| Clock skew | SNTP at boot; monotonic offset if SNTP unavailable; backend records both timestamps |

A delayed fall event must still create an alert — clearly marked. Suppressing it would lose a real
safety signal; presenting it as current would mislead.

---

## 19. 🆕 Backend data model — minimum additions

Four new tables. Every proposal in the brief was checked against existing models first.

Conventions confirmed from the repo and followed exactly: **UUID PKs** with `default=uuid.uuid4`,
`DateTime(timezone=True)`, **no `relationship()`** (this codebase queries by explicit FK filters),
**no mixins**, no soft delete, explicit `index=True`.

#### `wearable_devices`
| Column | Type | Note |
|---|---|---|
| `id` | UUID PK | |
| `device_code` | String(32) unique idx | `SH-WEAR-001` |
| `status` | Enum `ACTIVE/DISABLED/RETIRED` native | Revocation switch |
| `credential_hash` | String(64) unique idx nullable | sha256; NULL = not enrolled/revoked |
| `hardware_id` | String(64) nullable | eFuse ID, binds credential to silicon |
| `enrollment_code_hash` | String(64) nullable | Single-use, hashed |
| `enrollment_expires_at` | timestamptz nullable | |
| `firmware_version` | String(32) nullable | |
| `battery_percent` | SmallInteger nullable | |
| `last_seen_at` | timestamptz nullable idx | Drives offline derivation |
| `created_by` | UUID FK users.id | |
| `created_at` / `updated_at` | timestamptz | |

#### `device_assignments`
| Column | Type | Note |
|---|---|---|
| `id` | UUID PK | |
| `device_id` | UUID FK idx | |
| `patient_id` | UUID FK idx | |
| `encounter_id` | UUID FK nullable | Context only |
| `monitoring_profile` | Enum `STANDARD/FALL_RISK/RESTRICTED_MOBILITY` native | Gates §15 |
| `assignment_token_hash` | String(64) unique idx nullable | QR token; nulled on unassign |
| `assigned_by` / `assigned_at` | UUID FK / timestamptz | |
| `unassigned_by` / `unassigned_at` | UUID FK nullable / timestamptz nullable | **NULL ⇒ active** |

Two **partial unique indexes** (`WHERE unassigned_at IS NULL`) on `device_id` and on `patient_id`.
No `active` boolean — see §10.

#### `sensor_events`
| Column | Type | Note |
|---|---|---|
| `id` | UUID PK | |
| `device_id` | UUID FK idx | |
| `assignment_id` | UUID FK nullable idx | NULL if unassigned at receipt |
| `device_event_id` | String(64) | Device-supplied |
| `event_type` | String(32) idx | |
| `occurred_at` / `received_at` | timestamptz | Both, always |
| `metrics` | JSONB | Motion metrics only — **never PHI** |
| `delayed` | Boolean default false | |

**`UNIQUE (device_id, device_event_id)`** — the idempotency guarantee. Heartbeats are **not** stored here.

#### `safety_alerts`
| Column | Type | Note |
|---|---|---|
| `id` | UUID PK | |
| `patient_id` | UUID FK idx | |
| `device_id` | UUID FK idx | |
| `sensor_event_id` | UUID FK nullable | NULL for derived `DEVICE_OFFLINE` |
| `alert_type` | String(32) idx | |
| `priority` | Enum `LOW/MEDIUM/HIGH` native | |
| `status` | Enum `OPEN/ACKNOWLEDGED/RESOLVED` native idx | Three states only |
| `created_at` | timestamptz idx | |
| `acknowledged_by` / `acknowledged_at` | UUID FK nullable / timestamptz nullable | |
| `resolved_by` / `resolved_at` | UUID FK nullable / timestamptz nullable | |

`DISMISSED` is **not** included — the brief called it "maybe"; `RESOLVED` covers it and a fourth
state invites ambiguity about whether anyone checked the patient.

Composite index `(status, created_at)` for the dashboard query.

### Changes to existing tables: **none**
`Patient.room_number` already exists. New `AuditEventType` members need **no migration** (it is a
`String(64)` column) — but **must** get frontend labels or the guard test fails the build.

### ❗ Correction made during Stage 2: `assignment_token_hash` deferred to Stage 10

The `device_assignments` table above listed `assignment_token_hash`. It was **not** built in
Stage 2, because implementing it exposed a flaw in the design above.

The device must **receive the raw token** in order to render the QR, and the heartbeat response is
the only channel to it. A stored hash cannot be served to the device, so hashing the assignment
token as originally specified makes the feature impossible.

The token is also not the same kind of secret as a device credential: per §11 it resolves to a
patient only for a caller holding a **clinician JWT**, so it is an opaque *identifier*, not a
bearer credential. Hashing therefore buys much less than it does for `credential_hash` — an
attacker with database access already has the patients.

Likely resolution in Stage 10: store the token in plaintext, keep it opaque and high-entropy, and
null it on unassignment (which still satisfies "old QR invalid immediately"). Deferred rather than
guessed, so an unused security-relevant column is not shipped on a design that is still open.

### Event types (V1, exactly five + one internal)
`POSSIBLE_FALL` · `ABNORMAL_MOVEMENT` · `UNEXPECTED_MOBILITY` · `DEVICE_LOW_BATTERY` ·
`DEVICE_OFFLINE` · (internal) `DEVICE_HEARTBEAT`

### Severity mapping
| Alert | Priority | Reasoning |
|---|---|---|
| `POSSIBLE_FALL` | **HIGH** | Highest-consequence observable event |
| `ABNORMAL_MOVEMENT` | **HIGH** if `FALL_RISK`/`RESTRICTED_MOBILITY`, else **MEDIUM** | Profile-driven, per brief |
| `UNEXPECTED_MOBILITY` | **MEDIUM** | Most inferential signal (§15) — must not outrank a fall |
| `DEVICE_OFFLINE` while assigned | **HIGH** | A silently-dead safety monitor is a safety event |
| `DEVICE_LOW_BATTERY` | **LOW** | Operational |

These are **operational priorities, not clinical severities** — nothing here claims medical acuity.

---

## 20. 🆕 API design

### Device API — `/device-api/*`, per-device credential, rate-limited
| Method | Path | Purpose |
|---|---|---|
| POST | `/device-api/enroll` | One-time; enrollment code → device secret (returned once) |
| POST | `/device-api/heartbeat` | Health in; **assignment + config out** |
| POST | `/device-api/events` | Submit candidate event(s); idempotent |

Three endpoints. No device-facing read of patient data — the device never learns who it monitors.

Request (`/device-api/events`) — note the absence of any PHI:
```json
{ "device_event_id": "a1b2-0007", "event_type": "POSSIBLE_FALL",
  "occurred_at": "2026-09-23T10:43:02Z",
  "metrics": { "score": 4, "peak_g": 3.1, "tilt_delta_deg": 62,
               "freefall_ms": 110, "inactive_ms": 1800,
               "stages_seen": ["freefall","impact","orientation","inactivity"] },
  "battery_percent": 73, "firmware_version": "0.1.0" }
```
Responses: `201` created · `200` duplicate (idempotent no-op) · `202` accepted-and-discarded
(no active assignment) · `401` generic auth failure.

### Staff API — clinician JWT (`get_current_user`)
| Method | Path | Purpose |
|---|---|---|
| GET | `/wearable-devices` | Fleet list + derived online/offline |
| POST | `/wearable-devices` | Register; returns enrollment code |
| POST | `/wearable-devices/{id}/revoke` | Revoke credential |
| GET | `/patients/{patient_id}/wearable-assignment` | Current assignment for the panel |
| POST | `/patients/{patient_id}/wearable-assignment` | Assign (device + profile) |
| DELETE | `/patients/{patient_id}/wearable-assignment` | Unassign |
| GET | `/safety-alerts?status=OPEN` | **Dashboard poll target** |
| POST | `/safety-alerts/{id}/acknowledge` | Acknowledge |
| POST | `/safety-alerts/{id}/resolve` | Resolve |
| POST | `/wearable-assignments/resolve` | Opaque QR token → patient |
| GET | `/patients/{patient_id}/safety-events` | Per-patient history panel |

Package shape follows every other module exactly: `models.py` / `schemas.py` / `service.py` /
`router.py`, plus **two** routers (device + staff) and two `include_router` lines in `main.py`.

---

## 21. 🆕 Real-time alert delivery — recommendation: **short polling for V1**

This is the brief's most consequential open question, and the answer is not the intuitive one.

| Option | Verdict |
|---|---|
| **Short polling** (`refetchInterval: 3000` on an existing react-query `useQuery`) | ✅ **Recommended.** ~3 s latency; **zero** new deps; zero new server code; survives multi-worker deployment; matches the documented "views are fetched, not pushed" convention |
| **SSE** (`StreamingResponse`) | ⚠️ Possible, no new deps — but `EventSource` **cannot send an `Authorization` header**, forcing the clinician JWT into a query string (logged by proxies). Needs a sync-generator bridge against sync SQLAlchemy |
| **WebSocket** (`@app.websocket`) | ⚠️ `websockets` 17.1 is already installed, so no new dep — but browser WebSocket also can't set headers, needs `run_in_threadpool` for every sync DB call, and adds connection lifecycle management |
| MQTT / Kafka / Redis pub-sub | ❌ Forbidden: new dependency **and** new infrastructure |

**The decisive argument is deployment, not elegance.** Any in-process push (SSE or WebSocket)
broadcasts from a single process's memory. Run uvicorn with `--workers 2` and a nurse connected to
worker A silently never receives an alert ingested by worker B. Fixing that needs Redis pub/sub —
a forbidden dependency and a forbidden service. **Polling reads Postgres, so it is correct under any
worker count.** A real-time mechanism that silently drops patient-safety alerts under a standard
deployment flag is worse than a 3-second poll.

Also honest: 3 s polling of `GET /safety-alerts?status=OPEN` with an index on `(status, created_at)`
is a trivial query. At ward scale this is not a performance concern.

Upgrade path (Stage 11, only if measured need): add SSE behind the **same** react-query cache keys,
with the token-in-query-string problem solved by a short-lived single-purpose stream token (the
`patient_access` pattern again). Polling stays as the fallback.

Audible alert: fire `sonner` toast + a short Web Audio beep on a newly-seen HIGH alert id. No
dependency needed. Must be user-gesture-unlocked (browser autoplay policy) — a "sound on" affordance
at dashboard load.

---

## 22. Idempotency

```
device assigns device_event_id (monotonic per device, persisted across reboot)
        ↓
UNIQUE (device_id, device_event_id)
        ↓
INSERT ... ON CONFLICT DO NOTHING   → if conflict: return 200, create NO alert
```
Retry, queue-drain, and duplicate delivery are therefore all safe by construction, not by
convention. Paired with §16 layer 4 for physical-event-level dedupe.

---

## 23. Nurse UI — minimum surface

Follows `src/pages/*Page.tsx` + `src/features/<domain>/` + `src/api/<domain>.ts` conventions, reusing
the established status palette (`emerald` ok · `amber` warning · `destructive` critical).

| # | Component | Location | Purpose |
|---|---|---|---|
| 1 | `SafetyAlertsPage` | `src/pages/` | Cross-patient open-alert queue, polled. **This is also the fix for the "single biggest remaining usability gap"** named in `DOCUMENTATION.md §13` |
| 2 | `SafetyAlertCard` | `src/features/safety-monitoring/` | Type, patient, `patient_code`, room, time, device, `[View Patient]` `[Acknowledge]` |
| 3 | `AlertPriorityBadge` | `src/features/safety-monitoring/` | Copies `StatusBadge.tsx`'s `Record<Enum, classes>` pattern |
| 4 | `WearableDevicePanel` | `src/features/safety-monitoring/` | On `PatientDetailPage` — assign/unassign, profile, battery, online |
| 5 | `AssignDeviceDialog` | `src/features/safety-monitoring/` | shadcn dialog; available devices + profile select |
| 6 | `SafetyEventHistoryPanel` | `src/features/safety-monitoring/` | New tab on `PatientDetailPage`, mirroring `AdministrationHistoryPanel` |
| 7 | Nav entry + global alert listener | `src/components/AppLayout.tsx` | "Safety Monitoring" link with open-HIGH count badge; toast + beep on new HIGH |

Wording is fixed in one place (`src/features/safety-monitoring/labels.ts`) so no diagnostic phrasing
can leak in:
```
POSSIBLE_FALL        → "Possible fall detected — check patient."
ABNORMAL_MOVEMENT    → "Abnormal repetitive movement detected — patient check recommended."
UNEXPECTED_MOBILITY  → "Unexpected mobility detected — assistance may be required."
DEVICE_OFFLINE       → "Safety monitor offline — device check required."
DEVICE_LOW_BATTERY   → "Wearable battery low."
```
No diagnosis anywhere. No alert shows a medical cause.

---

## 24. Audit integration

Reuse `record_event()` exactly — same signature, same inline-call-at-business-boundary pattern,
`db.add` without commit so the audit row shares the caller's transaction.

New `AuditEventType` members (granular, per `MODULE_2`'s precedent of one type per state change —
not one generic `ALERT`):

```
WEARABLE_DEVICE_REGISTERED      WEARABLE_DEVICE_ENROLLED     WEARABLE_DEVICE_REVOKED
WEARABLE_DEVICE_ASSIGNED        WEARABLE_DEVICE_UNASSIGNED
SAFETY_EVENT_RECEIVED           SAFETY_ALERT_RAISED
SAFETY_ALERT_ACKNOWLEDGED       SAFETY_ALERT_RESOLVED
WEARABLE_DEVICE_OFFLINE_DETECTED
```

| Rule | Application |
|---|---|
| No migration needed | `event_type` is `String(64)` |
| **Frontend label required** | Guard test fails the build otherwise — `DOCUMENTATION.md §3.6` |
| `event_metadata` never carries PHI, raw tokens, or token hashes | Store `device_code`, `alert_type`, `priority`, metric summary only |
| `actor_type` | `CLINICIAN` for assign/ack/resolve; **`SYSTEM`** for device-originated and derived-offline events |

Device-originated events use `actor_type=SYSTEM` with `actor_id=NULL` — the existing convention used
by `revoke_all_tokens_for_patient`.

---

## 25. Discharge integration

Exactly one code site: the existing `if data.admission_status == AdmissionStatus.DISCHARGED:` branch
in `app/orchestration/patient_ops.py::update_patient`, alongside `revoke_all_tokens_for_patient`.

```
patient discharged
   ↓  (same transaction, commit=False, same as the care-token cascade)
end active DeviceAssignment    → unassigned_at = now(), unassigned_by = SYSTEM
null assignment_token_hash     → QR invalid immediately
resolve OPEN device-health alerts for that patient   (keep clinical alerts for the record)
record_event(WEARABLE_DEVICE_UNASSIGNED, actor_type=SYSTEM)
   ↓
device's next heartbeat returns assignment=null → clears QR → UNASSIGNED
```

**Automatic, not staff-confirmed** — reasoning in §10. Historical `SensorEvent`, `SafetyAlert` and
audit rows are retained; only the *active* association ends.

⚠️ Note for whoever implements this: `AuditEventType.PATIENT_DISCHARGED` exists in the enum but is
**never actually emitted**. Do not hang Module 3 logic on that audit event — extend the `if` branch
directly.

---

## 26. Hardware adapter design

`DetectionCore` must compile and run **unchanged** on host and on device. Four interfaces:

```cpp
struct ISensorProvider { virtual bool read(ImuSample& out) = 0; };   // real BMI270 | replayed CSV
struct IDisplayProvider{ virtual void render(const DeviceScreen&) = 0; }; // ST7789 | stdout/PNG
struct INetworkProvider{ virtual PostResult post(const char* path, const char* json) = 0; };
struct IClock         { virtual uint64_t millis() = 0; virtual uint64_t epochMs() = 0; };
struct IStorage       { virtual bool put(k,v) = 0; virtual bool get(k,&v) = 0; }; // NVS | file
```

| | Device build | Host build |
|---|---|---|
| Sensor | BMI270 over I2C | CSV/synthetic replay (fast-forwardable) |
| Display | ST7789 TFT | Text dump / PNG snapshot |
| Network | `WiFiClientSecure` + HTTPS | `libcurl`/stub against local FastAPI |
| Clock | `millis()` + SNTP | Virtual clock — 10 min of motion in 1 s |
| Storage | Encrypted NVS | Temp file |

PlatformIO with two environments (`env:m5sticks3`, `env:native`) building the **same**
`DetectionCore` sources. Porting to different hardware later replaces only adapters.

The virtual clock matters more than it looks: §14 needs 20 s sustain and §15 needs 30 s — testing
those at real time makes the suite unusably slow.

---

## 27. Simulation plan — how much can be built before hardware arrives

**Answer: essentially all of the backend and frontend, and the detection algorithms. Roughly 80% of
Module 3.**

Three simulation layers, in order of value:

| Layer | What it enables | Limitation |
|---|---|---|
| **1. Python event injector** (`backend/scripts/simulate_device.py`) — a script that enrols a fake device and POSTs scripted event sequences | **Every backend + frontend + demo scenario.** Stages 1–5 and 7–10 need no firmware at all | Proves nothing about firmware or real motion |
| **2. Native host build** of `DetectionCore` fed CSV/synthetic traces | Algorithm correctness, threshold tuning, regression vectors for §13–§15 | Synthetic motion is not real wrist motion |
| **3. Wokwi** generic ESP32-S3 + Wi-Fi | Firmware structure, Wi-Fi/HTTPS path, display layout | See limitations below |

### ❗ Verified simulator limitations
| Limitation | Detail |
|---|---|
| **No M5StickS3 board in Wokwi** | No M5Stack board definitions exist. Use a generic ESP32-S3 board and fake the chassis |
| **No BMI270 (or MPU6886) part in Wokwi** | Only `wokwi-mpu6050` — a *different* IMU. Register behaviour and noise differ |
| **Wokwi Wi-Fi/HTTPS works — through Wokwi's gateway** | ⚠️ **Traffic traverses a third-party gateway. Use synthetic patient data only.** Never point Wokwi at an instance holding real data |
| **QEMU has no Wi-Fi at all** | Espressif's official QEMU fork does not emulate Wi-Fi/BT for any target. Its OpenCores-Ethernet workaround exercises a different network path than real firmware |

### Cannot be simulated anywhere — real hardware required
Real BMI270 noise/drift; battery discharge curve and brown-out under Wi-Fi TX bursts; display
contrast/glare and **actual QR scan success with a real phone**; Wi-Fi roaming, RSSI reassociation,
and WPA2-Enterprise/RADIUS handshake; 2.4 GHz congestion; strap comfort and impact robustness.

**Therefore:** Stages 0–5 and 7–10 proceed now with layers 1–2. Stage 6 (real hardware) is the only
one that blocks on delivery, and no capability claim about battery, QR, or detection accuracy is made
until it completes.

---

## 28. Test plan

Backend tests follow `tests/conftest.py` exactly: real Alembic migrations, savepoint-rollback
`db_session`, real `POST /auth/register` + `/auth/login` for tokens (auth is not mocked here).
Every new model needs a real migration or the suite's schema build diverges from the ORM.

### Backend — unit (`tests/unit/`), no DB
| # | Test |
|---|---|
| 1 | Fall state machine: valid 4-stage sequence → candidate |
| 2 | Fall: impact only, score below `MIN_FALL_SCORE` → **silent** |
| 3 | Fall: free-fall with no impact → silent |
| 4 | Abnormal movement: 25 s rhythmic 4 Hz → candidate |
| 5 | Abnormal movement: 10 s burst → silent (below sustain) |
| 6 | Abnormal movement: **walking gait 2 Hz → suppressed** |
| 7 | Abnormal movement: device-handling signature → suppressed |
| 8 | Mobility: sustained gait + `RESTRICTED_MOBILITY` → candidate |
| 9 | Mobility: identical trace + `STANDARD` → **no event** |
| 10 | Offline derivation boundary (just inside / just outside) |
| 11 | Severity mapping table, per profile |
| 12 | Label table contains no diagnostic term (guard test) |

### Backend — integration (`tests/integration/`)
| # | Test |
|---|---|
| 13 | Enrolment: valid code → secret once; replay of same code → 401 |
| 14 | Event with valid credential → 201 + alert |
| 15 | Unknown / revoked / `DISABLED` credential → **generic 401, indistinguishable** |
| 16 | Staff JWT rejected on `/device-api/*`; device secret rejected on staff routes |
| 17 | Event with no active assignment → 202, no alert |
| 18 | Event for discharged patient → no alert |
| 19 | **Duplicate `device_event_id` → 200, exactly one alert** |
| 20 | 20 fall events in 3 s → **exactly one alert** (dedupe window) |
| 21 | Acknowledge → status + `acknowledged_by/at` + audit row |
| 22 | Resolve → audit row |
| 23 | Heartbeat updates `last_seen_at`/`battery`; returns assignment |
| 24 | Heartbeat creates **no** `sensor_events` row |
| 25 | Low battery edge-triggered: one alert, not one per heartbeat |
| 26 | Offline detection creates `DEVICE_OFFLINE` for assigned device only |
| 27 | Delayed event (old `occurred_at`) → `delayed=true`, alert still created |
| 28 | Assignment: second active assignment for same device → rejected (partial unique index) |
| 29 | Same for same patient |
| 30 | Discharge → assignment ended, token hash nulled, audit written |
| 31 | **Old QR token after unassign → resolves to nothing** |
| 32 | Reassign device to new patient → new token; no active link to old patient |
| 33 | `event_metadata` contains no PHI and no token/hash (guard test) |
| 34 | Every new `AuditEventType` has a frontend label (extends existing guard test) |
| 35 | No PATCH/DELETE route exists on alerts (mirrors existing audit immutability test) |

### Firmware / simulation
Native `DetectionCore` build run against recorded + synthetic traces, sharing **the same numeric
vectors** as tests 1–9 so host and device logic cannot silently diverge. Plus: queue overflow drops
non-fall first; reboot preserves `device_event_id` monotonicity; backoff timing.

### Frontend
TypeScript strict typecheck; Playwright against the real backend driven by the event injector:
alert appears within poll interval, badge count updates, acknowledge round-trips, assign/unassign,
delayed-event labelling. No LLM anywhere in Module 3's test path.

---

## 29. Implementation order

Adjusted from the brief's suggested order for three repo-specific reasons: device health moves
**before** hardware (it is needed for the offline demo and needs no device); QR moves late (it is
gated on an unverified hardware capability); and a hardening stage is added because §16 is the
module's central risk.

| Stage | Scope | Blocks on hardware? |
|---|---|---|
| **0** | Simulation foundation: event injector, adapter interfaces, native build, trace fixtures | No |
| **1** | Device registry + enrolment + credential auth + `/device-api` boundary + rate limit | No |
| **2** | Assignment + profiles + partial unique indexes + discharge cascade | No |
| **3** | Event ingestion + idempotency + assignment resolution + audit | No |
| **4** | Fall rules + dedupe/cooldown + severity mapping | No |
| **5** | Nurse UI: alerts page, cards, polling, toast + beep, acknowledge/resolve | No |
| **6** | Device health: heartbeat, battery, derived offline | No |
| **7** | **Real hardware bring-up**: firmware on M5StickS3, Wi-Fi, real IMU, threshold tuning | **Yes** |
| **8** | Abnormal movement + gait/handling exclusions | Tuning only |
| **9** | Unexpected mobility + `RESTRICTED_MOBILITY` gating | Tuning only |
| **10** | Dynamic QR: token mint/invalidate, on-device render, staff resolve | Partly (H5b) |
| **11** | Hardening: edge-case pass, false-positive tuning, offline-queue soak, optional SSE | Partly |

**A complete demo of Scenarios 1–4, 6 and 7 is reachable at the end of Stage 6 with no hardware at all.**

---

## 30. Estimated time — one developer

| Stage | Estimate |
|---|---|
| 0 — Simulation foundation | 1.5 d |
| 1 — Device registry + auth | 2 d |
| 2 — Assignment + discharge | 1.5 d |
| 3 — Event ingestion | 1.5 d |
| 4 — Fall rules | 1.5 d |
| 5 — Nurse UI | 2.5 d |
| 6 — Device health | 1 d |
| **Subtotal — full software demo, no hardware** | **~11.5 d (~2.5 weeks)** |
| 7 — Real hardware bring-up | 3 d |
| 8 — Abnormal movement | 1.5 d |
| 9 — Unexpected mobility | 1 d |
| 10 — Dynamic QR | 1.5 d |
| 11 — Hardening | 2 d |
| **Total** | **~20.5 d (~4 working weeks)** |

Excluded from the estimate and genuinely uncertain: WPA2-Enterprise onboarding (could be an hour or
could be weeks of hospital IT process — §32 R2); real-world threshold tuning, which is empirical and
open-ended; enclosure/strap fabrication.

---

## 31. Files and folders to change

### New — backend
| Path | Purpose | Size |
|---|---|---|
| `backend/app/wearables/models.py` | 4 models + enums | MEDIUM |
| `backend/app/wearables/schemas.py` | Device + staff request/response | MEDIUM |
| `backend/app/wearables/service.py` | Enrolment, assignment, ingestion, rules, dedupe | **LARGE** |
| `backend/app/wearables/detection.py` | Backend-side deterministic rules + severity | MEDIUM |
| `backend/app/wearables/device_router.py` | `/device-api/*` | SMALL |
| `backend/app/wearables/router.py` | Staff endpoints | MEDIUM |
| `backend/app/wearables/dependencies.py` | `get_current_device` credential dependency | SMALL |
| `backend/alembic/versions/xxxx_add_wearable_tables.py` | 4 tables + partial unique indexes | MEDIUM |
| `backend/scripts/simulate_device.py` | Event injector | MEDIUM |
| `backend/tests/unit/test_wearable_detection.py` | Tests 1–12 | MEDIUM |
| `backend/tests/integration/test_wearables.py` | Tests 13–35 | **LARGE** |

### New — firmware (new top-level `firmware/`)
| Path | Purpose | Size |
|---|---|---|
| `firmware/platformio.ini` | `env:m5sticks3` + `env:native` | SMALL |
| `firmware/src/core/` | `DetectionCore`, detectors, `EventQueue`, `StateMachine` | **LARGE** |
| `firmware/src/hal/` | Interfaces + device/host adapters | MEDIUM |
| `firmware/src/main_device.cpp` | Device entry point | MEDIUM |
| `firmware/src/main_native.cpp` | Host simulator entry point | SMALL |
| `firmware/test/` | Native tests + shared trace vectors | MEDIUM |

### New — frontend
| Path | Purpose | Size |
|---|---|---|
| `frontend/src/api/safety-monitoring.ts` | `apiRequest` wrappers | SMALL |
| `frontend/src/types/safety-monitoring.ts` | Types | SMALL |
| `frontend/src/pages/SafetyAlertsPage.tsx` | Alert queue | MEDIUM |
| `frontend/src/features/safety-monitoring/*` | 6 components + `labels.ts` | **LARGE** |

### Modified — existing (deliberately minimal)
| Path | Change | Size |
|---|---|---|
| `backend/app/main.py` | 2 imports + 2 `include_router` | SMALL |
| `backend/app/models.py` | Import new models for `Base.metadata` | SMALL |
| `backend/app/audit/models.py` | ~10 new `AuditEventType` members | SMALL |
| `backend/app/orchestration/patient_ops.py` | Extend the existing discharge `if` branch | SMALL |
| `backend/app/core/config.py` | Module 3 settings + boot validator | SMALL |
| `backend/.env.example` | New settings documented | SMALL |
| `frontend/src/App.tsx` | 1 route | SMALL |
| `frontend/src/components/AppLayout.tsx` | Nav link + badge + global alert listener | MEDIUM |
| Frontend audit-label map | Labels for new event types (**guard test**) | SMALL |

### ✅ No changes anywhere in
`app/instructions/` · `app/medication_verification/` · `app/reference/` · `app/ai/` ·
`app/validation/` · `app/patient_access/` · `app/patients/` · `app/encounters/` ·
`app/conditions/` · `app/allergies/` · `app/tts/` · `frontend/src/features/medication-verification/` ·
`BarcodeScanner.tsx`

**No Module 1 file changes. No Module 2 file changes. No new Python or JS dependencies.**

---

## 32. Risks

| # | Risk | Severity | Mitigation / honest position |
|---|---|---|---|
| **R1** | **Battery life ~1.5–3 h with continuous Wi-Fi** — far short of a nursing shift | **HIGH** | Modem-sleep, duty-cycled heartbeat, longer intervals. **Accept and disclose**: a 250 mAh wearable streaming over Wi-Fi is a demo device, not a shift device. Do not claim otherwise |
| **R2** | **Hospital WPA2-Enterprise onboarding** — needs ESP-IDF-level EAP, plus IT/NAC/MAC-allowlist process | **HIGH** | Prototype on a dedicated/lab SSID. Treat enterprise auth as a spike, not a task. Schedule-dominant unknown |
| **R3** | **Wrist IMU false positives** — sitting hard, dropping the device, rolling over | **HIGH** | Five layers (§16), score threshold, real-trace tuning. `DOCUMENTATION.md §7` rule 6 makes this a safety issue, not a polish issue |
| **R4** | **Bed-exit cannot be proven from a wrist** | **HIGH** | Wording capped at "unexpected mobility." §15 states the limit explicitly rather than implying capability |
| **R5** | Device credential extractable from flash | MEDIUM | Secure Boot v2 + Flash + NVS encryption; per-device revocable secret. No secure element exists on this hardware — stated, not hidden |
| **R6** | **QR unscannable at 0.49 mm/module** | MEDIUM | Short payload (v1–2), max contrast, close-range UX. **Unverified until hardware arrives**; fallback is staff entering `device_code` via the existing `ScanOrManualEntry` |
| **R7** | Enclosure/strap: StickS3 not named on the strap accessory page | MEDIUM | Physical fit-check on arrival; 3D-printed cradle as fallback |
| **R8** | Sensor placement — wrist is worst-case for falls (hip/trunk is better) | MEDIUM | Accept for V1; note trunk placement as the accuracy upgrade path |
| **R9** | Offline queue: delayed alerts arriving as if current | MEDIUM | `delayed` flag + explicit UI labelling of both timestamps |
| **R10** | Derived offline detection is late when nobody watches the dashboard | MEDIUM | Accepted trade for zero infrastructure; `last_seen_at` stays truthful. `lifespan` sweep is the Stage-11 upgrade |
| **R11** | **Wokwi traffic crosses a third-party gateway** | MEDIUM | **Synthetic data only in simulation.** Never point Wokwi at real data |
| **R12** | Polling at 3 s gives ~3 s worst-case latency | LOW | Within the "few seconds" requirement; SSE upgrade documented |
| **R13** | **Philosophical tension**: "AI proposes, code decides, a clinician approves" assumes clinician-entered structured input. Sensor inference has no `compare_facts()` equivalent | **HIGH (framing)** | Module 3's analogue is the **multi-stage score** (§13) — evidence-based and inspectable, not an opaque classifier. `stages_seen[]` is carried into the alert so the basis is always auditable. **No ML in V1.** This must be stated explicitly in any review |
| **R14** | Repo currently has extensive **uncommitted changes** on `main` (single "Initial commit") | LOW | Commit/branch before starting Module 3 so its diff is reviewable |

---

## 33. Decisions required from you

### ✅ Resolved 2026-09-23

| # | Decision | Outcome |
|---|---|---|
| **D1** | Real-time delivery | **Polling (3 s).** Chosen as the option least likely to cause trouble later: it is correct under any uvicorn worker count, whereas in-process SSE/WebSocket silently drops alerts under `--workers 2`. The SSE upgrade path in §21 keeps this from being a dead end |
| **D2** | Module 2 / QR interop in V1 | **Dropped from V1.** The hospital wristband remains the authoritative bedside identity; the wearable QR is a SAFEHAVEN-auxiliary mechanism only. §11 |
| **D6** | Firmware QR library | **Accepted.** The "no new dependencies" rule governs the Python/JS repo, not the new `firmware/` tree |
| **D9** | Firmware location | **This repo, top-level `firmware/`** |

### Still open

| # | Decision | My recommendation |
|---|---|---|
| **D3** | **Does discharge auto-unassign, or require staff confirmation?** | **Auto-unassign**, mirroring the existing care-token cascade. A device believing it monitors a discharged patient is the worse failure. §25 |
| **D4** | **Keep `UNEXPECTED_MOBILITY` in V1 given a wrist cannot prove bed-exit?** | **Keep it**, `MEDIUM` priority, `RESTRICTED_MOBILITY` only, wording capped at "unexpected mobility." Defer if hardware testing shows gait detection is unreliable. §15 |
| **D5** | **Buy hardware now?** | **Yes — two M5StickS3 ($43 total).** Stages 0–6 don't need it, but Stage 7 tuning is the long pole and R1/R6 stay unresolved until it's in hand |
| **D7** | **Is an audible browser alert acceptable in your demo environment?** | Include it, default-on with a visible mute. Needs a user gesture to unlock audio |
| **D8** | **Who may assign a device / acknowledge an alert?** | **Any authenticated clinician for V1.** No role check exists anywhere in the codebase; adding the first RBAC is out of scope. Flag as a known gap |

**D3, D4, D5, D7 and D8 do not block Stage 0** — they are needed by Stages 2, 9, 7, 5 and 1
respectively. Stage 0 can begin on the resolved decisions alone.

---

## 34. Final go / no-go

**Is the current SAFEHAVEN architecture ready for Module 3?**
**Yes, with two named firsts.** Patient/Encounter identity, `record_event()`, the hashed-opaque-token
credential pattern, the orchestration discharge hook, sync SQLAlchemy conventions, and the test
harness are all directly reusable, and `Patient.room_number` already exists. Module 3 is the first
feature to need **real-time delivery** and the first to need **background-ish periodic work** — §21
and §17 solve both with **zero new dependencies and zero new services** by polling and by deriving
offline status on read. The module cleanly honours "shared patient data + separate safety engines":
it touches no Module 1 or Module 2 file and never reads medication data as a trigger.

**Can we begin with simulation before hardware arrives?**
**Yes — Stages 0–6, roughly 80% of Module 3 and ~11.5 days, need no hardware at all.** A Python event
injector plus a native host build of the detection core covers demo Scenarios 1–4, 6 and 7 end to
end. Be clear-eyed about the simulators: Wokwi has **no M5StickS3 board and no BMI270 part**, and
Espressif's QEMU has **no Wi-Fi at all**, so simulation validates *logic*, never sensor accuracy,
battery, RF, or QR scanning.

**Is the proposed hardware suitable?**
**Yes.** Your device name was right and my doubt was wrong: **M5StickS3 is real, current, $21.50**,
and it is the vendor's replacement for the now-EOL M5StickC PLUS2 — update any doc still naming the
PLUS2. It satisfies Wi-Fi, a 6-axis BMI270 at ±16 g and 1.6 kHz, a 135×240 display, 250 mAh + USB-C,
2 buttons, audio, and ESP32-S3 secure boot / flash / NVS encryption, with no camera. Four items stay
**UNCERTAIN until hardware is in hand**: battery runtime (~1.5–3 h estimated, none published),
QR scan reliability at ~0.49 mm/module, wrist-strap fit for this exact SKU, and Arduino-level
WPA2-Enterprise support. None blocks starting.

**What should we build first?**
**Stage 0 — the simulation foundation**, specifically the event injector and the hardware-adapter
interfaces. It unblocks every later stage, makes the whole module testable without hardware, and
forces the device/backend event contract to be settled before any code depends on it. Then Stage 1
(device registry + credential auth), because the `/device-api` security boundary should exist before
anything is allowed to post events into it.

**Verdict: GO for Stages 0–6 immediately. Order two M5StickS3 in parallel.**
D1, D2, D6 and D9 were resolved on 2026-09-23 (§33), so **Stage 0 is unblocked**. The remaining
open decisions land in later stages and do not gate it.

**Two claims Module 3 must never make:** that it diagnoses anything, or that its thresholds are
clinically validated. The device observes. SAFEHAVEN alerts. The nurse assesses.

---

## 35. Demo plan — the 5-minute walkthrough

> **Numbering note.** This was section 28 in the original brief and was missed
> when the plan was written; the document went from Test plan straight to
> Implementation order. Added here rather than renumbering, because §28, §29
> and §33 are cited by name in code comments and commit messages across the
> repo.

Written after Stages 0–6 were built, so this is a rehearsed script rather than
an aspiration: every beat below is asserted by
`frontend/verify_safety_monitoring.mjs`, which passes 16/16. **No hardware is
required** — the wearable is the Stage 0 simulator, which speaks the same
device API a real M5StickS3 will.

### Before the room

```bash
# 1. Backend, with a short offline threshold so Scenario 6 fits in the demo
cd backend && DEVICE_OFFLINE_AFTER_SECONDS=20 .venv/bin/python3 -m uvicorn app.main:app

# 2. Frontend
cd frontend && npm run dev

# 3. Rehearse — if this passes, the demo works
cd frontend && node verify_safety_monitoring.mjs
```

Have ready: one patient (with a room number), two registered + enrolled
devices, and a terminal with the simulator. Two browser tabs: the patient
page, and **Safety Monitoring**.

> Turn **Sound on** in the alert queue before you start. Browsers block audio
> until a click, so do it during setup, not mid-demo.

### The script

**1 · The problem** *(20s — no screen)*

> "Hospitals often can't put cameras in patient rooms, and staff aren't at the
> bedside most of the time. So when a patient falls at 3am, the first anyone
> knows is the next round. Module 3 is a low-cost wrist wearable that watches
> for movement worth checking on — and tells someone in seconds."

**2 · Assign a device** *(45s — patient page)*

*Scroll to Safety Monitoring. Click **Assign device**.*

> "Devices are reusable, so they're not tied to a patient. I pick a free one —
> note it shows battery and when it last checked in, so I don't hand out a
> dead device."

*Open the profile select. Pause on **Restricted mobility**.*

> "And I choose what to watch for. Read what it says about restricted
> mobility: *a wrist sensor cannot confirm a patient left the bed*. We put that
> in the UI on purpose. I'll take Fall risk."

*Assign. Panel shows **Connected**.*

**3 · Normal movement — nothing happens** *(30s)* ⭐ **the most important beat**

```bash
python3 backend/scripts/simulate_device.py --secret "$S" scenario normal
python3 backend/scripts/simulate_device.py --secret "$S" scenario weak-fall
```

*Switch to Safety Monitoring. Let it sit. Nothing appears.*

> "That second one was a real impact — someone sitting down hard. The device
> detected it, the backend stored it, and deliberately told nobody. An alert
> that fires on normal behaviour teaches staff to ignore alerts, so the
> silence here is a feature, not the system being asleep."

**4 · A fall** *(60s — stay on the dashboard, do not reload)*

```bash
python3 backend/scripts/simulate_device.py --secret "$S" scenario fall
```

*Alert appears on its own, with a chime.*

> "I didn't refresh. Name, patient ID, room, device, and the wording —
> *possible fall*, not *the patient fell*. The device observes; the nurse
> decides."

*Point at the event count.*

> "One physical fall produced several detections. That's **one** alert saying
> *8 events*, not eight alerts. Same idea as before — the system is trying
> hard not to shout."

**5 · Movement, and why the profile matters** *(45s)*

```bash
python3 backend/scripts/simulate_device.py --secret "$S" scenario abnormal
python3 backend/scripts/simulate_device.py --secret "$S" scenario mobility
```

> "Abnormal repetitive movement — and notice what it does *not* say. It
> doesn't say seizure. It can't know that, so it doesn't claim it. There's a
> test that fails the build if that wording ever drifts."

*The mobility event produces nothing.*

> "The mobility one was ignored, because this patient is on Fall risk, not
> Restricted mobility. That's switched on deliberately by a clinician — never
> inferred from a diagnosis."

**6 · The device goes quiet** *(30s)*

*Stop the simulator. Wait ~20s.*

> "A safety monitor that silently stops is the dangerous failure — you'd think
> the patient was watched when they weren't. So going quiet is itself a
> high-priority alert. And there's no background job doing this: the
> dashboard's own refresh is what notices."

**7 · Respond, and the audit trail** *(30s)*

*Acknowledge the fall. Open the patient's **Activity & Safety Timeline**.*

> "Every step is recorded — device assigned, event received, alert raised,
> who acknowledged it and when."

*Open **Wearable Events**.*

> "And here's everything the device reported, including the events that
> *didn't* alert, with the evidence behind each. Being able to see what was
> correctly ignored is how you learn to trust the silence."

**8 · Discharge and reuse** *(30s)*

*Discharge the patient.*

> "Monitoring stops automatically — no one has to remember."

*Assign the same device to another patient.*

> "Same hardware, new patient, and the old patient keeps no active link."

**9 · What we don't claim** *(30s — close on this)*

> "Three honest limits. It doesn't diagnose anything. A wrist sensor can't
> prove someone left a bed, so we never say that. And the thresholds are
> engineering estimates, not clinically validated — tuning those needs real
> hardware on real people. Everything you saw ran without a device, which is
> why we could build and test all of it before one arrived."

### If something goes wrong

| Symptom | Cause / fix |
|---|---|
| No alert appears | Device unassigned, or a weak-fall payload. Check the panel says Connected |
| No sound | Audio needs a click first — press **Sound on** |
| Alert missing on reload | You resolved it; the live queue hides resolved by default |
| Offline never fires | Backend not started with `DEVICE_OFFLINE_AFTER_SECONDS=20` |
| Device not offered | It's already assigned, or registered but never enrolled |

### Deliberately not shown

QR display (Stage 10), real hardware (Stage 7), and detection running on a
real IMU. The demo shows the **backend rules, alert pipeline and nurse
workflow**, which is the part that is finished.

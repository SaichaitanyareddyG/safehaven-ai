# Module 3 — Edge Case Review

Systematic pass over the interactions BETWEEN Module 3's stages, after Stages
0–6 were built. Each stage was tested in isolation as it landed; the defects
below all live in the seams where two stages meet, which is exactly where the
Module 2 review found its three bugs.

Method: probe tests asserting *current* behaviour, so this records what the
system actually did rather than what the code looked like it should do. Four
defects found and fixed, three behaviours examined and deliberately kept, one
UI improvement.

Marker key: 🔴 defect found and fixed · 🟡 examined, kept as-is with reasoning
· 🔵 improvement

---

## Summary

| # | Area | Finding | Severity | Status |
|---|---|---|---|---|
| 1 | Revoke × assignment | Revoking a device left the patient **appearing monitored while not being monitored** | 🔴 **Critical** | Fixed |
| 2 | Discharge × device health | Open `DEVICE_OFFLINE` alert survived discharge and could never be cleared | 🔴 High | Fixed |
| 3 | Escalation × notification | An alert escalating MEDIUM → HIGH produced no toast and no sound | 🔴 High | Fixed |
| 4 | Revoke × enrolment | A revoked device could never be returned to service — permanently bricked | 🔴 Medium | Fixed |
| 5 | Discharge × clinical alerts | An open fall alert stays OPEN after discharge | 🟡 | Kept |
| 6 | Offline queue × discharge | A queued event delivered after discharge still alerts | 🟡 | Kept |
| 7 | Acknowledge × new events | Further events fold into an acknowledged alert without re-alerting | 🟡 | Kept |
| 8 | Assign × stale device | Assign dialog showed a two-day-silent device as simply "Seen" | 🔵 | Improved |

---

## 1. 🔴 CRITICAL — revoking a device left the patient apparently monitored

**What happened.** Revoking a device destroyed its credential and set status
`DISABLED`, but left the `DeviceAssignment` **active**. Probe result:

```
assignment still active : True
panel shows a device    : True
device can still report : 401
alerts raised           : 0
```

So the patient detail page kept showing a connected wearable, the device was
rejected on every report, and **nothing anywhere said monitoring had stopped**.

It was worse than a single oversight, because the safety net that should have
caught it had the same blind spot: `sweep_offline_devices` filters on
`WearableDevice.status == DeviceStatus.ACTIVE`, so a revoked device is excluded
from offline detection too. A device that can never report was also a device
that could never be reported *as* not reporting.

**Why it matters.** This is the precise failure mode Module 3 exists to
prevent: a patient who is believed to be monitored and is not. Every other
route to "monitoring stopped" — discharge, unassign, going silent — is either
explicit or raises an alert. Only revocation was silent.

**Fix.** `revoke_device` now ends any active assignment first, reusing the same
`_end_assignment` path as discharge, and the audit event records
`ended_active_assignment` so the cascade is visible in the trail.

**Regression test.** `test_revoking_an_assigned_device_stops_the_monitoring_it_implied`

---

## 2. 🔴 HIGH — discharge stranded device-health alerts forever

**What happened.** With an open `DEVICE_OFFLINE` alert, discharging the patient
left it `OPEN` and in the live queue:

```
status after discharge  : OPEN
still in live queue     : 1
status after reconnect  : OPEN
```

The last line is the trap. Discharge ends the assignment, so afterwards the
offline sweep no longer sees the device (it only looks at assigned devices) and
a reconnect cannot auto-resolve it (that path also requires an assignment). The
alert had no remaining route to resolution — it would sit in the nurse queue
indefinitely, about a patient who had gone home.

**Fix.** The discharge cascade now auto-resolves `DEVICE_OFFLINE` and
`DEVICE_LOW_BATTERY` for that patient, recorded as SYSTEM with reason
`patient_discharged`.

**Regression tests.** `test_discharge_resolves_device_health_alerts`,
`test_discharge_resolves_a_low_battery_alert_too`

---

## 3. 🔴 HIGH — escalation to HIGH was silent

**What happened.** An ongoing episode that escalates keeps the same alert row
by design (one alert = one episode). But `useAlertNotifications` tracked only a
`Set` of alert **ids**, so:

```
priority        : MEDIUM -> HIGH
same alert id   : True   (therefore no notification)
```

An alert became urgent and nobody was told. The badge count did not change
either, since the alert was already counted.

**Fix.** The notifier now tracks a `Map<id, priority>` and announces both new
alerts and upward transitions to HIGH. Downgrades are ignored — they are not
news, and the backend never downgrades anyway.

---

## 4. 🔴 MEDIUM — a revoked device could never return to service

**What happened.** `reissue_enrollment_code` deliberately allows any
non-`RETIRED` device, so it happily minted a code for a `DISABLED` one — but
`enroll_device` then required `status is ACTIVE` and rejected it:

```
reissue status    : 200
re-enroll status  : 401 Invalid enrollment code
```

The two halves disagreed about what revocation meant. A device revoked by
mistake, or one revoked after being mislaid and later found, was **bricked
permanently**, and the failure was opaque (the generic 401) so the cause was not
obvious from the response.

**Fix.** Enrolment now accepts a `DISABLED` device and returns it to `ACTIVE`.
`RETIRED` remains terminal, which is the distinction the two states were for.
The clinician's act of reissuing a single-use code is the authorisation. The old
credential stays dead — re-enrolment issues a new secret.

**Regression test.** `test_revoked_device_can_be_returned_to_service`

---

## 5. 🟡 KEPT — a clinical alert stays open after discharge

An open `POSSIBLE_FALL` alert survives discharge and remains in the live queue.

Deliberate, and the asymmetry with finding #2 is the point. A fall that
happened is still a fall; closing it is a human decision, not a side effect of
paperwork. Auto-resolving it would let a real safety event be erased by an
administrative action — and the nurse who was walking to that room would find
the alert simply gone.

Device-health alerts are different: "the battery was low" stops being true the
moment the device is no longer monitoring anyone.

A test asserts this asymmetry holds
(`test_discharge_does_NOT_resolve_a_clinical_alert`).

**Residual gap:** the alert card does not show that the patient has since been
discharged. Worth adding, but it is a display gap rather than a safety one.

---

## 6. 🟡 KEPT — a queued event delivered after discharge still alerts

An event detected before discharge, queued through a network outage and
delivered afterwards, is accepted and raises an alert:

```
queued event for discharged patient : 201 CREATED
alerts                              : 1
```

This follows from the Stage 3 decision to let a device name the assignment it
was running when it detected the event. The alternative — discarding it — means
throwing away a **real fall that really happened while the patient was in the
ward**, which is worse than a late alert about someone who has left. The event
is flagged `delayed`, and the UI labels it as such.

---

## 7. 🟡 KEPT — further events fold into an acknowledged alert without re-alerting

Five more falls after acknowledgement produced `event_count: 6` and no new
alert or notification.

Correct for the case it is aimed at: a nurse who has acknowledged and is
walking to the room should not be handed a fresh alert for the same episode.

Importantly this **self-limits**: the clinical dedupe window is measured from
the alert's `created_at`, so once `alert_dedupe_seconds` has elapsed a new event
creates a genuinely new alert rather than folding forever. An episode that is
still producing events several minutes later therefore does re-alert.

---

## 8. 🔵 IMPROVED — the assign dialog showed stale devices as healthy

Assigning a device last seen two days ago succeeds (correctly — the backend has
no reason to refuse), and an offline alert appears seconds later:

```
assign a long-silent device : 201
immediately offline?        : 1
```

The backend behaviour is right; the dialog was not. It showed a flat "Seen" for
any device that had ever checked in, so a two-day-dead device looked identical
to one reporting every 30 seconds.

**Fix.** The dialog now shows *when* ("2 days ago") and marks anything past the
offline threshold in amber, so a nurse picks an awake device rather than
discovering the problem from an alert afterwards.

---

## Areas checked and found sound

- **Idempotency vs deduplication** — separate layers, behaving separately. A
  resent `device_event_id` does not increment `event_count`; twenty distinct
  events do.
- **Reassignment** — history stays attributed to the patient the events came
  from, since events resolve their patient through the assignment.
- **Cross-patient and cross-type dedupe** — alerts do not merge across
  patients or across alert types.
- **Device-credential boundary** — a device credential is rejected on every
  clinician route and vice versa; all auth failures remain byte-identical.
- **Offline detection on a freshly-assigned device** — `assigned_at` fallback
  prevents alerting before the first heartbeat is even due.
- **Unassigned devices** — never reported offline; a device in a drawer is idle,
  not broken.

## Known limitation, not fixed here

**Concurrent sweeps.** `sweep_offline_devices` checks for an existing open
alert and then inserts, with no unique constraint behind it. Two nurses' polls
landing simultaneously could in principle both create a `DEVICE_OFFLINE` alert
for the same device. Not reproduced, and low impact (a duplicate operational
alert, not a missed one), but the honest fix is a partial unique index on
`(patient_id, alert_type) WHERE status <> 'RESOLVED'`, matching how the
assignment invariants are enforced. Deferred to hardening rather than fixed
speculatively.

---

## Verdict

Four real defects, all in seams between stages, none of which the per-stage
tests could have caught — each required two features interacting. Finding #1 in
particular defeated its own safety net, which is the kind of thing only a
deliberate cross-cutting pass finds.

All four are fixed with regression tests. Module 3 Stages 0–6 are sound for the
no-hardware demo.

# Module 3 — Edge Case Review 2 (device link, pairing, alarm on the band)

Second systematic pass, after the real-hardware work of 2026-10-02 added the
device ↔ backend link, the offline event queue, QR pairing, device-initiated
pairing, the fall beacon, the help button, nurse response on the band and the
no-response escalation. As in the first review (`MODULE_3_EDGE_CASE_REVIEW.md`),
the defects live in the seams between those features.

Method: backend behaviour recorded with probe tests before changing anything;
band behaviour traced through `firmware/src/sticks3_main.cpp` and
`DeviceLink.h`, then exercised on the real band (scripted with a bench-only
`inject` command, and by hand).

Marker key: 🔴 defect found and fixed · 🟡 examined, kept as-is with reasoning

---

## Summary

| # | Area | Finding | Severity | Status |
|---|---|---|---|---|
| 1 | Detection × network | A burst of events while the network task was stuck in a slow request could **silently drop a safety event** | 🔴 High | Fixed |
| 2 | Help button × fall alarm | Pressing help during a fall alarm left the beacon running and **escalated "no response" 60 s later** — for a patient who had just responded | 🔴 High | Fixed |
| 3 | Unassign × fall alarm | Unassigning/discharging mid-alarm left the band flashing for nobody and escalating for an unmonitored patient | 🔴 Medium | Fixed |
| 4 | Second event × fall alarm | Any other event during a fall alarm took over its screen and its nurse-response tracking | 🔴 Medium | Fixed |
| 5 | Pairing × revoke | A revoked band could never be re-added under the label printed on it | 🔴 Medium | Fixed |
| 6 | Pairing housekeeping | Expired pairing requests were never deleted (unauthenticated route) | 🔴 Low | Fixed |
| 7 | Pairing × several bands | Poll limit (60/min/IP) could throttle three new bands on one network | 🔴 Low | Fixed |
| 8 | Pairing × live label | Pairing a second band onto a live band's label | 🟡 | Refused (409) — kept |
| 9 | Reboot × fall alarm | A reboot mid-alarm loses the beacon and the escalation timer | 🟡 | Known limitation |

---

## 1. 🔴 HIGH — a burst could silently drop a safety event

**What happened.** The detection loop hands events to the network task through
a 6-slot FreeRTOS queue. `xQueueSend`'s result was ignored. While the network
task was blocked in a slow HTTP request (up to ~10 s on a bad network) a burst
— fall, abnormal movement, low battery, help — could fill it, and the next
event vanished with no log line and no retry.

**Fix.** `DeviceLink::submit` checks the result and, if the hand-off is full,
writes the event straight to the flash queue from the caller (LittleFS is
thread-safe); the network task sends it with the rest.

## 2. 🔴 HIGH — help during a fall alarm caused a false escalation

**What happened.** Holding the front button during the red beacon raised the
help request, but the beacon kept pulsing, the screen title became "Movement
alert", and the 60 s timer still fired `NO_RESPONSE` — telling the nurse the
patient was unresponsive seconds after they asked for help.

**Fix.** A help request during the beacon stops it and cancels the escalation:
it is the clearest possible sign the wearer is responsive.

## 3. 🔴 MEDIUM — unassigned mid-alarm, the band kept alarming

**What happened.** When the heartbeat reported the assignment had ended, the
detection core went idle but the alarm state did not: beacon, tones, and a
`NO_RESPONSE` 60 s later for a patient no longer monitored.

**Fix.** `unassign()` stops the beacon, cancels the escalation and closes the
alert screen. Anything already queued is still delivered.

## 4. 🔴 MEDIUM — a second event took over the fall alarm

**What happened.** The alert screen tracked "the last event submitted". An
abnormal-movement event (or a low-battery event) during a fall alarm replaced
the alarm's title and the event whose delivery and nurse response the band was
following — so the screen could fall back from "notified" to "sending" and
follow the wrong alert.

**Fix.** `DeviceLink` now tracks delivery of one *watched* event, set
atomically at submit time. During a fall beacon, other events are still sent
but do not take over the screen.

## 5. 🔴 MEDIUM — a revoked band could not come back under its own label

**Probe:** re-pairing a revoked band with its printed label → **409**. Staff
would have had to invent a new label, and the case and the record drift apart.

**Fix.** `approve_pairing` reuses the existing record when its credential is
gone (revoked, or a pairing that never finished) — via
`reissue_enrollment_code` — and still refuses (409) when the label belongs to a
live, credentialled band (#8).

## 6–7. 🔴 LOW — pairing housekeeping and limits

Expired pairing requests older than a day are purged on each new request. The
poll limit is now 300/min/IP: polls carry a 256-bit token, so the limit only
caps a broken loop and must not throttle several bands unboxed together.

## 8. 🟡 KEPT — a live band's label cannot be paired onto another band

Probe: 409. Allowing it would hand an existing identity — and its patient — to
whoever holds the new band. To move a label, revoke the old band first.

## 9. 🟡 KNOWN LIMITATION — reboot mid-alarm

Events already detected are persisted and delivered after a reboot; the
beacon and the 60 s escalation timer are not. The nurse still has the fall
alert. Persisting alarm state across reboots is a candidate for hardening.

---

## Areas checked and found sound

- QR resolve after revoke → 404 (revoke ends the assignment, which nulls the token).
- A band moved to a new patient is never shown the previous patient's alert
  (the band alert view filters by the current assignment's patient).
- The heartbeat's alert view carries type, status and time only — no patient data.

## Verification

- Backend: probes rewritten as regression tests (`test_wearable_pairing.py`);
  372 wearable + unit tests pass.
- Band: fixes built and flashed. On the real band, a scripted run confirmed the
  no-response escalation 60 s after an untouched fall; by hand, the full loop
  (drop → alert → no response → acknowledge → "A nurse is coming" → resolve).
  Fixes 2 and 3 are on the manual test list.
- `SH_BENCH_TOOLS` (the `inject` command used for this) must be removed from
  `platformio.ini` before any deployment.

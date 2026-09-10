# SAFEHAVEN AI — Module 2 Implementation Plan

**Status note, read this first:** Module 2 was already designed (`MODULE_2_DESIGN_REPORT.md`), approved, and **built** earlier in this project — backend engine, one migration, 34 passing tests, full scan-verify-confirm UI. This plan is written against that existing build, not a blank codebase. Each section below is marked ✅ **already built**, ⚠️ **gap found**, or 🆕 **new scope** so it's clear what this document is actually asking you to decide.

---

## 1. Current Reusable Data

| Piece | Verified state |
|---|---|
| `Patient.patient_code` | Server-generated, unique, `P####` format — already the wristband ID |
| `CareInstruction.clinical_status` (ACTIVE/COMPLETED/STOPPED) + dates | Exists, MEDICATION-only by construction |
| `GET /patients/{id}/instructions?clinical_status=ACTIVE` | Already live |
| `StructuredExtraction.normalized_facts` | `medication_name, dose_value, dose_unit, route, frequency, timing, duration, reason` |
| Clinician auth (`get_current_user`) | Reused as-is |
| `User.role` | Exists, unenforced |
| `AuditEventType` | Plain string column — new values need no migration |
| Frontend routing/`AppLayout` | Flat, bare shell — extended without touching Module 1 |

✅ **Already built and reused exactly this way** by `app/medication_verification/`.

---

## 2. Data Gaps

- **Formulation precision**: `medication_name` is free text; a clinician may write "Metoprolol" without specifying succinate/tartrate. Handled by treating an unspecified formulation as `REVIEW_REQUIRED`, never an auto-pass — no Module 1 schema change made.
- **No allergy model** — out of scope for this spec (not requested this round).
- **No expiry/OCR-confidence fields anywhere** — only relevant if image fallback (§8) is approved; currently N/A.

---

## 3. CareInstruction Decision

**YES — confirmed, with evidence.** `app/medication_verification/service.py` reuses `CareInstruction`/`StructuredExtraction` directly:

```python
_, instructions = instructions_service.list_patient_instructions(
    db, patient_id, status=InstructionStatus.APPROVED, limit=1000, offset=0, clinical_status=None
)
```

`clinical_status=None` deliberately pulls ALL statuses (not just ACTIVE) so STOPPED/COMPLETED orders remain visible internally for the "outdated medication" detection — exactly this spec's requirement. No second order model exists or was created.

---

## 4. Medication Product Design

✅ **Already built** — `app/reference/medication_products.py`, a static Python dict, not a database table (same pattern as `medication_purpose.py`; this project has direct precedent of removing a DB table built for this exact shape of data in favor of a static dict). Fields match the spec's minimum exactly: `barcode, medication_name, strength_value, strength_unit, formulation, route`.

Currently seeded: `MED-METOPROLOL-SUCCINATE-25/50`, `MED-METOPROLOL-TARTRATE-25`, `MED-LISINOPRIL-10`. This spec's test data additionally wants a Metformin 500mg product (`MED005`) — trivial one-entry addition, not yet added.

Naming note: existing barcodes are mnemonic strings (`MED-METOPROLOL-SUCCINATE-25`); this spec's examples use numeric codes (`MED001`). Cosmetic difference only — flagged in §22, not acted on without your call.

---

## 5. Administration Event Design

✅ **Already built** — `AdministrationEvent` table, one migration applied. Field comparison against this spec's suggested list:

| Spec's field | Actual field | Note |
|---|---|---|
| `verified_by` | `performed_by` | same meaning, different name |
| `verification_timestamp` | `created_at` | same meaning |
| `administered_by`, `administered_at` | same | nullable until administration is actually confirmed |
| `verification_result` | same | `VERIFIED/WARNING/BLOCKED/REVIEW_REQUIRED` |
| `status` | *(not present)* | would duplicate `verification_result` + whether `administered_at` is set — not adding unless you see a case the existing two fields don't cover |
| `notes` | *(not present)* | no current UI writes free-text notes; add only if a real need shows up |
| *(not requested)* | `mismatch_reasons`, `checks` | machine-readable reason codes + full per-check detail, for audit reconstruction |

No changes recommended here — the extra fields not in the spec's list were things I found genuinely necessary while building (see the checklist UI in §14).

---

## 6. Patient Scanning Design

✅ **Already built, fully matching this spec**: QR code (`patient_code` as the payload), `@zxing/browser` camera decode, and — added in the last round of feedback — a **Scan / Enter Patient ID toggle** for manual fallback. Both paths call the same `GET /patients/by-code/{code}` lookup, so behavior is identical either way.

---

## 7. Medication Scanning Design

✅ **Mostly already built.** QR (not Code128) was chosen deliberately for both scan targets — one library, one format, simplest reliable prototype path (per the original design report). `@zxing/browser`'s underlying `BrowserMultiFormatReader` supports Code128/DataMatrix too, so this isn't a dead end if real pharmacy-standard 1D barcodes are needed later — just swap the reader class, no architecture change.

**⚠️ Gap found while re-reading the engine for this plan:** multiple-active-order resolution is NOT correctly handled. The code picks `order = active[0]` — the first same-drug-family ACTIVE order, ordered by most-recently-created — without checking whether more than one ACTIVE order for that drug exists. If two ACTIVE orders for the same drug at different doses ever coexist (e.g. a dose change where the old order wasn't marked STOPPED), a scan could be compared against the wrong one, producing a misleading DOSE_MISMATCH instead of matching the correct order, or in a worse case silently matching when the *other* active order is the one actually intended. This directly contradicts this spec's own rule: *"AI must never silently choose between multiple possible orders."*

**Fix (not yet implemented, pending your approval on this plan):** after narrowing to same-drug-family ACTIVE orders, find how many of them the scanned product's dose matches:
- exactly one → proceed with that one (current common case, unaffected)
- zero → dose mismatch, message can list all active doses on file for that drug
- more than one → `REVIEW_REQUIRED` (genuinely ambiguous, per spec)

Small, contained change to `service.py`, fully covered by adding 2-3 new test cases.

---

## 8. Image Fallback Design

🆕 **Not built — this is new scope, not a gap.** The design report you approved earlier explicitly deferred this to Phase 2; this spec now lists it as required Demo Case 6. That's a real decision, not something I'll assume — see §22.

Smallest safe design, if approved:

```
Barcode unreadable
  → nurse taps "Scan Medication Label"
  → camera captures a still image (not continuous video)
  → sent to a vision/OCR call — a single request, not a continuous stream
  → extracts candidate: medication_name, strength, formulation, expiry (if visible)
  → shown to nurse as a SUGGESTION, never auto-applied
  → nurse taps [Confirm] or [Incorrect / Rescan]
  → ONLY on [Confirm] does the confirmed structured data enter the SAME
    deterministic verification engine as a normal barcode scan (§9) —
    the exact same rules, same result states, no separate "OCR-only" path
  → result is always at best REVIEW_REQUIRED-eligible for VERIFIED, never
    auto-VERIFIED purely from OCR confidence
  → UI always discloses: "Barcode verification unavailable. Medication
    was identified from label image and manually confirmed."
```

Implementation note: this needs a vision-capable call (a multimodal LLM image call, or a dedicated OCR API) purely for **text extraction**, never for the safety decision — the extracted fields flow through the exact same deterministic engine as any other scan. This is consistent with "LLM is NOT needed for Module 2 core verification" — vision is only ever a text-extraction aid here, same boundary as OCR would be.

---

## 9. Verification Engine

```
1. Resolve patient by code/manual entry → not found: BLOCKED
2. Resolve product by barcode → not found: REVIEW_REQUIRED
3. Load ALL (any clinical_status) APPROVED medication instructions for the patient
4. Filter to same-drug-family as the scanned product
   → none at all: BLOCKED ("no matching order for this patient")
5. Among same-drug-family orders, split ACTIVE vs STOPPED/COMPLETED
   → does the scanned dose match a STOPPED/COMPLETED order specifically
     (and not the active one)? → BLOCKED, "previous order stopped, active
     order is X" (the outdated-medication demo case)
   → no ACTIVE order at all → BLOCKED, same message shape
6. [FIX PENDING §7] Among ACTIVE same-drug orders, how many does the
   scanned dose match?
     0 → BLOCKED, dose mismatch
     1 → continue to 7 against that one order
     >1 → REVIEW_REQUIRED, ambiguous
7. Hard checks against the resolved order (ALL must pass or → BLOCKED):
   dose exact match, route exact match, formulation not contradicted
8. Formulation specifically:
   - order text contains a contradicting salt/release keyword → BLOCKED
   - order text specifies nothing → REVIEW_REQUIRED (data gap, never
     treated as if it were a detected mismatch)
   - order text consistent with product → pass
9. Time (soft check, prototype config, ±60 min around a morning/afternoon/
   evening/night keyword found in timing/frequency text; no keyword found
   → skipped, not penalized): outside window → WARNING, never BLOCKED
   purely from time
10. All hard checks pass + time within window → VERIFIED
```

No LLM anywhere in this path — confirmed by direct code inspection, not just description.

---

## 10. Result States

| State | Meaning | Nurse can proceed? |
|---|---|---|
| VERIFIED | Every hard check passed, time in window | Yes — Confirm Administration |
| WARNING | Everything passed except time | Yes, after acknowledgment |
| REVIEW_REQUIRED | Unresolvable barcode, ambiguous multiple orders, or unspecified formulation | No — Rescan / manual path only |
| BLOCKED | An actual hard rule was violated | No — Rescan only, no Ignore button anywhere in the UI |

---

## 11. Multiple Medication Handling

Already matches the spec exactly: the nurse never pre-selects which medication they're giving. One scan of the physical product is enough — the engine searches *all* of the patient's medication orders (any status) for a drug-family match, narrows automatically, and only asks for human input when that narrowing is genuinely ambiguous (§7 fix) — never when it can resolve deterministically on its own.

---

## 12. Medication-Form Scope

| Form | Classification |
|---|---|
| Oral tablets/capsules | **BUILD NOW** — already built, all 4 seeded products are this form |
| One prefilled injection (e.g. Enoxaparin) | **BUILD NEXT** — same static-dict pattern, one new entry, no engine change (ready-to-administer dose = simple 1:1 like oral) |
| Liquids, multi-dose vials, reconstitution, IV infusion rate, insulin/weight-based/titrated dosing, drug interactions, dose calculation | **PHASE 2** — none of this is touched by the current engine, deliberately |

---

## 13. APIs Needed

✅ **Already built, matches "smallest set" exactly:**
- `GET /patients/by-code/{code}`
- `GET /medication-products/{barcode}`
- `POST /medication-verification/verify`
- `POST /medication-verification/administer`

No PATCH/DELETE on any of these — immutable, same as `AuditEvent`.

---

## 14. UI Changes

✅ **Already built:** `/medication-verification` route, `BarcodeScanner` (shared component, both scan targets), `PatientIdentificationStep` (scan/manual toggle), `VerificationResultView` (checklist + banner + contextual actions), nav link in `AppLayout`. No Module 1 page touched.

---

## 15. Auth / Security

Already reviewed and unchanged: `get_current_user` gates every Module 2 endpoint, identical to Module 1's. Patient care-plan tokens (`PatientCareAccessToken`) are a structurally separate mechanism `get_current_user` never accepts — confirmed by a passing test (`test_patient_care_plan_token_cannot_call_verify`), not just asserted. `User.role` exists but is unenforced; if a real Nurse-vs-Clinician distinction is wanted later, the smallest safe change is one `require_role("nurse")` dependency applied to specific routes — not built, not recommended for the prototype.

---

## 16. Audit Events

✅ **Already built and firing:** `PATIENT_SCANNED`, `MEDICATION_SCANNED`, `MEDICATION_VERIFIED`, `MEDICATION_MISMATCH`, `ADMINISTRATION_CONFIRMED` — all through the existing `record_event()`/`audit_events` table, zero new infrastructure.

Not built: `VERIFICATION_CANCELLED` (no cancel action exists in the UI to fire it — nothing to wire it to yet), `PATIENT_MANUALLY_SELECTED` (manual patient-ID entry currently logs the same `PATIENT_SCANNED` event as a camera scan — could add a `resolved_via: "manual"|"scan"` metadata flag cheaply if distinguishing them in the audit trail matters to you), `MEDICATION_SCAN_FAILED`/`MEDICATION_IMAGE_IDENTIFIED`/`MEDICATION_MANUALLY_CONFIRMED` (only meaningful if §8's image fallback is built).

---

## 17. Test Data

`patient_code` is server-generated (sequence-based), so I cannot force it to literally be `P1001`/`P1002` — the DB already has many patients from earlier testing sessions, so fresh ones will get whatever the sequence assigns next. I can seed the exact clinical scenario (names, orders, statuses) and report back the real codes assigned:

```
Patient "John", Room 204
  ACTIVE:  Metoprolol Succinate ER 25 mg, oral
  ACTIVE:  Lisinopril 10 mg, oral
  STOPPED: Metoprolol Succinate ER 50 mg, oral

Patient "Mary", Room 205
  ACTIVE:  Metformin 500 mg, oral
```

Products: the 4 already seeded, plus one new `MED-METFORMIN-500` entry to match Mary's order.

---

## 18. Test Plan (the 6 demo cases)

| # | Case | Status |
|---|---|---|
| 1 | John + matching Metoprolol → VERIFIED | ✅ covered by existing passing test |
| 2 | Mary + John's Metoprolol → BLOCKED (no matching order) | ✅ covered |
| 3 | John + wrong dose → BLOCKED | ✅ covered |
| 4 | John + wrong formulation → BLOCKED | ✅ covered |
| 5 | Stopped/outdated product scanned → BLOCKED | ✅ covered |
| 6 | Barcode unreadable → OCR → confirm → REVIEW_REQUIRED-eligible | 🆕 pending §8 approval |

Plus the §7 fix needs 2-3 new tests: two simultaneous ACTIVE orders for the same drug → REVIEW_REQUIRED.

---

## 19. Demo Script (3–5 min)

> "A nurse is about to give John his morning medications." *(Scan John's wristband — or type his ID, either works.)* "Metoprolol and Lisinopril, both active." *(Scan the correct Metoprolol product.)* "Every check passes." *(VERIFIED → Confirm Administration.)*
>
> "Here's the case barcode scanning alone can't catch." *(Scan John again, then the 50mg product — his old, stopped dose.)* "The barcode is completely valid — it's a real product. SafeHaven checks it against the *current* order, not just what's on the package." *(BLOCKED: previous order stopped, active order is 25mg.)*
>
> "Same drug name, different product." *(Scan the Tartrate product against the Succinate ER order.)* "Formulation mismatch — never reduced to just name and dose." *(BLOCKED.)*
>
> "And the wrong patient." *(Scan Mary, then John's Metoprolol.)* "No matching order for her at all." *(BLOCKED.)*

*(If §8 is approved: add — "barcode won't scan? photograph the label instead — SafeHaven suggests what it sees, but a human still has to confirm it before anything is compared.")*

---

## 20. Implementation Timeline

Most of the original 5-7 day estimate is **already spent and done** — this isn't a fresh clock. What's actually left:

- **0.5 day** — §7 fix (multiple-active-order ambiguity) + its tests
- **0.5 day** — reseed John/Mary test data, add the Metformin product, rerun full suite
- **2-3 days** *(only if §8 approved)* — image capture UI, one vision/OCR call, confirm step, wired into the existing engine unchanged
- **0.5 day** — demo rehearsal against all 6 scenarios live

Without §8: **~1 day** remaining. With §8: **~3-4 days** remaining.

---

## 21. Files to Modify

| File | Reason | Size |
|---|---|---|
| `backend/app/medication_verification/service.py` | §7 fix: multi-active-order ambiguity → REVIEW_REQUIRED | SMALL |
| `backend/tests/integration/test_medication_verification.py` | new tests for the above | SMALL |
| `backend/app/reference/medication_products.py` | +1 Metformin entry | SMALL |
| *(seed script or manual API calls)* | John/Mary test data | SMALL |
| — everything else in §§1-6, 9-17 — | **no changes** | — |
| *(only if §8 approved)* new: image capture component, vision/OCR call, confirm-step UI, `MEDICATION_SCAN_FAILED`/`MEDICATION_IMAGE_IDENTIFIED`/`MEDICATION_MANUALLY_CONFIRMED` audit events | new scope | LARGE |

---

## 22. Risks / Questions — the only things I actually need from you

1. **Approve the §7 fix?** (Recommended — closes a real, spec-mandated safety gap, no downside, small change.)
2. **Build the image/OCR fallback now (§8), or keep deferring it as originally agreed?** This is the one real scope/timeline decision — it's the difference between ~1 day and ~3-4 days of remaining work, and it's genuinely new work, not a gap in what exists.
3. Cosmetic, low-priority, no action needed unless you want it: rename barcodes to `MED001`-style numeric codes; add a `notes`/`status` field to `AdministrationEvent`; distinguish manual vs. scanned patient identification in the audit trail.

Nothing else in this plan requires a decision — everything else already matches what's built.

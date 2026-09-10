# SAFEHAVEN AI — Module 2 Design Report

Read-only inspection. No code, models, or migrations were written to produce this report. Verified directly against the current codebase (not assumed from memory).

---

## 1. Module 2 Product Definition

**Context-aware bedside medication verification that confirms the right patient and medication against the latest active clinician-approved order before administration.**

---

## 2. What Already Exists (exact reuse)

| Shared-core piece | Verified state | Module 2 use |
|---|---|---|
| `Patient.patient_code` | Auto-generated, unique, DB-sequence-backed, format `P1001` (`patients/models.py:31-37`) | **Already exactly the wristband QR identifier** the spec describes — no new field needed |
| `Patient.room_number` | Exists, nullable | Shown on the "Scan Patient" confirmation screen |
| `CareInstruction.clinical_status` (`ACTIVE`/`COMPLETED`/`STOPPED`) + `clinical_start_date`/`clinical_end_date` | Built this project, MEDICATION-only by construction | This **is** "the current active order" concept — exactly what Module 2 needs, already there |
| `GET /patients/{id}/instructions?clinical_status=ACTIVE` | Already live (`instructions/router.py:70`) | Fetches the patient's active medication orders — **zero new backend work** to load this list |
| `StructuredExtraction.normalized_facts` | `medication_name, dose_value, dose_unit, route, frequency, timing, duration, with_food, reason` (`ai/schemas.py:16-32`) | The order's medication identity/dose/route/timing data for comparison |
| Clinician authentication (JWT) | `get_current_user` dependency, works today | Gates Module 2 endpoints exactly like Module 1's |
| `User.role` | Column exists on `User` (`auth/models.py:18`), **always `"clinician"`, never checked anywhere** | A ready but currently-inert foundation for nurse/clinician separation later |
| `AuditEventType` | Plain `String(64)` column, not a native Postgres enum, specifically so new event types don't need a migration (`audit/models.py:20-24`) | New Module 2 event types are a pure Python addition |
| `record_event()` / `audit_events` table | Immutable, append-only, filtered by `patient_id` | Reused as-is |
| Frontend routing (`App.tsx`) | Flat `<Routes>`, `ProtectedRoute` wrapper | A new route slots in without touching any Module 1 page |
| `AppLayout.tsx` | Bare header + content shell, no nav sidebar to fight | Confirmed still true after this session's chat rebuild |
| `Encounter` | Exists, optional context | Not required for MVP verification; available if a later iteration wants per-visit administration history |

**Nothing here needs to change for Module 2 to read what it needs.**

---

## 3. Data Gap Analysis

What Module 2 needs that Module 1 does not currently store:

1. **Physical product identity (barcode → product).** Nothing in the schema maps a scannable code to a medication product. Genuinely new.
2. **Formulation/salt-form precision.** `medication_name` is free text; Module 1's extraction was built for patient explanation, not exact product matching, so a clinician's order for "Metoprolol 25 mg" may never specify succinate vs. tartrate at all. This is a real gap — detailed in §4.
3. **Allergy data.** `PatientCondition` is free-text diagnoses/conditions only (verified: `condition_name: String`, no type/category field distinguishing an allergy from a diagnosis). There is no structured, safe allergy source today.
4. **"Administered" as distinct from "active order exists."** `CareInstruction.status` tracks the *authoring* workflow (DRAFT→APPROVED); `clinical_status` tracks whether an order is still *in effect*. Neither records "a nurse gave this specific dose at this specific time." Genuinely new (§6).
5. **Enforced nurse/clinician role separation.** The column exists; the enforcement does not (§14).

---

## 4. CareInstruction Review

**YES — with one caveat.**

`CareInstruction` + `StructuredExtraction` can safely represent the order side of Module 2 exactly as they stand: medication name, dose value/unit, route, frequency, timing, clinical status, and start/end dates are all already there, and Module 2 would read the *same rows* Module 1 already writes and approves — no duplicate source of truth, no new order model.

**The caveat:** `medication_name` is free text, and Module 1's clinicians were never prompted to specify salt form or release mechanism (extended-release vs. immediate-release, succinate vs. tartrate) — that precision was never needed for patient explanation. So an order for "Metoprolol 25 mg" may not, on its own, say which physical product it means.

**Recommendation for now:** do not modify Module 1 to fix this. Instead, the verification engine treats an unspecified/ambiguous formulation on the order side as `REVIEW_REQUIRED`, never as an automatic pass (§8–9). A future, purely additive, nullable `formulation: str | None` field on `MedicationFacts` — the same low-risk pattern already used for `duration` earlier this project — would close this gap cleanly later. That is a Phase 2 recommendation, not a requirement to start Module 2.

---

## 5. Medication Product Model

**Needed as a concept — but NOT as a new database table.**

This project has explicit, direct precedent for exactly this shape of data: a `MedicationPurposeCache` DB table was built for small, static, non-patient-specific reference content and later **deliberately removed in favor of a static curated Python dict** (`app/reference/medication_purpose.py`). `MedicationProduct` is the same shape of thing — small, non-patient-specific, read-only, prototype-scale (4 products in the test dataset) — so it should follow the same pattern: a static Python mapping keyed by barcode, not a table.

Minimum fields (as a dict/dataclass entry, not columns):

```
barcode          -> str   (the scanned code, e.g. "MED-METOPROLOL-SUCCINATE-25")
medication_name  -> str   (e.g. "Metoprolol Succinate ER")
strength_value   -> float (e.g. 25.0)
strength_unit    -> str   (e.g. "mg")
formulation      -> str   (e.g. "extended-release tablet" — this is what distinguishes
                            succinate/ER from tartrate/IR; see §4 and §8)
route            -> str   (e.g. "oral")
```

If real barcode-to-product lookups are ever needed beyond a hand-curated prototype set, that becomes a Phase 2 decision (e.g. an external drug database), not a reason to add a DB table now.

---

## 6. Administration Event Model

**Needed — as one small, new table.** This is genuinely new, patient/order-specific transactional data, not reference data, so it doesn't fit the static-dict pattern above, and it doesn't fit anywhere already in the schema.

**Why it's needed, precisely:** a `VERIFIED` result is a moment-in-time comparison; it says nothing about whether the nurse then actually gave the dose. Conflating the two would make it impossible to later ask "was this dose actually administered, by whom, when" — a real clinical/legal question distinct from "did the barcode match the order."

Minimum fields:

```
id                    uuid, PK
patient_id            FK -> patients.id
care_instruction_id   FK -> care_instructions.id          (the order verified against)
product_barcode       str                                 (reference into the static
                                                             MedicationProduct mapping —
                                                             not a FK, since that's not a table)
verification_result   enum: VERIFIED | WARNING | BLOCKED | REVIEW_REQUIRED
mismatch_reasons       JSONB list of str                  (e.g. ["FORMULATION_MISMATCH"];
                                                             empty when VERIFIED)
administered_by       FK -> users.id
administered_at       datetime, nullable                  (null until administration is
                                                             actually confirmed — a verified-
                                                             but-not-yet-confirmed record has
                                                             this null)
override_reason       text, nullable                      (only set if a controlled override
                                                             was used — see §14/§17)
created_at            datetime
```

No update/delete path — same immutability pattern as `AuditEvent`.

---

## 7. Scanning Design

**Recommendation: browser/tablet camera via `getUserMedia`, one library, one code format.**

- **Library:** `@zxing/browser` (ZXing) — mature, widely used, decodes both QR and 1D formats (Code128, DataMatrix) from a live camera stream in-browser, no native app needed. No barcode/camera library exists in this codebase today (verified — no `getUserMedia`, no scanning package in `package.json`), so this is a new, contained dependency.
- **Code format — QR for everything, for the prototype.** Both the wristband and the medication label become QR codes (`P1001`, `MED-METOPROLOL-SUCCINATE-25`) — the spec's own examples already assume this. Using one symbology for both scan targets is the simplest reliable approach: one decode path, one component (`<BarcodeScanner onDecode={...} />`), reused for both steps. Code128/DataMatrix support stays available in ZXing for later if real pharmacy-standard labels are introduced.
- **Device:** any device with a camera running the SafeHaven web app — phone, tablet, or laptop. No new native app.

---

## 8. Verification Engine

Pure, deterministic function — no LLM anywhere in this path.

```
INPUT: scanned patient_code, scanned barcode

1. Resolve patient by patient_code.
   → not found: BLOCKED ("Unknown patient wristband")

2. Resolve product by barcode (static MedicationProduct mapping).
   → not found: REVIEW_REQUIRED ("Unrecognized barcode")

3. Load ALL of the patient's medication CareInstructions (not just ACTIVE —
   STOPPED/COMPLETED ones are needed to build an informative message).
   Group by medication_name (case-insensitive, normalized).

4. Find the candidate order(s) whose medication_name matches the scanned
   product's medication_name.
   → no match at all, any status: BLOCKED ("No order for this medication on this patient")
   → matches exist, but the only ones are STOPPED/COMPLETED: BLOCKED, with the specific
     contrast message ("Previous {old dose} order is {status}. Current active order is
     {new dose}.") — this is the stopped-vs-active demo scenario.
   → an ACTIVE match exists: continue to 5 against that instruction.

5. Hard checks against the ACTIVE candidate (ALL must pass):
   a. dose_value + dose_unit: exact normalized match.                    fail → BLOCKED
   b. route: normalized case-insensitive match.                          fail → BLOCKED
   c. formulation: does the order's medication_name text contain a clear,
      contradicting salt/release-form signal vs. the product's formulation?
        - contradicts (e.g. order says "tartrate", product is succinate): BLOCKED
        - order specifies nothing about formulation at all:               REVIEW_REQUIRED
        - order's text is consistent with the product's formulation:      pass
   d. clinical_status must be ACTIVE (already guaranteed by step 4, kept
      explicit here as a defense-in-depth check).                        fail → BLOCKED

6. Soft check (only reached if step 5 fully passes or only produced the
   formulation-ambiguous case):
   a. Map the order's timing/frequency to a configured time-of-day
      (prototype config, e.g. "morning" → 08:00, ±60 min tolerance —
      explicitly labeled prototype configuration, not a clinical standard).
      outside window → WARNING
      within window  → pass

7. (Optional, only if allergy data is added — see §3/§17) Cross-check the
   product's medication_name against a documented allergy list.
      conflict → BLOCKED

RESULT:
  any hard check failed                          → BLOCKED
  formulation ambiguous, everything else passed   → REVIEW_REQUIRED
  time outside window, everything else passed     → WARNING
  everything passed cleanly                        → VERIFIED
```

---

## 9. Result States

| State | Meaning | Nurse can proceed? |
|---|---|---|
| **VERIFIED** | Every hard check passed, time within tolerance. | Yes — `[Confirm Administration]` |
| **WARNING** | Every hard check passed; only the time-of-day soft check missed. | Yes, after explicit acknowledgment — `[Acknowledge & Confirm]` |
| **REVIEW_REQUIRED** | System could not reach a confident answer (unreadable barcode, unrecognized product, or the order's formulation is unspecified/ambiguous — not contradicted). | No — `[Rescan]` / `[Manual Lookup]`, human resolution required |
| **BLOCKED** | A hard safety rule was actually violated (wrong patient, wrong drug, wrong dose, wrong route, contradicted formulation, or the order is STOPPED/COMPLETED). | No — `[Rescan]` / `[Request Review]` only, no casual dismissal |

Nothing here is ever auto-approved on uncertainty — `REVIEW_REQUIRED` and `BLOCKED` both require a human action, never a timeout-to-pass.

---

## 10. Barcode Failure Flow

Normal path: barcode → product → verification. Fallback only when the barcode can't be read.

**For this design pass, recommend keeping the fallback minimal, not OCR:** unreadable barcode → nurse gets a manual product search/select (type the drug name, pick from the same static `MedicationProduct` list) → whatever is picked still goes through the full verification engine in §8, and is still capped at `REVIEW_REQUIRED` at best if identity is at all uncertain — human confirmation is still required before administration either way. This satisfies Scenario 6 (optional) without building computer vision now.

**If OCR is added later (Phase 2, per the spec's own "keep it only as a safe fallback"):** camera → OCR extracts a *candidate* name/strength/formulation → shown to the nurse as a suggestion only → always lands in `REVIEW_REQUIRED`, never `VERIFIED`, regardless of OCR confidence. The UI copy must say "Possible medication identified. Barcode verification unavailable. Human/pharmacist verification required." — never "Medication verified."

---

## 11. API Design

All new, minimal, additive — nothing here modifies a Module 1 endpoint.

| Endpoint | Purpose |
|---|---|
| `GET /patients/by-code/{patient_code}` | Resolve a wristband scan to a patient (exact lookup, not the existing fuzzy `/patients?search=` list endpoint) |
| `GET /medication-products/{barcode}` | Resolve a scanned barcode to product identity (reads the static reference mapping — mirrors `lookup_medication_purpose()`'s existing pattern) |
| `GET /patients/{patient_id}/instructions?clinical_status=ACTIVE` | **Already exists** — reused as-is |
| `POST /medication-verification/verify` | Body: `{patient_id, barcode}` → runs §8's engine → `{result, checks: {...}, matched_instruction_id, reasons}`. Records `PATIENT_SCANNED`/`MEDICATION_SCANNED`/`MEDICATION_VERIFIED` or `MEDICATION_MISMATCH`. |
| `POST /medication-verification/administer` | Body references the verification just performed → creates the `AdministrationEvent` row → records `ADMINISTRATION_CONFIRMED` |
| `POST /medication-verification/override` *(only if §14/§17's override is approved)* | Requires reason, authenticated user → records `MEDICATION_OVERRIDE` |

No PATCH/DELETE on any of these — same immutable-record pattern as `AuditEvent`.

---

## 12. UI Design

**Recommend a dedicated route, `/medication-verification`, not a tab nested inside Patient Detail.** The real workflow begins with "nurse scans a wristband" — the patient isn't known yet at that point, unlike every existing `PatientDetailPage` tab, which already presupposes a selected patient. A top-level route (linked from `AppLayout`'s header) matches how the workflow actually starts.

Minimum screens, matching the spec's own mockups:

1. **Scan Patient** — camera view → on decode, shows resolved name/room/code for confirmation.
2. **Scan Medication** — camera view → on decode, shows resolved product name/strength/formulation.
3. **Verification Result** — checklist (Patient / Medication / Dose / Formulation / Route / Time, each ✓ or ✗) + one overall banner (`VERIFIED`/`WARNING`/`REVIEW_REQUIRED`/`BLOCKED`) + result-specific actions exactly as §9 describes. No `[Ignore]` button, ever.
4. **Confirmation** — simple success state with timestamp, after `[Confirm Administration]`.

Mobile/tablet-responsive by default (Tailwind, already the project's convention) since this workflow is meant to run on a handheld device at the bedside.

---

## 13. Audit Design

All new values added to the existing `AuditEventType` string enum — no migration needed (verified: it's `String(64)`, not a native Postgres enum, specifically for this reason):

```
PATIENT_SCANNED
MEDICATION_SCANNED
MEDICATION_VERIFIED
MEDICATION_MISMATCH
VERIFICATION_CANCELLED
ADMINISTRATION_CONFIRMED
```

If override is built (§14/§17):
```
REVIEW_REQUESTED
MEDICATION_OVERRIDE
```

Same `record_event()` writer, same `audit_events` table, same per-patient timeline the clinician UI already renders — 100% reused.

---

## 14. Authorization

**Minimum recommendation: none, for the prototype.** Module 2 endpoints require `get_current_user` exactly like Module 1's — any authenticated staff account. This already satisfies the one hard requirement in the spec: patient care-plan tokens (`PatientCareAccessToken`) are a structurally separate auth mechanism that `get_current_user` never accepts, so "patient tokens must never reach medication verification" is already true by construction, with no new code.

`User.role` exists but is unenforced anywhere today (verified). Building real nurse-vs-clinician separation (e.g. "only a nurse can confirm administration," "only a clinician can override") is a small addition *when actually wanted* — one `require_role("nurse")` dependency checked against `current_user.role`, applied to specific routes — but is not recommended as part of the initial build. Full RBAC is explicitly out of scope.

---

## 15. Test Plan

Deterministic, no mock/live LLM toggle needed anywhere in this module (no LLM involved at all):

| # | Scenario | Expected |
|---|---|---|
| 1 | Correct patient + correct medication, dose, route, formulation, within time window | `VERIFIED` |
| 2 | Wrong patient (scanned wristband doesn't match the order's patient) | `BLOCKED` |
| 3 | Correct patient, correct drug, wrong dose | `BLOCKED` |
| 4 | Same medication name, wrong formulation (Metoprolol Succinate ER 25mg ordered, Tartrate 25mg scanned) | `BLOCKED` |
| 5 | Stopped/outdated order scanned instead of the current active one (Metoprolol 25mg STOPPED vs. 50mg ACTIVE) | `BLOCKED`, with the specific contrast message |
| 6 *(optional)* | Barcode unreadable → manual lookup path | `REVIEW_REQUIRED` |
| 7 *(optional, if allergy data exists)* | Documented allergy conflicts with scanned medication | `BLOCKED` |
| 8 | Correct everything, administration time outside configured window | `WARNING` |
| 9 | Order's medication_name doesn't specify formulation at all | `REVIEW_REQUIRED` |
| 10 | Unauthenticated request to any Module 2 endpoint | 401 |
| 11 | Valid patient care-plan token presented to a Module 2 endpoint | 401 (proves the auth boundary in §14) |

---

## 16. Demo Flow (3–5 minutes)

> "A nurse is about to give a patient their morning medications." *(Open Medication Verification, scan John's wristband.)* "SafeHaven identifies the patient — John, room 204." *(Scan the Metoprolol Succinate ER 25mg product.)* "Every check passes against his current active order." *(VERIFIED, click Confirm Administration.)*
>
> "Now here's the case barcode scanning alone can't catch." *(Scan the same patient's wristband, then scan the Metoprolol Succinate ER **50mg** product — deliberately using the product that matches his old, stopped order instead of today's.)* "The barcode reads perfectly fine — it's a real product. But SafeHaven checks it against the *current* order, not just what's printed on the package." *(BLOCKED: "Previous 25 mg order is stopped. Current active order is 50 mg.")* "This is the exact error barcode-only systems miss."
>
> "One more — same drug name, different product entirely." *(Scan Metoprolol **Tartrate** 25mg against the Succinate ER order.)* "Same name, same strength — but a different formulation is a different medication clinically." *(BLOCKED: formulation mismatch.)* "SafeHaven never reduces this to just a name-and-dose check."

Under five minutes, and every state shown (VERIFIED, BLOCKED ×2) is a real deterministic comparison, not a canned response.

---

## 17. What Not to Build

- Full pharmacy inventory
- Drug-drug interaction database or engine
- AI prescribing / AI dose calculation / automatic treatment recommendations
- Full commercial BCMA replacement, real Epic/Cerner integration, insurance workflows, pharmacy dispensing
- Smart cabinets, RFID
- Module 3
- A new native mobile app (the web app's camera access is sufficient)
- Full enterprise RBAC (§14)
- OCR/computer vision (§10) — designed, not built, this pass
- Controlled override flow — designed, not built, this pass (see below)
- Allergy checking — genuinely optional; **recommendation: move to Phase 2.** `PatientCondition` cannot safely represent allergies today (it's diagnoses, no type field), so this would require a small new field/table on its own, for one optional demo scenario. Not worth the prototype effort unless the demo specifically needs it.

**On controlled override:** the spec asks for a judgment call. Recommendation — **defer to Phase 2.** It adds a full authenticated-reason-timestamp-audit workflow for a case (a nurse consciously bypassing a BLOCKED result) that isn't needed to demonstrate the core value proposition, and every required demo scenario (§15/§16) is servable with just Rescan/Request Review. If wanted later, §6's `override_reason` field and §13's two audit events are already designed and ready.

---

## 18. Files Likely to Change

| File / folder | Reason | Size |
|---|---|---|
| `backend/app/reference/medication_products.py` (new) | Static barcode→product mapping, mirrors `medication_purpose.py` | SMALL |
| `backend/app/medication_verification/` (new package: `models.py`, `schemas.py`, `service.py`, `router.py`) | `AdministrationEvent` model + deterministic engine + endpoints | MEDIUM |
| `backend/alembic/versions/` (new migration) | One new table: `administration_events` | SMALL |
| `backend/app/audit/models.py` | +6-8 new `AuditEventType` string values | SMALL |
| `backend/app/main.py` | Register the new router | SMALL |
| `backend/app/patients/router.py` (or a small new module) | `GET /patients/by-code/{code}` | SMALL |
| `frontend/package.json` | +1 dependency: `@zxing/browser` | SMALL |
| `frontend/src/components/BarcodeScanner.tsx` (new) | Reusable camera-scan component, used twice (patient, medication) | MEDIUM |
| `frontend/src/features/medication-verification/` (new) | Scan/result screens | MEDIUM–LARGE |
| `frontend/src/pages/MedicationVerificationPage.tsx` (new) | Hosts the workflow | MEDIUM |
| `frontend/src/App.tsx` | +1 route | SMALL |
| `frontend/src/components/AppLayout.tsx` | +1 nav link (optional) | SMALL |

**No Module 1 file changes anywhere in this list.**

---

## 19. Implementation Order

1. Static `MedicationProduct` reference mapping + lookup function (no DB, no migration).
2. `AdministrationEvent` model + one migration (smallest schema footprint, done early).
3. Deterministic verification engine as a pure function, unit-tested in isolation first — same "pure function before wiring it to HTTP" pattern already used for `compare_facts()` in Module 1.
4. `GET /patients/by-code/{code}` and `GET /medication-products/{barcode}` endpoints.
5. `POST /medication-verification/verify` and `/administer`, wired to audit events.
6. Backend tests for every scenario in §15 — fully deterministic from day one, no mock/live LLM toggle needed anywhere in this module.
7. Frontend: install `@zxing/browser`, build one reusable `BarcodeScanner` component.
8. Frontend: `MedicationVerificationPage` — scan steps + result screen, wired to the new endpoints.
9. Frontend: route + nav link.
10. Live/Playwright verification of every demo scenario in a real browser.
11. *(Only if separately approved)* controlled override, allergy check, OCR fallback — explicitly last, explicitly optional, per §17.

---

*Read-only design report. No code, models, or migrations were created. Awaiting approval before implementation begins.*

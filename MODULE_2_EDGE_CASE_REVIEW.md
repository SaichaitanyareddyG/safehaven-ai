# SAFEHAVEN AI — Module 2 Edge Case & Safety Review

Read-only. No code changed producing this report. Every "supported" claim below was verified by reading the actual current code (`app/medication_verification/service.py`, `router.py`, `models.py`), not assumed — several genuine gaps turned up that were not visible from the design documents alone.

**Headline finding:** the core comparison engine (patient/drug/dose/formulation/route/order-status/time) is solid and already covers scenarios 1–6, 9, 10, 13–15, 17–18. But three related, serious gaps exist around the *time* dimension of safety, not the *comparison logic*: **nothing revalidates between initial verification and final administration, nothing detects a duplicate administration of the same order, and the confirm step has a real (if narrow) concurrency race.** These three are the load-bearing reason this review exists, and are the main thing standing between "the demo works" and "this wouldn't misbehave in an actual bedside sequence."

---

## 1. Edge Case Matrix

| # | Scenario | Supported now? | Expected result | Bucket | Required change | Risk |
|---|---|---|---|---|---|---|
| 1 | Wrong patient | ✅ Yes (`NO_MATCHING_ORDER`) | BLOCKED | Built | None | — |
| 2 | Wrong medication | ✅ Yes (`NO_MATCHING_ORDER`) | BLOCKED | Built | None | — |
| 3 | Wrong strength | ✅ Yes (`_check_dose`) | BLOCKED | Built | None | — |
| 4 | Wrong formulation | ✅ Yes (`_check_formulation`) | BLOCKED | Built | None | — |
| 5 | Wrong route | ✅ Yes (`_check_route`) | BLOCKED | Built | None | — |
| 6 | Stopped/cancelled order scanned | ✅ Yes (`STOPPED_ORDER_SCANNED`) | BLOCKED | Built | None | — |
| 7 | Order changed after patient scan, before medication scan | ⚠️ Partially — each `verify()` call already reads live data, so this specific window is safe. The real gap is §8, not §7. | N/A once medication is actually scanned | Built (by construction) | None | Low |
| 8 | Order changes after VERIFIED, before Confirm Administration | ❌ **No** — `administer()` (service.py:503-523) trusts the `verification_result` stored at scan time; it never re-fetches the order or re-runs comparison. | Should BLOCK with "order changed since verification" | **Must build now** | Revalidation in `administer()` (see §5) | **High** |
| 9 | Multiple active orders, same drug, different schedule | ✅ Yes — dose-based narrowing already resolves the unambiguous case; genuinely ambiguous (same dose, 2+ active orders) already returns REVIEW_REQUIRED (`MULTIPLE_ACTIVE_ORDERS`) | REVIEW_REQUIRED only when genuinely ambiguous | Built | None | — |
| 10 | No active order for this medication | ✅ Yes (`NO_MATCHING_ORDER`) | BLOCKED | Built | None | — |
| 11 | Duplicate administration (same order, already given) | ❌ **No** — nothing checks prior `AdministrationEvent` rows for this `care_instruction_id` before allowing a new one. | BLOCKED "already administered at HH:MM" | **Must build now** | New pre-check in `verify()`/`administer()` (see §6) | **High** |
| 12 | Repeated/duplicate scanner event | ✅ Effectively safe — `verify()` is a pure read+compute; re-running it twice is harmless (just extra audit rows). Actual risk is concentrated in `administer()`, covered by #8/#11 fixes. | Same result both times | Built (as a side effect of stateless design) | None beyond §5/§6 | Low |
| 13 | Unknown medication barcode | ✅ Yes (`PRODUCT_NOT_FOUND`) | REVIEW_REQUIRED | Built | None | — |
| 14 | Unreadable barcode → image fallback | ✅ Yes, full flow built and live-tested | REVIEW_REQUIRED until confirmed, then real result | Built | None | — |
| 15 | OCR low confidence | ✅ Yes — `confidence: "low"` surfaced, nurse must review every field before confirming; nothing is auto-applied | Nurse decides, not AI | Built | None | — |
| 16 | OCR vs. barcode conflict | ✅ N/A by construction — a nurse takes exactly one path (scan OR photograph) per medication identification; there is no state where both a barcode result and an OCR result exist to conflict | — | Built (avoided by design) | None | — |
| 17 | Manual patient ID fallback — enough identity shown? | ⚠️ Partial — name, patient code, and room are shown; DOB is fetched but not displayed at this step | Name + ID shown; DOB not surfaced | Nice for demo | Add DOB to the patient summary card | Low |
| 18 | Room changed, patient ID stable | ✅ Yes — room is display-only, never read by the comparison engine at all | Never blocks on stale room | Built | None | — |
| 19 | Time window | ✅ Yes, configurable ±60min, explicitly labeled prototype config, never BLOCKs alone | WARNING, not BLOCKED | Built | None | — |
| 20 | PRN medication | ✅ Safe by accident of design — no time-of-day keyword in a PRN order means the time check is skipped, not misapplied; the engine never asks "does the patient need this now" | VERIFIED reachable if all other checks pass, no clinical-need judgment attempted | Built (behavior is safe); **demo data should still avoid PRN examples** | None to code; keep PRN out of demo data | Low |
| 21 | Unit normalization (mg vs g) | ❌ No — `_check_dose` requires exact numeric + exact unit-string match; 500mg vs 0.5g would BLOCK as a mismatch today | Fails closed (BLOCKED), never fails open | Phase 2 | mg↔g conversion only, if ever needed; **do not build mcg↔mg conversion** (real harm risk in a misconversion) | Low (fails safe already) |
| 22 | Brand vs. generic name | ✅ N/A given current scope — all 5 reference products and all demo orders use canonical generic names only, which is exactly the "restrict to canonical names" safe option | Works as long as scope stays generic-name-only | Built (by scope constraint) | None now; brand mapping is Phase 2 if ever needed | Low |
| 23 | Multiple tablets for one dose | ⚠️ Partial — currently reported as a plain `DOSE_MISMATCH` (BLOCKED), same as a genuinely wrong dose. It should instead say "multi-tablet dosing not supported by this prototype" | Should be REVIEW_REQUIRED/unsupported, not indistinguishable from a real error | Phase 2 | A distinct "unsupported quantity" check | Low today (no demo product needs this) |
| 24 | Half tablet | Same as #23 | Same as #23 | Phase 2 | None now | Low |
| 25 | Liquid medication (concentration/volume) | Not applicable — no liquid products in the reference catalog | N/A | Phase 2 | None | — |
| 26 | Multi-dose vial | Not applicable | N/A | Phase 2 | None | — |
| 27 | Prefilled syringe (e.g. Enoxaparin) | Not built, but architecturally trivial — same static-dict pattern, no engine change, since a ready-to-administer syringe is a simple 1:1 product like a tablet | Would work like any oral product once one is added | **Candidate: first post-tablet extension** | One new `MedicationProduct` entry + one demo order | Low |
| 28 | IV/infusion | Not applicable, explicitly out of scope | N/A | Phase 2 | None | — |
| 29 | Allergy | ❌ No safe structured allergy source exists — `PatientCondition` is diagnoses only, no type field | N/A | Phase 2 (confirmed again by inspection, unchanged since the design report) | A real allergy field/table, deliberately not built | — |
| 30 | Backend/network failure during verify | ✅ Safe by construction — any exception surfaces as an HTTP error, never a fabricated VERIFIED; frontend shows a generic retry message | Never VERIFIED on failure | Built (fail-safe by default) | None required; see §10 on whether a dedicated state is worth adding | — |
| 31 | Product reference lookup fails | ✅ Same as #30 — `lookup_medication_product` returning None already yields `REVIEW_REQUIRED` (`PRODUCT_NOT_FOUND`), and a genuine exception fails the same safe way as #30 | REVIEW_REQUIRED / error | Built | None | — |
| 32 | Auth expires mid-workflow | ✅ Yes, for free — every endpoint requires `get_current_user`; an expired JWT 401s on the next call including `administer`, with no special-casing needed | Confirm fails, must re-authenticate | Built (by existing generic auth) | None | — |
| 33 | Two nurses / concurrent confirm | ⚠️ Partial — `AlreadyAdministeredError` catches a *sequential* double-confirm, but the read-then-write in `administer()` has no row lock, so two requests arriving in the same instant could both pass the `administered_at is None` check before either commits | Second request should always lose cleanly | **Must build now** | `SELECT ... FOR UPDATE` in `administer()` (see §7) | **Medium** (narrow window, but a real race) |
| 34 | Same product scanned for two different patients | ✅ N/A by design — `MedicationProduct` is stateless reference data with no per-session memory; every `verify()` call is a pure function of the `patient_code` + `barcode` actually submitted, never a "remembered" patient | Always uses the currently-submitted patient | Built | None | — |
| 35 | Patient re-scanned mid-workflow | ✅ N/A by UI construction — Step 2 has no patient-scanning input at all; the only way to change patient is "Start Over," which fully resets frontend state, and the backend never carries session state between calls anyway | Cannot happen in the current UI | Built | None | — |
| 36 | Medication scanned before patient | ✅ N/A by UI construction — Step 2 (medication) isn't reachable until Step 1 (patient) succeeds; there is no route to the medication scanner without a resolved patient | Blocked by page flow itself | Built | None | — |
| 37 | Confirm called without valid verification | ✅ Yes — `administer()` requires a real `verification_id` that must already exist in the DB with `verification_result` in (VERIFIED, WARNING); there is no code path to confirm administration from raw client-submitted facts | 404/422, never silently succeeds | Built | None | — |
| 38 | Tampered frontend data | ✅ Yes — the frontend never submits medication facts for comparison at confirm time, only an opaque server-generated `verification_id`; all patient/order/product resolution happens server-side in both `verify()` and `verify_confirmed()` | Browser cannot influence the PASS/BLOCK decision | Built | None | — |
| 39 | Stale verification (confirmed long after scan) | Same underlying issue as #8 — there is currently no expiry or re-check on old `verification_id`s | Should revalidate or expire | **Must build now** | Same fix as §8 covers this | High |
| 40 | Unsupported medication form (if catalog ever grows) | ⚠️ Latent — not an active bug today (all 5 products are oral tablets), but nothing currently distinguishes "wrong medication" from "right medication, unsupported form," so adding a liquid/IV product to the catalog without a guard would misreport as a normal mismatch | Should be a distinct REVIEW_REQUIRED | Phase 2 (guard needed *before* the catalog ever grows beyond tablets) | A `formulation`/form allow-list check | Low today, real before any catalog expansion |

---

## 2. Missing Edge Cases (not in your list)

Two realistic ones worth naming, kept to what actually affects this architecture — not padding the list:

- **Instruction rejected or edited after a STOPPED/ACTIVE order was already scanned as part of a multi-order household.** Not materially different from #8/#39 — the same revalidation fix covers it, since it re-derives clinical_status fresh regardless of *why* it changed (clinician stopped it, corrected it, or superseded it).
- **The nurse account itself gets deactivated/discharged patient re-admitted with a new encounter mid-workflow.** Neither is currently a real risk: nurse deactivation isn't a concept that exists yet (no role/status field on `User` beyond `role` string), and patient discharge doesn't retroactively invalidate an in-flight verification — but this is speculative beyond what today's architecture needs to handle. Noting it, not recommending action.

Nothing else in your 40 was missing something the current architecture needs to worry about — the list is thorough.

---

## 3. Final Verification Algorithm (with revalidation)

```
verify(patient_code, barcode_or_confirmed_candidate):
    resolve patient                          -> not found: BLOCKED
    resolve product (barcode lookup OR confirmed candidate)
                                              -> barcode unresolved: REVIEW_REQUIRED
    find same-drug-family orders (any clinical_status)
                                              -> none: BLOCKED (no matching order)
    split into ACTIVE / STOPPED·COMPLETED
    if scanned dose matches only a STOPPED/COMPLETED order: BLOCKED (order changed/stopped)
    if scanned dose matches >1 ACTIVE order: REVIEW_REQUIRED (ambiguous)
    if scanned dose matches exactly 1 ACTIVE order: that is "order"
    if scanned dose matches 0 ACTIVE orders: "order" = the active order for
        this drug (for an informative dose-mismatch message), proceed to hard checks
    hard checks against "order": dose, route, formulation
    soft check: time window
    -> BLOCKED / REVIEW_REQUIRED / WARNING / VERIFIED (unchanged from today)
    PERSIST the resolved product's fields (name/strength/unit/formulation/route)
        on the AdministrationEvent — not just the barcode string (needed so
        administer() can revalidate without re-deriving an image-identified
        product from a placeholder barcode)


administer(verification_id):                  # THE FIX THIS REVIEW IS FOR
    event = fetch AdministrationEvent by id     -> not found: 404
    if event.verification_result not in (VERIFIED, WARNING): reject (422)
    if event.administered_at already set: reject (409) — under a row lock (see §7)

    # --- NEW: revalidate before trusting the old result ---
    re-resolve the patient's CURRENT same-drug-family orders, fresh, right now
    re-run the SAME hard checks (dose/route/formulation/order-status) using
        the PERSISTED product fields from the original verification
    if the fresh result is no longer VERIFIED/WARNING, OR resolves to a
        DIFFERENT care_instruction_id than originally recorded:
            do NOT administer
            return BLOCKED, reason=ORDER_CHANGED_SINCE_VERIFICATION,
                showing what changed (old order vs. new order/status)
    # --- NEW: duplicate-administration check (see §6) ---
    if this care_instruction_id already has another AdministrationEvent with
        administered_at within the configured duplicate window:
            do NOT administer
            return BLOCKED, reason=ALREADY_ADMINISTERED, showing when/by whom

    otherwise: proceed exactly as today (set administered_by/at, audit event)
```

---

## 4. Order Matching Strategy

Already correct, unchanged by this review:

- **Zero matches** (no order for this drug at all, any status) → BLOCKED, `NO_MATCHING_ORDER`.
- **Exactly one ACTIVE match** → use it.
- **Multiple ACTIVE matches, only one dose-compatible** → use the dose-compatible one (not ambiguous — the dose itself disambiguates).
- **Multiple ACTIVE matches, more than one dose-compatible** → REVIEW_REQUIRED, `MULTIPLE_ACTIVE_ORDERS` — never silently pick one.
- **Only STOPPED/COMPLETED matches, dose-specific** → BLOCKED, `STOPPED_ORDER_SCANNED`, with the specific "previous X, current active Y" message.
- **Same drug, multiple schedules (different times, different doses)** → each is really a different order by dose; the dose-based narrowing above already separates them correctly.

---

## 5. Revalidation Strategy

**At medication scan (`verify`):** already fully live-data — no caching, no staleness possible, since it's computed fresh on every call. No change needed here.

**At Confirm Administration (`administer`):** this is the fix. Before flipping `administered_at`, re-run the exact same order-resolution and hard-check logic used at scan time, using the *persisted* product identity from the original verification (not re-asking the nurse to rescan). If the fresh result disagrees with the stored one in any way that matters (order no longer active, dose/route/formulation no longer match, or a different order now applies), refuse the confirmation and surface exactly what changed. This is the single most important change this review identifies — everything else in this document is either already fine or a Phase 2 scope call; this one is a genuine hole in the safety story as it exists today.

---

## 6. Duplicate Administration Strategy

Minimum safe design: before finalizing `administer()`, check whether the same `care_instruction_id` already has a *different* `AdministrationEvent` row with `administered_at` set within a configurable window (reuse the existing `_TIME_TOLERANCE_MINUTES` concept — e.g., twice that window, so a genuinely separate scheduled dose a few hours later is never blocked, but a re-scan of the same dose minutes later is). If found, reject with `ALREADY_ADMINISTERED`, showing when and by whom. This does not require a full eMAR schedule-slot model — a simple "has this order been administered recently" query against the existing table is sufficient for the prototype's scope.

---

## 7. Concurrency Strategy

The narrow, real race is in `administer()`'s read-then-write. Fix: wrap the read in `db.query(AdministrationEvent).filter(...).with_for_update().first()` so a second concurrent request blocks on the database row lock until the first transaction commits, then correctly sees `administered_at` already set and raises `AlreadyAdministeredError` instead of racing past the check. This is a small, standard SQLAlchemy/Postgres pattern — no new infrastructure, no distributed locking needed for a single-Postgres-instance prototype.

Double-click protection at the frontend (disabling the Confirm button while the mutation is pending) already exists as a UX nicety, but the backend fix above is what actually makes it safe regardless of frontend behavior — consistent with #38's "browser never decides" principle.

---

## 8. OCR Fallback Strategy

Unchanged from what's already built and live-tested: barcode fails → nurse taps "Photograph Label" → one vision call extracts a candidate (medication name, strength, unit, formulation, route, confidence) → every field is shown editable, nothing pre-locked → nurse must explicitly confirm → only the confirmed fields (which may differ from what OCR suggested) enter the same deterministic engine as any barcode scan → the result is permanently tagged `identification_method=IMAGE` and disclosed as such in the UI, regardless of what result state it reaches. Low OCR confidence changes nothing structurally — it's surfaced to the nurse as a caution to look more carefully, never as a reason to auto-decide.

---

## 9. Supported Medication Scope

| Scope | Status |
|---|---|
| Unit-dose oral tablets/capsules | **NOW** — built, all 5 reference products, all demo orders |
| One prefilled syringe (e.g. Enoxaparin) | **NEXT** — architecturally trivial, same pattern, not yet added |
| Multiple tablets per dose, half tablets, liquids, multi-dose vials, IV/infusion, weight-based/titrated dosing, insulin calculation | **PHASE 2** — none touched, and per #23/#24/#40, the engine should eventually distinguish "unsupported form" from "wrong medication" before any of these are added |

---

## 10. Final Result States

**VERIFIED / WARNING / REVIEW_REQUIRED / BLOCKED — unchanged, all four confirmed correct and sufficient.**

**On a 5th `SYSTEM_UNAVAILABLE` state: recommend NOT adding one.** A backend/provider failure is an *operational* failure to produce any result at all, not a verification *outcome* to audit alongside the other four — and in several failure modes (DB unreachable) there'd be nothing to reliably persist a state to in the first place. The existing behavior — any exception surfaces as an HTTP error, the frontend shows a generic "could not verify, please retry" message, and nothing is ever fabricated as VERIFIED — already satisfies the actual safety requirement in #30/#31 without adding a state that would need to be persisted, audited, and reasoned about alongside real verification outcomes. Keep it as an HTTP-layer concern, not a domain state.

---

## 11. Minimum Data Model Changes

One additive change, justified directly by §5/§8's revalidation need — not by any other scenario in this review:

```
AdministrationEvent gains (all populated at verify-time, for both barcode and
image-identified paths):
    identified_medication_name   str
    identified_strength_value    float
    identified_strength_unit     str
    identified_formulation       str
    identified_route             str
```

Why: `administer()`'s revalidation (§5) needs to re-run the exact same hard checks it ran at scan time, using the *same product identity* — for a barcode scan this could be re-derived by looking the barcode up again (static data, never changes), but for an image-confirmed result there is no real barcode to look up (`product_barcode` is the literal placeholder string `"IMAGE-CONFIRMED"`), so the confirmed fields must be persisted to be re-checked later. Storing them for both paths (rather than only the image path) keeps `administer()`'s revalidation logic uniform — one code path, not two.

No other new model or field is justified by this review. `MedicationProduct` stays a static reference dict, not a table (unchanged conclusion). No new `MedicationOrder` model (unchanged conclusion) — `CareInstruction` remains sufficient, confirmed again by this review finding nothing that requires a second order representation.

---

## 12. Final API Needs

No new endpoints. The existing four (`verify`, `administer`, `identify-from-image`, `verify-confirmed`) are unchanged in shape — §5/§6/§7's fixes are internal to `administer()`'s implementation, not a new API surface.

---

## 13. Final Test Cases (for the must-build-now items)

- Order is STOPPED between initial `verify()` (VERIFIED) and `administer()` → `administer()` rejects, does not set `administered_at`, reports the change.
- Order's dose is changed between `verify()` and `administer()` → same rejection.
- A *different* order becomes the dose-match between `verify()` and `administer()` (e.g. a second active order for the same drug appears) → rejection, not a silent switch.
- Same `care_instruction_id` already has an administered `AdministrationEvent` within the duplicate window → a fresh `verify()` + `administer()` attempt is rejected as a duplicate.
- A dose given 8+ hours ago for a twice-daily order does **not** block the next legitimate scheduled dose (duplicate window must not be absurdly wide).
- Two concurrent `administer()` calls against the same `verification_id` → exactly one succeeds, the other gets `AlreadyAdministeredError`, never both.
- Image-identified `verify_confirmed()` → `administer()` still correctly revalidates using the persisted confirmed fields (not the barcode placeholder).

---

## 14. Final Demo Cases

Your proposed 8 are exactly right and match what's actually strongest to show — no changes recommended:

1. VERIFIED (correct patient + medication)
2. BLOCKED — wrong patient
3. BLOCKED — wrong strength
4. BLOCKED — wrong formulation
5. BLOCKED — stopped/outdated order
6. **Order changes after verification, caught at Confirm** (the fix in this review makes this demonstrable for the first time)
7. **Duplicate administration blocked** (also newly demonstrable after this review's fix)
8. Barcode failure → image fallback → nurse confirmation → real result

Scenarios 6 and 7 currently could **not** be honestly demoed — this review is what makes them true rather than aspirational.

---

## 15. Implementation Impact

| File | Change | Size |
|---|---|---|
| `backend/app/medication_verification/models.py` | +5 columns on `AdministrationEvent` (identified product fields) | SMALL |
| `backend/alembic/versions/` | One migration for the above | SMALL |
| `backend/app/medication_verification/service.py` | Populate the new fields in `_persist_and_audit`; add revalidation + duplicate-check + row-lock logic in `administer()` | MEDIUM |
| `backend/app/audit/models.py` | +1-2 new reason codes as audit metadata values (no new event *types* needed — reuse `MEDICATION_MISMATCH`) | SMALL |
| `backend/tests/integration/test_medication_verification.py` | New tests per §13 | MEDIUM |
| Frontend | New rejection messages surfaced on the existing result view (no new screens) | SMALL |

Nothing else in this review requires a code change — everything else in the matrix is either already correct or explicitly Phase 2.

---

## 16. Final Go / No-Go

**GO, conditional on one thing.** The workflow, supported medication scope, verification semantics, and failure/edge-case behavior are all sound and don't need further architecture discussion — 34 of 40 scenarios are already correctly handled by design, and the remaining 6 are cleanly scoped to Phase 2 with no open questions.

The one thing that should be built **before** calling Module 2 done, not after: **§5's revalidation-at-confirm fix, plus §6's duplicate-administration check and §7's concurrency lock.** These three are small (§15's estimate: one migration, changes concentrated in one function) but they're the difference between "the demo looks right" and "this wouldn't misbehave in something resembling a real bedside sequence" — and they're exactly the gap a later redesign would otherwise be needed to close. Everything else here confirms the existing design holds; this is the one place it doesn't yet, and it's a small, well-scoped fix, not a rethink.

No further decisions are needed from you to proceed — this review found the concrete gap it was looking for, named the fix, and confirmed nothing else needs to change first.

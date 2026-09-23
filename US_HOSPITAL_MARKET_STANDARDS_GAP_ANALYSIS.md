# SafeHaven AI vs. US Hospital Market Standards — Gap Analysis

**Scope:** Module 1 (Medication Understanding / Health Literacy) and Module 2 (Medication
Administration Verification), checked against real US hospital regulatory/practice standards —
not against a hypothetical ideal, and not assuming enterprise-scale rebuild. Every gap below is
checked against what the code actually does today (grepped, not assumed) and against the
standard's real source. Module 3 (wearables) is out of scope — not started.

**How to read this:** each item names the standard, what SafeHaven does today, the gap, and a
prototype-appropriate fix. Priority is about patient-safety/compliance materiality, not effort.

---

## Sources checked

- The Joint Commission — National Patient Safety Goals (NPSGs), transitioning to National
  Performance Goals (NPGs) effective January 2026 for the Hospital program.
- BCMA (Barcode Medication Administration) industry practice — the "five rights" standard
  (right patient, medication, dose, route, time) and the badge+wristband+medication three-way
  scan workflow.
- ONC/ASTP Health IT Certification — HTI-1 (USCDI v3, mandatory Jan 2026), FHIR API requirements
  for certified EHRs, CDS certification criteria (drug-drug/drug-allergy interaction checking).
- ISMP (Institute for Safe Medication Practices) — List of High-Alert Medications in Acute Care
  Settings (2024), and its recommended independent double-check practice.
- AHRQ — Health Literacy Universal Precautions Toolkit (3rd ed.), specifically the teach-back
  method (Tool 5).
- CMS Conditions of Participation — nursing/medication administration record documentation
  requirements.
- Title VI of the Civil Rights Act / CLAS standards — language access for Limited English
  Proficiency (LEP) patients.

---

## Module 2 — Medication Administration Verification

### 🔴 Critical

**1. Single patient identifier, not two. — ✅ BUILT**
- *Standard:* Joint Commission's longstanding NPSG.01.01.01 (folded into the 2026 NPGs) requires
  **two** patient identifiers before any medication administration — never a room number, never
  one scan alone. Real BCMA workflows scan the wristband *and* the clinician visually/verbally
  confirms name + DOB.
- *Was:* `ScanOrManualEntry` / `patientScanMutation` resolved the patient from **one** value —
  the patient code (`P1001`) — whether scanned or typed. The patient's name was displayed
  afterward, but nothing required the nurse to actively confirm it matched before proceeding.
- *Built:* a new `confirm-patient` step (Step 2) in `MedicationVerificationPage.tsx`, inserted
  between patient lookup and medication scanning — resolving the code now shows the patient's
  full name and date of birth and requires an explicit "Yes, this is [Name]" click
  (`patient-confirm-identity-button`) before the medication step (now Step 3) unlocks. A
  "No — wrong patient" button (`patient-reject-identity-button`) sends the nurse back to Step 1
  instead of silently correcting course. DOB is also now shown in the persistent patient banner
  visible throughout every later step, not just at the one-time confirmation. UI-only, no schema
  change. Verified live via Playwright: the medication step is unreachable before confirming, the
  reject path returns to Step 1, and the full existing regression flow
  (`frontend/verify_all_flows.mjs`, updated for the new step) still passes end-to-end with zero
  console errors.

**2. No allergy check at all. — ✅ BUILT**
- *Standard:* Drug-allergy interaction checking is an ONC CDS certification criterion
  (170.315(a)(4)) and one of the most basic hospital medication-safety controls that exists.
- *Was:* grepped the whole backend — there was no `Allergy`/`AllergyIntolerance` entity anywhere.
  `PatientCondition` exists but models diagnoses, not allergies, and is explicitly never
  consulted by Module 2's verification engine.
- *Built:* a new `PatientAllergy` model (`app/allergies/` — mirrors `PatientCondition`'s shape and
  CRUD conventions exactly: allergen, optional reaction/severity, free text, no coded
  terminology) plus a new `_check_allergy` deterministic check in
  `medication_verification/service.py`, wired in at the top of `_resolve_and_compare` so it runs
  on **every** verification path and always forces `BLOCKED` on a match — overriding what would
  otherwise be VERIFIED, WARNING, or even REVIEW_REQUIRED (an allergy match is never allowed to be
  softened by order ambiguity). Also re-checked fresh inside `_revalidate_order_still_matches` at
  `administer()` time, so an allergy documented *after* the scan but *before* the confirm still
  stops the dose — same "never trust the stale scan-time result" pattern as the order-changed and
  duplicate-administration checks already in that function.
  Surfaced to the clinician via a new `PatientAllergiesPanel` on the patient detail page
  (alongside the existing conditions panel) and to Module 2's UI as a new "Allergy" row in
  `VerificationResultView`. Migration `b9300aa8f28f`. 4 new tests
  (`test_medication_verification.py`), all passing; 372 backend tests total. Verified live via
  Playwright: documented a Metoprolol allergy through the UI, scanned a matching Metoprolol
  Succinate order, confirmed the result is BLOCKED with no confirm-administration button shown.

**3. No high-alert medication safeguard. — ✅ BUILT**
- *Standard:* ISMP's High-Alert Medications list (insulin, anticoagulants, opioids,
  concentrated electrolytes, chemotherapy, etc.) calls for **independent double-checks** —
  a second clinician verifies before administration — precisely because these drugs cause
  disproportionate harm when wrong.
- *Was:* `MedicationProduct` had no `high_alert: bool` field, and there's still only one user
  role (`"clinician"`), so there was no way to require or check a second person at all.
- *Built, prototype-scoped as originally planned:* `high_alert: bool = False` added to
  `MedicationProduct` (catalog entry `MED-WARFARIN-5` — an anticoagulant — flagged `True`,
  matching ISMP's list); persisted onto the `AdministrationEvent` at verify time
  (`identified_high_alert`, migration `0ec7c07af10f`) so it survives to the administer step
  unchanged, same pattern as the other `identified_*` fields. `administer()` now requires a
  second clinician's **actual credentials** (email + password, authenticated via the same
  `AuthProvider` login uses — not just a name picked from a list) whenever the identified product
  is high-alert, rejects if the co-signer is the same person as the administering clinician, and
  records `co_signed_by`. Frontend: a new amber co-sign panel appears in
  `VerificationResultView.tsx` only for high-alert results, and the confirm button stays disabled
  until both co-signer fields are filled. Doesn't require the item-13 role system after all — an
  independent double-check just needs a genuinely *different* authenticated person, not a
  different *role*. 6 new backend tests; full suite now 391/391. Verified live end-to-end
  (co-sign panel appears, confirm stays disabled until both fields are filled, a valid second
  clinician's login successfully co-signs and records the administration).

### 🟠 High

**4. No nurse re-authentication at the point of scan.**
- *Standard:* the real BCMA "three-way scan" is badge (clinician) + wristband (patient) +
  medication. The badge scan re-proves *who is actually standing at the bedside right now* — a
  JWT in localStorage from login proves who's using the browser, not who's holding the syringe.
- *Today:* `administered_by` is taken from the logged-in session; there's no re-confirmation step
  at the moment of administration.
- *Fix:* not worth building real badge-scan hardware support for a prototype, but a lightweight
  password or PIN re-entry immediately before `confirm-administration-button` would close the
  same class of gap cheaply and is a realistic thing to demo.

**5. No drug-drug interaction / therapeutic-duplication check. — ✅ BUILT (curated subset)**
- *Standard:* also an ONC CDS certification criterion, and one of the most common real-world
  catches (e.g., two different beta-blockers active at once — which is exactly what Patient A's
  and Patient B's demo orders would look like if given to the *same* patient).
- *Was:* `_find_medication_instructions` only compared the *scanned* product against orders for
  the *same* drug family — it never looked across the patient's other active, unrelated orders.
- *Built, prototype-scoped exactly as originally flagged (the "curated subset" option):* a new
  `app/reference/drug_interactions.py` — a small, hand-curated table of well-established
  interaction pairs (e.g. warfarin+NSAIDs, beta-blocker+verapamil/diltiazem), each tagged SEVERE
  or MODERATE — same static-table precedent as `medication_purpose.py`/`medication_products.py`/
  `condition_explainers.py`, not a real First Databank/Lexicomp integration. A new
  `_check_drug_interactions` cross-references the scanned product against the patient's *other*
  active medications: a SEVERE match forces `BLOCKED` (same absolute-override treatment as an
  allergy match — never softened by an otherwise-clean dose/route/time result); a MODERATE match
  forces `WARNING` (requires the same "Acknowledge & Confirm" step a timing warning already
  does — never silently ignored, never treated as absolute). Also re-checked (SEVERE only) in the
  administer()-time revalidation, so a new interacting medication started between scan and
  confirm still stops the dose. New "Drug Interactions" row in `VerificationResultView.tsx`. 4
  new backend tests (SEVERE blocks, MODERATE warns, no-interaction passes, post-scan new-SEVERE
  blocks administer); full suite now 395/395. Verified live: a Metoprolol Succinate scan is
  correctly BLOCKED with the specific interacting drug (Diltiazem) named in the check detail, and
  no confirm-administration path is offered.

**6. Barcodes are prototype strings, not NDC/GS1 format.**
- *Standard:* real unit-dose packaging carries NDC-11 (National Drug Code) or GS1
  DataMatrix-encoded barcodes, which is what a real pharmacy dispensing system and a real EHR
  would both expect.
- *Today:* `MED-LISINOPRIL-10`-style hand-authored strings.
- *Fix:* not worth changing for the prototype (there's no real pharmacy system to interoperate
  with yet) — but worth being explicit that this is a deliberate simplification, not an oversight,
  the same way `medication_purpose.py` and `medication_products.py` already document themselves.

### 🟡 Medium

**7. No PRN (as-needed) administration workflow.**
- *Standard:* CMS/nursing documentation standards require capturing *why* a PRN dose was given
  (e.g., "pain 7/10") and a later effectiveness reassessment — a PRN med isn't just "give it,
  done" the way a scheduled dose is.
- *Today:* `"as needed"`/`"prn"` is recognized by the extraction normalization regex
  (`app/validation/normalization.py`), but `administer()` has no PRN-specific fields at all —
  it's treated identically to a scheduled dose.
- *Fix:* add an optional `administration_reason` field, required only when the order's frequency
  is PRN. Small, additive, no change to the non-PRN path.

**8. No FHIR-shaped interoperability surface.**
- *Standard:* ONC HTI-1 makes USCDI v3 mandatory for certified health IT in January 2026, and
  certified EHRs must expose FHIR APIs (`Patient`, `MedicationRequest`, `MedicationAdministration`,
  `AllergyIntolerance`, `Condition`) for patient access and third-party exchange.
- *Today:* SafeHaven's API is a bespoke REST shape with no FHIR resource modeling.
- *Fix:* this is the single biggest architectural gap if SafeHaven ever needs to plug into a real
  hospital's Epic/Cerner instance — but it's a legitimately large scope item (resource mapping,
  versioning, a `$everything` operation, SMART-on-FHIR auth), not a quick patch. Recommend
  explicitly deferring with this written down, rather than attempting a partial FHIR layer that
  isn't actually spec-compliant and creates false confidence.

---

## Module 1 — Medication Understanding / Health Literacy

### 🔴 Critical

**9. Comprehension check is a button, not teach-back. — ✅ BUILT**
- *Standard:* AHRQ's Health Literacy Universal Precautions Toolkit identifies teach-back — the
  patient explains the instruction back in their own words — as the single most effective health
  literacy technique measured (in AHRQ's own training data, comprehension-check quality nearly
  tripled with teach-back vs. without). A "Yes, I understand" click verifies nothing; patients
  reliably over-report understanding.
- *Was:* the comprehension-feedback control was a plain confirm/deny/ask-care-team button set.
- *Built:* clicking "Yes, I understand" now reveals a teach-back prompt — "Just to double check —
  in your own words, what do you take and why?" — instead of immediately confirming. The answer is
  checked by a new deterministic, dependency-free word-overlap comparator
  (`_check_teach_back` in `app/patient_feedback/service.py`) against the order's own structured
  facts (medication name, frequency/timing, and — reusing `resolve_why` — only a Tier
  1/DOCUMENTED reason, never Tier 2/GENERAL or an inferred one, same standing rule as everywhere
  else in this app). A passing explanation gets a plain confirmation; an incomplete one gets a
  gentle, specific nudge ("didn't mention how often you take it") and a nudge toward the chat —
  it never blocks the patient from anything, it only raises a new
  `PATIENT_TEACH_BACK_NEEDS_ATTENTION` audit event onto the clinician's Activity Timeline, the
  same non-blocking pattern as the existing HAS_QUESTION/ASK_CARE_TEAM responses. New
  `PatientTeachBackResponse` table (migration `bdec9040c64a`), new `POST /care-plan/teach-back`
  endpoint. 5 new backend tests; full suite now 377/377. Verified live via Playwright: an
  incomplete answer ("I take a pill sometimes.") is correctly flagged with specific missing facts
  and never blocks the patient.

### 🟠 High

**10. No allergy list shown to the patient either. — Partially addressed.**
- Same underlying gap as Module 2 item 2 — once `PatientAllergy` exists, Module 1's patient view
  should surface it too ("You are allergic to: Penicillin") since patients themselves are a real
  safety check in the loop, not just clinicians.
- **Conditions half done as a side effect of the market-research pass** (see
  `MARKET_ANALYSIS_AND_VISUAL_EXPLAINER_DECISION.md`): documented *conditions* (not yet
  allergies) now reach the patient care page, each shown with a curated three-panel "what it
  is / how it develops / where it affects you" explainer
  (`app/reference/condition_explainers.py`) — a safe, non-AI-generated alternative to an
  AI-generated disease image, chosen after finding real 2026 research showing AI-generated
  anatomical/medical illustrations still have "biologically impossible" accuracy failures with no
  equivalent to this app's deterministic text-validation layer. **Allergies still aren't shown to
  the patient** — same fix, not yet applied to the allergy list.

**11. Only 2 non-English languages.**
- *Standard:* Title VI / CLAS standards require *meaningful access* for any LEP patient a
  facility actually serves, not a fixed shortlist — real hospitals in the US commonly need
  10–15+ languages (Spanish, Mandarin, Vietnamese, Arabic, Tagalog, etc., varies heavily by
  region).
- *Today:* Telugu and Hindi only (reflecting this prototype's specific patient population, not a
  general US hospital's).
- *Fix:* the translation pipeline is already generic (LLM translation + the existing
  `translation_preservation` deterministic fact-check) — adding more `preferred_language` enum
  values is mechanical, not architectural. Worth flagging that **for real (non-synthetic) use,
  LLM-only translation of clinical instructions without a certified-medical-interpreter fallback
  is itself a compliance risk** many hospitals would not accept for anything beyond low-stakes
  content — separate from the count of languages.

**12. No readability/reading-level check on generated patient text. — ✅ BUILT**
- *Standard:* AMA/CDC guidance targets a 5th–6th grade reading level for patient materials.
- *Was:* nothing measured the LLM-generated patient-friendly text's reading level before showing
  it — a well-known LLM failure mode (medically accurate but written above a patient's reading
  level).
- *Built:* a dependency-free Flesch-Kincaid Grade Level scorer (`app/validation/readability.py`,
  pure arithmetic — words/sentence and syllable counting, no LLM involved) computed at generation
  time and stored on `PatientOutput.reading_grade_level` (migration `4a80500a5ae6`). Deliberately
  **informational, not a pass/fail gate** — unlike fact-preservation, a higher score can be
  entirely legitimate (a long medication name raises syllable count without the text actually
  being unclear), so it's surfaced to the clinician's own judgment via a colored badge in
  `PatientOutputPanel.tsx` ("Reading level: grade X, target: grade 6 or below") rather than
  blocking approval. 6 new backend tests (5 unit tests on the scorer + 2 integration assertions);
  full suite now 385/385. Verified live: a real generated instruction scored grade 5.7, correctly
  shown in green (within the AMA/CDC target).

---

## Cross-Cutting (Shared Core)

**13. Single role (`"clinician"`) — no nurse/pharmacist/prescriber distinction.**
- Blocks several of the above (independent double-check for high-alert meds needs a *second*
  identifiable person; a real hospital's audit trail distinguishes who prescribed vs. who
  administered vs. who verified). Not urgent by itself, but is a prerequisite for item 3.

**14. No medication reconciliation across care transitions.**
- *Standard:* Joint Commission's medication reconciliation goal (admission/transfer/discharge —
  compare what the patient was already taking against new orders, resolve discrepancies).
- *Today:* `CareInstruction` models orders only; there's no "home medication list" or
  reconciliation workflow. This is a materially larger feature than anything else in this
  document — flagging for awareness, not proposing to build it now.

---

## Suggested Priority Order (if building next)

Given this is still a single-developer prototype, not a certified hospital system, the
highest safety-value-per-effort items are:

1. ~~**Allergy check** (Module 2 #2 + Module 1 #10)~~ — ✅ built (see item 2 above).
2. ~~**Two-identifier confirmation** (Module 2 #1)~~ — ✅ built (see item 1 above).
3. ~~**Teach-back comprehension check** (Module 1 #9)~~ — ✅ built (see item 9 above).
4. ~~**Readability scoring** (Module 1 #12)~~ — ✅ built (see item 12 above).
5. ~~**High-alert flag + co-sign gate** (Module 2 #3)~~ — ✅ built (see item 3 above) — turned out
   not to need the role system after all (a co-sign just needs a different authenticated person).
6. **Patient-facing allergy display** (Module 1 #10's other half) — the clinician side is built;
   showing the same list on the patient care page is a small, separate follow-up if wanted.

Everything else (FHIR interoperability, drug-drug interactions, medication reconciliation,
real NDC barcodes) is a legitimate gap **relative to a production hospital system**, but is a
large-enough scope increase that it should be a deliberate, separate decision — not something
to fold in silently.

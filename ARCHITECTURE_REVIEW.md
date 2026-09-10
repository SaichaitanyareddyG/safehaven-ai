# SAFEHAVEN AI — Architecture Alignment Review

Read-only review. Nothing implemented, nothing refactored. Verified fresh against the codebase (not assumed from the earlier audit) where anything could plausibly have changed — routing, layout, and `CareInstruction`'s field set specifically.

---

## 1. Current Product Map

```
                         SAFEHAVEN AI
                              |
                     SHARED CORE (real, exists today)
        Patient · Encounter · PatientCondition · CareInstruction (row +
        clinical_status/dates/encounter_id) · AuditEvent/record_event · Auth
                              |
        +---------------------+---------------------+
        |                     |                     |
   MODULE 1                MODULE 2               MODULE 3
  (built, this repo)      (not built)            (not built)
  Extraction/generation    Bedside verification    Fall/mobility safety
  Validation pipeline      engine (nurse scan ->   Sensor ingestion,
  patient_access,          match/mismatch)         alert engine
  patient_chat,
  patient_feedback,
  medication_purpose
```

The important finding: the "shared core" column above isn't aspirational — it already exists and is already used only by Module 1, but nothing in its design is Module-1-specific. `AuditEvent.entity_type`/`entity_id` are generic pointers; `CareInstruction.clinical_status` doesn't reference anything about patient education; `Encounter` has zero dependency on the AI pipeline. Module 1 got there first, not because these things belong to it.

---

## 2. Module 1 Scope Review

**Belongs in Module 1 core:** the explain-to-patient pipeline — extraction, completeness, generation, fact-preservation, approval gate, translation + back-translation, WHY resolution, audio.

**Exists but should be de-emphasized, not removed:**
- Patient chat — real, tested, but its one known gap (no deterministic output check) means it shouldn't anchor the demo story. See dedicated section below.
- Multi-provider LLM support (`anthropic_provider.py`, `ollama_provider.py`) — fully implemented, zero runtime usage. Costs nothing to leave in place (it's just alternate implementations of `LLMProvider`), earns nothing to invest further in right now.

**Should be reclassified as shared infrastructure, not "Module 1 feature":** `Encounter`, `PatientCondition`, `CareInstruction.clinical_status`/`clinical_start_date`/`clinical_end_date`/`encounter_id`, the whole audit trail. These were built *during* Module 1 development and are easy to mentally file under "Module 1 scope creep" — they aren't. They're the exact shared substrate Module 2 needs (see §3, §9). Re-filing them this way changes the overengineering conversation: the encounter/lifecycle work isn't bloat to trim, it's foundation to keep.

**Correctly already excluded, stays in Phase 2:** prescribing templates, full teach-back, QR, FHIR — none of these exist, and none should be started now.

---

## 3. Shared Data Model Review

**Can today's models support Module 1 + Module 2 without duplicating medication data? Yes**, and this is the most important finding in this review.

Module 2's bedside workflow needs exactly one read: "what is the patient's currently active medication order, and what does it say." That's already `GET /patients/{id}/instructions?clinical_status=ACTIVE`, filtered to `instruction_type=MEDICATION`, reading `StructuredExtraction.normalized_facts` (drug, dose, route, frequency, timing). Nothing about that read is Module-1-specific — it was built generically because `clinical_status` was added to `CareInstruction` directly rather than to a separate table (see the special review below for why that was the right call).

**What Module 2 will need that doesn't exist yet — and this is new, not a duplicate:** a place to record the *verification event itself* — nurse scanned drug X at time T, compared against order Y, result MATCH/MISMATCH. That's a new, small, Module-2-owned table (e.g. `MedicationAdministrationCheck`: `care_instruction_id` FK, scanned values, result, nurse id, timestamp). It references the order; it never re-states the order's own fields. This is the correct shape: shared medication data, a separate safety engine bolted on top, no second source of truth for what was prescribed.

---

## 4. Module Boundary Review

| Owns | Responsibility |
|---|---|
| **Shared Core** | `Patient`, `Encounter`, `PatientCondition`, `CareInstruction` (the row itself, its clinical facts, `clinical_status`/dates/`encounter_id`), `AuditEvent`/`record_event()`, clinician auth |
| **Module 1** | `StructuredExtraction`, `PatientOutput`, `PatientOutputTranslation`, the full AI pipeline, `patient_access` (token-gated care page), `patient_chat`, `patient_feedback`, `medication_purpose` reference table |
| **Module 2** (future) | A verification-event table + nurse-facing scan flow + match/mismatch engine. Reads `CareInstruction`. Never writes to Module 1's tables. |
| **Module 3** (future) | Sensor ingestion, fall-event engine, alerting. Reads `Patient` (+ room, if added) and MOBILITY-type `CareInstruction` rows *as context only*. Never reads medication data as a trigger input. |

---

## 5. UI Flexibility Review

Verified fresh, not assumed:

- **`AppLayout.tsx`** is a bare, module-agnostic shell — header + a single `<main>` slot. It contains zero navigation structure specific to Module 1.
- **`PatientDetailPage.tsx`** already uses shadcn `Tabs`/`TabsContent` with three independent panels (Instructions, Activity, Chat), each a `data-testid`-tagged sibling. Adding "Medication Verification" or "Safety Alerts" later is one more `TabsTrigger` + `TabsContent` pair — additive, not a rewrite.
- **`App.tsx`** routing is a flat list of five routes with no nested/module-scoped structure. A nurse-facing Module 2 screen or a Module 3 alert dashboard would be new top-level routes, not a restructuring of existing ones.

**Conclusion: yes** — Module 2 and Module 3 can be added later without rewriting Module 1's UI. This is a verified property of the current code, not a hope about future code.

---

## 6. Overengineering Review

| Item | Verdict | Why |
|---|---|---|
| Multi-provider LLM support | **Freeze** | Real, tested, zero current usage. Costs nothing left as-is; don't extend it further. |
| Patient chat | **Harden or hide, don't expand** | The one AI surface without a deterministic output check — see below. |
| Evaluation harness (`backend/evaluation/`) | **Not in scope for this question** | A development/benchmarking tool, not shipped product surface — doesn't count toward "is the product too big." |
| Encounters + medication lifecycle | **Not overengineering** | Reclassified in §2 as shared infrastructure Module 2 needs directly. |

---

## 7. Safety Review — Re-confirmed

- **No indication inference from diagnoses:** confirmed — `resolve_why()` takes only a `StructuredExtraction`, never queries `PatientCondition`. An earlier version that matched conditions to medications was deliberately removed; the reversal is documented in the function's own docstring.
- **No LLM-generated medication-purpose fallback:** confirmed removed — `medication_purpose_ai` has zero references anywhere in the current codebase.
- **Patient sees only approved instructions:** confirmed — `get_care_plan()` filters to `status == APPROVED` with a `PASSED` output; nothing else is reachable through the token-gated route.
- **Unsafe generated/translated content blocks:** confirmed — `validate_fact_preservation()` / `validate_translation_preservation()` sit between every AI rewrite and the patient, fail closed.
- **Stopped medications don't appear as current:** confirmed — `get_care_plan()` splits on `clinical_status`, tested against a real drug-supersession scenario.
- **Chat is the one remaining weakly enforced AI surface:** confirmed, see next section.

---

## Special Review — Patient Chat

**A, B, or C?** — **B: hide it from the main demo path, keep hardening it in the background, do not expand it.** Reasoning: it's real, tested, and has two genuine deterministic gates (emergency, treatment-change) that work correctly. But its core answer-generation step has no equivalent to `compare_facts()` — nothing re-verifies a reply the way every other AI output in this system is re-verified. That's not a reason to rip it out (the two hard gates are worth keeping exactly as they are), but it's a reason not to feature it as evidence of the safety story you're telling — a judge who pokes at chat first will find the one place the "AI proposes, validation decides" principle isn't fully enforced yet. No new chat functionality should be added until that gap has an answer.

---

## Special Review — Curated Medication Knowledge

- **Where:** `app/reference/medication_purpose.py` — a plain Python `dict[str, str]`, 19 entries.
- **How used:** `resolve_why()`'s Tier 2 (GENERAL) fallback, only when no documented reason exists on the instruction.
- **Is the mechanism correct?** Yes — deterministic lookup, no guessing, disclaimer always attached, never conflated with a documented (Tier 1) reason.
- **Does the content need external clinical review?** Yes, explicitly — it was authored by the assistant that built the feature, not sourced from or checked against a clinical reference. This is a content-accuracy gap, not a mechanism gap.
- **Should the prototype restrict itself to these 19?** Yes. **Do not reintroduce an LLM fallback.** For anything outside the list, the correct behavior is exactly what's already implemented: nothing shown, Tier `NONE`, "ask your clinician" — not a guess. If the current copy for that case reads as anything softer than "general medication information is not available here," that's worth a one-line copy check, not a mechanism change.

---

## Special Review — `CareInstruction` vs. a Separate `MedicationOrder`

**Verdict: `CareInstruction` is sufficient as the shared medication-order source for Module 1 + Module 2. Do not create `MedicationOrder`.**

Current `CareInstruction` already has everything an order representation needs: it's independently row-per-prescription (never grouped by drug name), carries structured medication facts via its linked `StructuredExtraction.normalized_facts`, an explicit `reason`, `clinical_status` (ACTIVE/COMPLETED/STOPPED), `clinical_start_date`/`clinical_end_date`, and an `encounter_id`. A real supersession scenario (old dose stopped, new dose active for a different reason) is already tested and passing.

The only thing that would force a genuine `MedicationOrder` split is if Module 2 needed medication facts as **typed, indexed, directly-queryable columns** rather than a JSONB blob — e.g., if bedside verification needed to run a fast query like "find all active orders where `dose_value > X`" across many patients at once. Nothing in the Module 2 workflow as you've described it needs that: verification is always scoped to one already-identified patient's already-identified active order, read one row at a time. If Module 2's real requirements later turn out to need that kind of cross-patient structured query, that's the concrete, unavoidable reason to reconsider — not before.

---

## 8. Demo Recommendation

Unchanged from the current-state audit, and still the right story: create a medication instruction with a stated reason, watch it auto-analyze and auto-generate live, approve it, open the patient link, show WHY (documented tier), a Telugu translation, and audio. Then show one instruction genuinely blocked (a self-contradicting dose), and one older medication marked Stopped moving out of Current Medications. Skip chat. Under five minutes, and every step is something currently, verifiably working — not an aspiration.

---

## 9. Future Module 2 Handoff

Reuse directly, unchanged: `Patient`, `Encounter`, `CareInstruction` (including `clinical_status`, `clinical_start_date`/`clinical_end_date`, `encounter_id`), `StructuredExtraction.normalized_facts` (the structured drug/dose/route/frequency/timing facts), `record_event()`/`AuditEventType` (add new event types for scan/match/mismatch, don't build a second audit system).

Module 2 should need **zero** new `Patient` fields and **zero** new medication-fact fields to get started. Its own new surface is narrow: a verification-event table and the scan/compare UI.

---

## 10. Future Module 3 Handoff

Reuse: `Patient` (identity, and room if that field is added later), `record_event()`/`AuditEventType` for alerts.

**Should explicitly NOT depend on:** `StructuredExtraction`, `PatientOutput`, `medication_purpose`, `patient_chat`, or any medication-specific table. MOBILITY-type `CareInstruction` rows may be read as *context* (e.g., a documented assistance requirement) but never as a trigger — per the stated rule, a fall event must originate from sensor evidence, medication must never be the trigger on its own.

---

## 11. Final Scope Map

**SHARED CORE**
- `Patient`, `Encounter`, `PatientCondition`
- `CareInstruction` (row, clinical facts via `StructuredExtraction`, `clinical_status`, `clinical_start_date`/`clinical_end_date`, `encounter_id`)
- `AuditEvent` / `record_event()`
- Clinician auth

**MODULE 1 — BUILD/FIX NOW**
- Clinical review of the 19 curated medication-purpose entries (content, not mechanism)
- One explicit decision on chat's demo visibility (recommend: hidden from the demo path, not expanded)
- One test covering the full auto-chain continuously, not just per-stage

**MODULE 1 — HIDE/FREEZE**
- Patient chat (keep the two hard gates exactly as-is; don't add capability)
- Anthropic/Ollama providers (leave in place, no further investment)

**MODULE 2 — NEXT**
- New: verification-event table, nurse scan flow, match/mismatch engine
- Reused, not duplicated: `CareInstruction` + `StructuredExtraction.normalized_facts` as the order source of truth

**MODULE 3 — LATER**
- New: sensor ingestion, fall-event engine, alerting
- Reused: `Patient` identity/room, audit trail
- Explicitly isolated from all medication data

**PHASE 2**
- Prescribing-assist templates, AI dosage suggestions, full teach-back verification, QR/discharge access, FHIR/EHR integration, additional LLM providers, complex notification systems

---

*Read-only review. No files modified, no migrations run, no code written.*

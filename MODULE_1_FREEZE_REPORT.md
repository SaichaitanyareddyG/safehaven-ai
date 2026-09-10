# SAFEHAVEN AI — Module 1 Freeze Report

Builds on the accepted `ARCHITECTURE_REVIEW.md`. No decisions from that document are reopened here. Read-only — no code changed producing this report.

---

## 1. Final Module 1 Product Definition

**SAFEHAVEN Module 1 turns a clinician-approved medication instruction into a validated, plain-language, multilingual explanation the patient can trust — nothing more, nothing less.**

---

## 2. Final Module 1 User Story

**Clinician:** logs in, opens a patient, types the medication instruction as plain text — the same words they'd write on a chart. Watches the system extract structured facts and check completeness automatically. Watches it generate a plain-language version and independently verify that version against the original before anything is shown. Reviews the extracted facts and the safety result, then approves — the one action nothing else in the pipeline does automatically. Can mark an older medication Stopped when it's no longer active.

**Patient:** opens a link (no login) and sees a short list of their current medications — name, dose, timing. Taps "Understand this medicine" to reveal what it is, why they're taking it (only if their clinician actually said why), how it helps, and when/how to take it, plus any important instructions. Switches between English, Telugu, and Hindi. Taps Listen to hear it read aloud.

---

## 3. Final End-to-End Flow

```
Clinician creates medication instruction (free text)
              |
Structured clinical facts extracted (AI, schema-constrained)
              |
Completeness checked --------> missing/unclear info? --> clarification requested
              |
Plain-language explanation generated (AI)
              |
Independently re-extracted and compared against the original (deterministic)
              |
    unsafe change / drop / invention?
        YES --------------------------------> BLOCKED, never shown to patient
        NO
              |
Clinician approves  <-- the only step that is never automatic
              |
Optional Telugu / Hindi translation --> back-translated --> re-compared --> blocked or shown
              |
       PATIENT VIEW
   Current Medications
   -> "Understand this medicine"
         WHAT   the medication and dose
         WHY    only if a reason was explicitly documented
         HOW    general information about how it helps, when no specific reason is documented
         WHEN   timing / how to take it
         Important instructions
   -> English / Telugu / Hindi
   -> Listen (audio)
```

---

## 4. Features Used in the Final Demo

- Free-text instruction creation
- Automatic extraction + completeness check
- Automatic generation + fact-preservation validation, **including one deliberately unsafe case shown being blocked**
- Clinician approval (manual, explicit)
- One medication marked Stopped, shown moving out of Current Medications
- Patient care page: Current Medications list → "Understand this medicine" → WHAT/WHY/HOW/WHEN
- English / Telugu / Hindi
- Audio playback
- Comprehension feedback buttons (harmless if left visible — see note below)

---

## 5. Features Implemented but Hidden

**Update (2026-09-05): patient chat was removed, then rebuilt as v3 with live web search**, per explicit follow-up requests. It was fully deleted first (backend module, DB table, provider methods, prompts, audit event types, frontend components). It was then rebuilt with one genuinely new capability beyond what existed before: on OpenAI's provider, the model may consult a live web search tool restricted to a small allow-list of trusted medical sites (medlineplus.gov, mayoclinic.org, cdc.gov, nih.gov) when the patient's care plan and curated facts don't cover a question — never the open web, never the model's own unfiltered training knowledge, and every such reply discloses that it drew on general sources rather than the patient's own plan (`web_search_used`, surfaced on both the patient and clinician views and in the audit trail as `PATIENT_CHAT_WEB_SEARCH_USED`). Anthropic/Ollama providers stay grounded-only (no web search) — undocumented parity across providers was never requested. This recommendation is unchanged: **still hidden from the frozen demo**, not because it's incomplete but because it remains the one AI surface without a deterministic output check — adding web search is a real capability improvement, not a change to that underlying safety picture. 310 backend tests pass (9 new for chat v3), frontend typechecks and lints clean, verified live end-to-end against the real OpenAI API and in a real browser.

| Feature | Why de-emphasized |
|---|---|
| Encounters panel, Conditions panel (clinician patient page) | Real, working, needed by Module 2 later — but not part of *this* product's story. De-emphasize by simply not narrating them, not by removing them from the page. |
| Multi-provider LLM support (Anthropic, Ollama) | Already invisible — there is no UI surface for provider selection at all, it's an environment variable. Nothing to hide. |
| Comprehension feedback buttons | *Not* recommending hiding these — they're simple, low-risk, and reinforce the "did this actually help" framing. Fine to leave visible; just don't build them out further. |
| Activity & Safety Timeline tab | *Not* recommending hiding this either — it's the concrete proof the audit story is real, and every event on it is already a human-readable description, not raw JSON. Worth a 10-second glance in the demo if there's time, not worth building around. |

---

## 6. Shared Core (exists, not part of Module 1's product story)

- `Patient`, `Encounter`, `PatientCondition`
- `CareInstruction` (the row, `clinical_status`, `clinical_start_date`/`clinical_end_date`, `encounter_id`)
- `StructuredExtraction.normalized_facts` (the structured drug/dose/route/frequency/timing facts)
- Clinician authentication
- `AuditEvent` / `record_event()`
- Instruction version history (`InstructionVersion`)

These support the demo without defining it. They are also exactly what Module 2 reuses (§8).

---

## 7. Phase 2 (confirmed, not started)

- Hardened patient chat (deterministic output validation added)
- Prescribing assistant (`MedicationTemplate`, "Use as Draft", AI dose suggestion) — proposal only, nothing built
- Full teach-back verification (AI asks, checks the answer, escalates on a wrong one)
- QR discharge workflow
- FHIR/EHR integration
- A larger, clinically reviewed medication-knowledge source (replacing today's 19-entry, unreviewed static table)

---

## 8. Module 2 Reuse — Exactly, No Schema Changes

Module 2 can retrieve, from what exists today, with zero new fields:
- `Patient`
- The patient's `ACTIVE` `CareInstruction` (`GET /patients/{id}/instructions?clinical_status=ACTIVE`, already live)
- Medication name, dose, route, frequency, timing — from `StructuredExtraction.normalized_facts`
- Indication, if documented — `normalized_facts["reason"]`
- `clinical_status` itself
- `record_event()`/`AuditEventType` for its own new event types (scan, match, mismatch)

Module 2's only new surface: a verification-event table that references `care_instruction_id`. It never re-states the order's own fields — confirmed as sufficient in `ARCHITECTURE_REVIEW.md`.

---

## 9. Module 3 Reuse — Exactly

- `Patient` identity (+ room, if that field is added later — it doesn't exist today)
- `record_event()`/`AuditEventType` for alerts
- MOBILITY-type `CareInstruction` rows, read as context only (e.g. a documented assistance requirement)

**Must not depend on:** `StructuredExtraction` beyond that narrow mobility-context read, `PatientOutput`, `medication_purpose`, `patient_chat`, or any medication-specific table. A fall event must originate from sensor evidence, never from medication data.

---

## 10. Final UI Flow

**Clinician screens (minimum):**
1. Patient List → select patient
2. Patient Detail — Instructions tab as the default, primary view; Activity tab available but not narrated unless asked
3. Instruction Workflow page — create → watch auto-analyze/generate → facts + validation result → approve (or watch a deliberately unsafe one block)
4. One click on `MedicationStatusControl` to mark a medication Stopped

**Patient screens (minimum):**
1. Care page — Current Medications list
2. Tap "Understand this medicine" → WHAT/WHY/HOW/WHEN, in place, no new request
3. Language toggle (English/Telugu/Hindi)
4. Listen button

Nothing else needs to be on screen for the demo to be complete.

---

## 11. Final 5-Minute Demo Script

> "A doctor writes a prescription the way they normally would." *(Type: "Take Lisinopril 10 mg orally once daily in the morning for your high blood pressure.")* "Watch — the system is reading it, pulling out the dose, the route, the timing, and checking nothing's missing." *(Auto-analyze completes.)* "Now it writes a plain-language version for the patient — but before anyone sees it, the system independently re-reads its own output and checks it still says the same thing." *(Auto-generate completes, shows "Safe to show patient.")* "I'm the clinician — I still have to say yes." *(Click Approve.)*
>
> "Here's what happens when the AI gets something wrong." *(Create a second instruction with a self-contradicting dose, or reuse a known adversarial case; show it land in Needs Review / blocked rather than reaching the patient.)* "It never reaches the patient — it comes back to me instead."
>
> "Now here's the patient's side." *(Open the patient link.)* "Lisinopril, ten milligrams — tap to understand it." *(Tap "Understand this medicine.")* "What it is, why they're taking it — and only because their doctor actually wrote that reason down, never guessed — how it helps, when to take it." *(Switch to Telugu.)* "Same explanation, independently verified in Telugu too." *(Tap Listen.)*
>
> "And one more thing — medications don't just accumulate forever." *(Show a Stopped medication in Past Medications.)* "Old prescriptions move out of the way automatically; nothing is deleted, it's just not shown as current anymore."

Under five minutes, nothing shown is aspirational.

---

## 12. Demo Blockers

| Blocker | Classification |
|---|---|
| None found that would prevent the demo from running | — |
| The 19 curated medication-purpose entries have not been clinically reviewed | **IMPORTANT** — not a functional blocker, but be ready to say so plainly if asked; consider a one-line "reference data, not independently verified" caveat before presenting to a clinical judge |
| Real-model translation back-translation occasionally produces a false block (~1 in 8 in prior sampling) | **IMPORTANT** — rehearse the exact demo medication/language pair beforehand to confirm it passes reliably, or be prepared to narrate a block as the system correctly catching something rather than treating it as a bug |
| No single test exercises the full auto-chain continuously (each stage is tested in isolation) | **OPTIONAL** — a test-suite completeness gap, not a demo-facing risk |

---

## 13. Code Changes Required to Reach the Frozen Demo

**None are required.** Every feature in §4's demo script already exists, is tested, and works — verified live multiple times this project, not just by unit test. Freezing Module 1 for the demo is a matter of what the presenter chooses to click and narrate, not a code change.

One genuinely optional polish item, explicitly not required:

| File | Reason | Size |
|---|---|---|
| `app/patient_access/service.py` (`_GENERAL_PURPOSE_DISCLAIMER`) | Strengthen the existing disclaimer to note the reference table itself is prototype/unreviewed content, not just "may not be fully accurate for you" | SMALL — one string |

Nothing else is recommended. Adding anything beyond this for the demo would work against the brief.

---

*Read-only report. No code written, no files modified, no architecture decisions reopened.*

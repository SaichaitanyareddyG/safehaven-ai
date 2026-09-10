# SafeHaven AI — Module 1 Current-State Audit

Evidence-based inspection only. No code was written or modified producing this report. Every claim below is backed by a file path, function/class name, endpoint, model, or test file — verified directly against the codebase at `/Users/sai/Desktop/safehaven-ai`.

---

## 1. Executive Summary

**What Module 1 does today, start to finish:** a clinician types a free-text instruction; the system extracts structured clinical facts from it with an LLM; a deterministic validator checks completeness; a second LLM call rewrites it in plain language; a third, independent step re-extracts facts from that rewrite and deterministically diffs them against the original — any changed, missing, or invented fact blocks the output before a clinician ever sees an approve button. Only after explicit clinician approval does a patient — reached via a token-gated link, no login — see the plain-language text, an optional Telugu/Hindi translation (independently back-translated and re-validated the same way), a "why" explanation gated to three tiers, text-to-speech audio, a grounded chat, and a comprehension check.

**Strongest current capability:** the fact-preservation pipeline (`app/validation/fact_preservation.py`) and its translation counterpart (`app/validation/translation_preservation.py`) — a genuinely deterministic, tested, twice-independently-verified (extraction re-run + comparison) gate between anything an LLM writes and anything a patient sees.

**Top 3 safety gaps:**
1. **Patient chat is the one ungated AI surface.** Every other AI output requires clinician approval or passes deterministic validation before a patient sees it. Chat answers reach the patient live, gated only by a system prompt telling the model to stay grounded — a prompt instruction, not a checkable rule.
2. **The medication-purpose curated table (19 entries) is hand-written by the assistant that built it, not clinically reviewed.** Presented to patients as "general medication information" with a disclaimer, but nothing has verified its clinical accuracy against an authoritative source.
3. **No real EHR/FHIR integration** means every "documented indication," diagnosis, and encounter is only as real as what a clinician manually typed into this app in this test environment.

**Top 3 scope-creep candidates:**
1. Encounters + medication clinical lifecycle (`app/encounters/`, `ClinicalStatus`) — real, tested, working, but adds a second organizing axis (visit-based) on top of the original patient-based one, for a 5-minute demo that may not need it.
2. Patient chat + comprehension feedback — two separate new surfaces added in the same period the core safety pipeline was still being hardened.
3. Multi-provider LLM abstraction (`app/ai/anthropic_provider.py`, `app/ai/ollama_provider.py`) — fully implemented and tested but unused by the running app.

**Is Module 1 coherent as one product?** The core loop (instruction → validated simplification → approval → patient view) is coherent and strong. Three features were added alongside it in the same window — encounters/lifecycle, chat, comprehension feedback — each individually well-built and tested, but together they now describe three different products (a records system, a patient-safety pipeline, a conversational assistant) sharing one codebase.

**Scores (current implementation):**

| Usefulness | Safety | Technical completeness | Demo readiness | Scope clarity |
|---|---|---|---|---|
| 7/10 | 8/10 | 8/10 | 6/10 | 5/10 |

---

## 2. Actual End-to-End Workflow

Verified against `app/instructions/service.py`, `app/patient_access/service.py`.

1. **Clinician** types free text into one `Textarea` (`CreateInstructionDialog.tsx`) → `POST /patients/{id}/instructions`. Body is exactly `{text: string}` — `create_instruction()` stores it as `CareInstruction` (status `DRAFT`) + `InstructionVersion` (`source=ORIGINAL`). **No LLM call yet.**
2. **System (auto)** — `InstructionWorkflowPage.tsx` auto-fires `analyze()` on mount for a `DRAFT` instruction. **AI call #1**: `run_extraction()` → structured facts. *Deterministic gate*: `evaluate_completeness()` (`app/validation/completeness.py`) decides PASSED / NEEDS_CLARIFICATION / FAILED per `app/validation/rules.py`'s field tiers.
3. **Clinician** — if NEEDS_CLARIFICATION, submits a clarification (`POST /instructions/{id}/clarify`) — creates a new *version* of the same instruction, never a new row. Otherwise the page auto-fires `generate()`.
4. **System (auto)** — **AI call #2**: `run_generation()` → plain-language text. **AI call #3**: the generated text is independently re-extracted. *Deterministic gate*: `validate_fact_preservation()` diffs original vs. re-extracted facts field by field. Any CHANGED/MISSING/ADDED → `NEEDS_REVIEW`, nothing shown to a patient. Else → `READY_FOR_APPROVAL`.
5. **Clinician** — the only human gate never auto-fired. `POST /instructions/{id}/approve` re-checks the latest output is PASSED (defense in depth) before setting `APPROVED`. If `MEDICATION`-type, also sets `clinical_status=ACTIVE` + `clinical_start_date`.
6. **System (auto)** — if the patient's `preferred_language` isn't English: **AI call #4** (translate) + **AI call #5** (back-translate) + **AI call #6** (re-extract the back-translation). *Deterministic gate*: `validate_translation_preservation()`. Failure blocks only that language.
7. **Patient** opens a token-gated link (`GET /care-plan?token=`, no login) → sees only `APPROVED` instructions with a `PASSED` output. Can view English/Telugu/Hindi, listen (TTS), open chat, submit comprehension feedback. Nothing here re-triggers generation.

**Where patient-facing content can appear without a human approving that specific content:** only patient chat replies (§11) and the fixed emergency/redirect messages. Everything else requires `APPROVED` status, set only by a clinician.

---

## 3. Backend Architecture

| Module | Purpose | Key symbols | Active | Safety-critical |
|---|---|---|---|---|
| `app/patients/` | Patient CRUD, admission status | `Patient`, `AdmissionStatus` | Yes | — |
| `app/conditions/` | Free-text documented conditions/diagnoses | `PatientCondition` | Yes | Yes — never used for inference |
| `app/encounters/` | Visit/encounter records | `Encounter`, `EncounterStatus` | Yes | — |
| `app/instructions/` | Core authoring/workflow state machine | `CareInstruction`, `InstructionVersion`, `ClinicalStatus`, `transition()` | Yes | Yes |
| `app/ai/` | Extraction/generation/translation/chat prompts + 4 provider implementations | `extraction_service.py`, `generation_service.py`, `translation_service.py`, `openai_provider.py`, `anthropic_provider.py`, `ollama_provider.py`, `mock_provider.py` | Partial (see §6) | Yes |
| `app/validation/` | All deterministic checking | `compare_facts()`, `scan_for_preserved_warnings()`, `evaluate_completeness()` | Yes | Yes — the core safety module |
| `app/reference/` | Static curated medication-purpose lookup | `MEDICATION_PURPOSE` dict, `lookup_medication_purpose()` | Yes | Yes — unreviewed content |
| `app/patient_access/` | Token-gated patient view, "why" resolution, TTS routing | `get_care_plan()`, `resolve_why()`, `validate_care_access_token()` | Yes | Yes |
| `app/patient_chat/` | Grounded chat + hard deterministic gates | `send_chat_message()`, `_EMERGENCY_PATTERNS`, `_TREATMENT_CHANGE_PATTERNS` | Yes | Yes — weakest gate in the system |
| `app/patient_feedback/` | "Did this explanation help?" buttons | `PatientComprehensionFeedback`, `ComprehensionResponse` | Yes | — |
| `app/tts/` | edge-tts speech synthesis | `synthesize_speech()` | Yes | — |
| `app/audit/` | Immutable audit trail | `record_event()`, `AuditEventType` (24 values) | Yes | Yes |
| `app/auth/` | Clinician login (JWT, dev provider) | `AuthProvider` protocol, `DevAuthProvider` | Yes | — |
| `app/orchestration/` | Cross-module transactions | `patient_ops.py` | Yes | — |

---

## 4. Database / Data Model

| Table | Important fields | Relationships |
|---|---|---|
| `patients` | `patient_code`, `preferred_language`, `admission_status` | 1→many `care_instructions`, `encounters`, `patient_conditions` |
| `encounters` | `admission_date`, `discharge_date`, `status`, `reason_for_visit` | patient FK; `care_instructions.encounter_id` and `patient_conditions.encounter_id` both nullable FKs |
| `patient_conditions` | `condition_name` (free text), `encounter_id` (nullable) | never joined into WHY resolution |
| `care_instructions` | `status` (workflow), `clinical_status` (ACTIVE/COMPLETED/STOPPED, nullable), `clinical_start_date`, `clinical_end_date`, `encounter_id` | 1→many `instruction_versions` |
| `instruction_versions` | `raw_text`, `version_number`, `source` (ORIGINAL/CLARIFICATION) | 1→1 `structured_extractions`; 1→many `patient_outputs` |
| `structured_extractions` | `normalized_facts` (JSONB), `completeness_status` | unique per version |
| `patient_outputs` | `patient_text_en`, `validation_status`, `validation_diff` (JSONB), `attempt_number` | 1→many `patient_output_translations` |
| `patient_chat_messages` | `role`, `text`, `emergency_flagged`, `redirect_flagged` | patient FK |
| `patient_comprehension_feedback` | `response` (UNDERSTOOD/HAS_QUESTION/ASK_CARE_TEAM) | patient + care_instruction FK |
| `audit_events` | `event_type` (plain string, 24 values), `event_metadata` (JSONB) | append-only, no update/delete route |

**Direct answers:**
1. Encounter/Visit model exists? **Yes** — `app/encounters/models.py`.
2. Multiple visits per patient? **Yes**, one-to-many.
3. Conditions tied to encounters? **Optionally** — `encounter_id` nullable by design.
4. Each prescription independent? **Yes** — every `CareInstruction` is its own row; no medication-name grouping anywhere.
5. ACTIVE/COMPLETED/STOPPED status? **Yes** — `ClinicalStatus` enum, medication-only by construction.
6. Same medication as two separate historical prescriptions? **Yes**, proven by `test_superseded_medication_order_never_leaks_into_the_new_active_one`.
7. Current vs. old medications distinguishable? **Yes** — `get_care_plan()` splits into `instructions` vs. `past_medications`.
8. Where is indication/reason stored? `StructuredExtraction.normalized_facts["reason"]` — per-instruction, never a separate table.
9. Tied to prescription or diagnosis? **Prescription only.** Confirmed absent: any join from `patient_conditions` into WHY logic.
10. Historical data preserved? **Yes** — no delete path exists for `CareInstruction` anywhere.

---

## 5. "Why Am I Taking This?" Logic

Core function: `resolve_why()`, `app/patient_access/service.py`. Pure, deterministic, takes only a `StructuredExtraction`.

- **A. Indication documented** → Tier `DOCUMENTED` — the clinician's own `reason`/`purpose` field, shown verbatim, no disclaimer.
- **B. Not documented** → Tier `GENERAL` if the medication is in the curated table, else Tier `NONE` — nothing shown.
- **C. Ever infers from diagnosis/name/LLM?** **No.** An earlier version matched a patient's documented condition against the medication — removed as an explicit safety correction (named directly in `resolve_why()`'s own docstring).
- **D. Curated table** — `app/reference/medication_purpose.py`, a plain `dict[str, str]`, **19 entries**: metoprolol, lisinopril, levothyroxine, amoxicillin, warfarin, ibuprofen, naproxen, metformin, amlodipine, atorvastatin, losartan, hydrochlorothiazide, omeprazole, sertraline, albuterol, gabapentin, prednisone, aspirin, furosemide.
- **E. Outside this list:** nothing shown — Tier `NONE`. An LLM fallback for this was built, tested, verified live, **and then deliberately removed** as a second safety correction — confirmed by grepping for `medication_purpose_ai`: zero hits.
- **F. Visual separation:** yes — `WhyExplanationBlock` in `PatientCarePage.tsx`, distinct panel with `data-tier`, labelled differently per tier, disclaimer only on GENERAL.

---

## 6. AI / LLM Usage

| Call | Schema-constrained | Validated after | Reaches patient directly? | Own knowledge allowed? |
|---|---|---|---|---|
| Extraction | Yes — `additionalProperties:false` | Yes, completeness | No | No |
| Generation | No (free text) | Yes, fact-preservation | Only after approval | No |
| Translation + back-translation | No (free text) | Yes, translation-preservation | Only after approval | No |
| Medication purpose | — | — | Yes, Tier GENERAL | N/A — static dict, not an LLM call |
| Patient chat | No (free text) | **No deterministic check** | **Yes, live, ungated** | Prompt says no — not structurally enforced |

The one honest answer to "where can the model use its own medical knowledge instead of retrieved/approved sources": **patient chat.** `PATIENT_CHAT_SYSTEM_PROMPT` instructs grounding, but nothing re-checks the reply the way `compare_facts()` re-checks generation.

---

## 7. Safety Validation

`Original instruction → normalize_facts() → compare_facts() (deterministic diff) → PASS / CHANGED / MISSING / ADDED → patient output`. Fields checked for MEDICATION: `medication_name, dose_value, dose_unit, route, frequency, timing, duration, with_food`. `warnings` checked separately by direct scan.

| Source phrase | Rewording | Result | Mechanism |
|---|---|---|---|
| "once daily" | "once every day" | PASS | `_FREQUENCY_MAP` normalization |
| "in the morning" | "once every morning" (merged) | PASS | `_split_once_daily_from_timing()` |
| "maximum 4,000 mg in 24 hours" | "Do not take more than 4,000 mg in 24 hours" | PASS | `_warning_preserved()` — number-anchored |
| "oral" | "sublingual" | **BLOCK** | genuinely different route, correctly caught |

**Fails closed:** a failed re-extraction, a type mismatch, or any unresolved difference all resolve to blocking. `NEEDS_REVIEW` happens pre-generation; blocking happens post-generation — both keep the instruction from the patient.

**Known bugs found & fixed:** timing-field wording drift; warnings verbatim-match false positive (fixed → number-anchored); frequency/timing cross-field reshuffling during back-translation (fixed). **Known unresolved:** back-translation occasionally still produces a false block (~1 in 8 in a real-model sample) — accepted as the safe failure mode, not fixed.

---

## 8. Translation

| Language | Generated | Back-translated | Facts re-extracted | Can block | Approval needed after? |
|---|---|---|---|---|---|
| English | n/a — canonical | n/a | n/a | n/a | yes, same as always |
| Telugu | Yes | Yes | Yes | Yes | No — auto-triggers post-approval if preferred language |
| Hindi | Yes | Yes | Yes | Yes | Same as Telugu |

If a translation fails: that row is `FAILED`, never shown; `PatientCarePage.tsx` falls back to English with a visible note. One language failing never blocks another that already passed.

---

## 9. Clinician Workflow

| Capability | Status | Evidence |
|---|---|---|
| Create instruction | DONE | `CreateInstructionDialog.tsx` |
| Edit / clarify | DONE | `ClarificationForm.tsx` |
| Approve / Reject | DONE | `InstructionActions.tsx` |
| See extracted facts | DONE | `FactsPanel.tsx` |
| See validation result | DONE | `PatientOutputPanel.tsx` |
| See medication purpose | Indirect | only via patient-facing preview |
| Mark active/stopped/completed | DONE | `MedicationStatusControl` |
| Select/create encounter | DONE | `EncountersPanel.tsx` — creation only, no instruction-linking UI |
| Choose indication explicitly | Implicit only | whatever's typed in free text, no separate field |
| Use prescribing template | **NOT BUILT** | proposed only |
| AI-generated dose suggestion | **NOT BUILT** | explicitly rejected in the proposal |

---

## 10. Patient Experience

| Capability | Status |
|---|---|
| See current medications, name/dose/timing | DONE |
| "Why am I taking this?" | DONE |
| "How does this help?" | Merged into WHY text, not separate |
| Change language | DONE |
| Listen (audio) | DONE — edge-tts |
| Chat / ask about medication | DONE (grounding caveat — see §11) |
| See past medications | DONE |
| "Understand this medicine" click | DONE — pure client-side expand |
| Full teach-back (AI verifies understanding) | **NOT BUILT** |
| "I still have a question" / "Ask my care team" | DONE — surfaces on clinician Activity timeline |
| Scan QR code | **NOT BUILT** |
| Authenticate from discharge receipt | **NOT BUILT** — plain URL token, copied manually |

The comprehension-feedback buttons and the originally-envisioned "teach-back loop" (AI verifies understanding, escalates on a wrong answer) are **not the same feature** — only the simpler one exists.

---

## 11. Patient Chat

**Is it strictly grounded?** By instruction, yes. **By enforcement, no** — no deterministic check on the reply content, unlike every other AI output in this system.

**Deterministic gates that do exist**, both running before the LLM, on the incoming message:
- `_EMERGENCY_PATTERNS` → fixed "call emergency services" message, LLM skipped.
- `_TREATMENT_CHANGE_PATTERNS` → fixed "contact your care team" message, LLM skipped. Also re-scanned on the output side as a backstop.

| Patient asks | Actual routing today |
|---|---|
| "Why am I taking Lisinopril?" | Neither gate matches → reaches the LLM with care-plan context → answered from documented reason or curated general text. |
| "What happens if I take two tablets?" | Matches treatment-change ("extra") → fixed redirect, LLM never called. |
| "Should I stop this because I feel dizzy?" | Matches treatment-change ("stop"). Dizziness itself isn't on the emergency list — a genuinely urgent symptom bundled with a stop-question routes to the redirect message, not the emergency one. |
| "Can I take another blood pressure medicine?" | Matches neither gate → reaches the LLM, unverified. |
| "What's the best medicine for hypertension?" | Same — general medical-advice question, no gate, answer depends entirely on the prompt being followed. |

---

## 12. Encounters / Medication History — Status

**IMPLEMENTED AND WORKING** — not discussed, built, migrated, tested.

- **Models:** `Encounter`, `ClinicalStatus` + 4 new columns on `CareInstruction`, `encounter_id` on `PatientCondition`.
- **Migration:** `9850830ad17a_add_encounters_medication_clinical_.py` — applied, with a scoped data backfill verified against the live dev database.
- **APIs:** `POST/GET /patients/{id}/encounters`, `PATCH /instructions/{id}/clinical-status`, `GET /patients/{id}/instructions?clinical_status=`.
- **UI:** `EncountersPanel.tsx`, `MedicationStatusControl`, current/past split on `PatientCarePage.tsx`.
- **Tests:** `test_encounters.py` (6), `test_medication_clinical_status.py` (11) — including the exact Metoprolol 25mg-stopped/50mg-active supersession case.

`clinical_start_date`/`clinical_end_date`: both implemented, nullable, populated only at transition time — never backfilled from `created_at`.

---

## 13. Clinician Prescribing Assistant — Status

**Planned only — not implemented.** A design proposal (architecture, safety boundaries, test plan) was produced and awaits approval. No model, migration, endpoint, UI component, or test exists. Grepped for "template"/"formulary"/"protocol": zero hits outside Python's own `typing.Protocol`.

Specifically absent: `MedicationTemplate` model, source/version field, suggested-dose UI, "Use as Draft" control, template-specific audit event.

---

## 14. Frontend Inventory

| File | Purpose | Calls |
|---|---|---|
| `pages/PatientListPage.tsx` | Clinician patient roster | `GET /patients` |
| `pages/PatientDetailPage.tsx` | Single patient — conditions, encounters, instructions, activity, chat tabs | children's own calls |
| `pages/InstructionWorkflowPage.tsx` | Authoring pipeline, auto-chains analyze/generate | analyze, generate, approve, translations |
| `pages/PatientCarePage.tsx` | Token-gated patient view — no clinician auth | care-plan, chat, feedback, audio |
| `features/instructions/FactsPanel.tsx` | Extracted-fact display | reads instruction detail |
| `features/patients/EncountersPanel.tsx` | List/create encounters | encounters endpoints |
| `features/patients/PatientConditionsPanel.tsx` | List/add/remove conditions | conditions endpoints |
| `features/patient-chat/PatientChatPanel.tsx` | Patient-side chat | `/care-plan/chat` |
| `features/patient-chat/PatientChatTranscript.tsx` | Clinician-side read-only transcript | `/chat-messages` |
| `features/patient-feedback/ComprehensionFeedback.tsx` | Three-button feedback | `/care-plan/feedback` |

No duplicated or dead components found.

---

## 15. API Inventory — 28 Endpoints

| Method | Path | Auth | Used by frontend |
|---|---|---|---|
| POST | `/auth/register` | public | Yes |
| POST | `/auth/login` | public | Yes |
| GET | `/auth/me` | clinician | Yes |
| POST/GET | `/patients` | clinician | Yes |
| GET/PATCH | `/patients/{id}` | clinician | Yes |
| POST/GET | `/patients/{id}/instructions` | clinician | Yes |
| GET | `/instructions/{id}` | clinician | Yes |
| POST | `/instructions/{id}/analyze` | clinician | Yes |
| POST | `/instructions/{id}/clarify` | clinician | Yes |
| POST | `/instructions/{id}/generate` | clinician | Yes |
| POST | `/instructions/{id}/approve` | clinician | Yes |
| PATCH | `/instructions/{id}/clinical-status` | clinician | Yes |
| POST | `/instructions/{id}/translations` | clinician | Yes |
| POST | `/instructions/{id}/reject` | clinician | Yes |
| POST/GET | `/patients/{id}/care-access-tokens` | clinician | Yes |
| POST | `/care-access-tokens/{id}/revoke` | clinician | Yes |
| GET | `/care-plan` | token only | Yes |
| POST | `/care-plan/audio` | token only | Yes |
| GET/POST | `/care-plan/chat` | token only | Yes |
| POST | `/care-plan/feedback` | token only | Yes |
| GET | `/patients/{id}/chat-messages` | clinician | Yes |
| POST/GET/DELETE | `/patients/{id}/conditions` | clinician | Yes |
| POST/GET | `/patients/{id}/encounters` | clinician | Yes |
| GET | `/patients/{id}/audit` | clinician | Yes |
| GET | `/health` | public | No — infra only |

No unused or overlapping endpoints found. The four `/care-plan*` routes are "token only" by design (that's the point of the patient link) — worth naming explicitly since it's the one place authorization means "possession of a URL" rather than a login.

---

## 16. Test Coverage — 322 Tests, All Passing

| Category | File | Count |
|---|---|---|
| Fact preservation (core safety) | `test_fact_preservation.py` | 36 |
| Extraction / analyze | `test_analyze.py` | 26 |
| Audit trail | `test_audit.py` | 25 |
| Generation / validation | `test_generate.py` | 22 |
| Normalization | `test_normalization.py` | 19 |
| Patient access / care-plan | `test_patient_access.py` | 16 |
| Translation | `test_translate.py` | 14 |
| Instruction workflow | `test_instructions.py` | 13 |
| Translation-preservation | `test_translation_preservation.py` | 12 |
| Patients CRUD | `test_patients.py` | 12 |
| Chat safety patterns | `test_patient_chat_patterns.py` | 11 |
| Medication clinical status | `test_medication_clinical_status.py` | 11 |
| Chat integration | `test_patient_chat.py` | 10 |
| WHY logic | `test_resolve_why.py` | 9 |
| Comprehension feedback | `test_patient_feedback.py` | 6 |
| Encounters | `test_encounters.py` | 6 |
| Medication purpose (curated) | `test_medication_purpose.py` | 4 |
| Completeness rules | `test_completeness.py` | 7 |
| All others (auth, prompts, schemas, TTS, provider factory, state machine) | 7 files | 36 |

**Critical workflows with no dedicated test:** the prescribing-template idea (correctly untested — not built). A genuine gap: no single test exercises the *full* auto-chain (create → analyze → generate → approve → translate) continuously across multiple instruction types; each stage is well tested in isolation only.

---

## 17. Audit Trail Coverage

| Action | Audited? |
|---|---|
| Clinician creates instruction | Yes — `INSTRUCTION_CREATED` |
| AI generates explanation | Yes — `PATIENT_OUTPUT_GENERATED` |
| Validation passes/fails | Yes — `FACT_VALIDATION_PASSED`/`_FAILED`, same for translation |
| Clinician approves/rejects | Yes |
| Translation created | Yes |
| Chat | Partial — only emergency/redirect-flagged turns audited; ordinary exchanges stored but not written to `audit_events` |
| Patient access (link viewed) | Yes — `CARE_PLAN_VIEWED`, deduplicated |
| Medication status change | Yes — `MEDICATION_CLINICAL_STATUS_CHANGED` |
| Prescription template usage | N/A — feature not built |

The audit table is append-only by construction — no update/delete route exists.

---

## 18. What Is Actually Safe vs. Not

| Feature | Implementation | Safety status | Why |
|---|---|---|---|
| Patient-specific WHY | Pure function, no diagnosis inference | GOOD | Explicit-only, deterministic, tested against adversarial cases |
| Translation | Back-translate + re-extract + diff | GOOD | Fails closed |
| Medication-purpose fallback (curated) | Static dict, unreviewed content | NEEDS HARDENING | Mechanism is safe; 19 entries' accuracy unreviewed |
| Patient chat | Prompt-grounded, no output validation | NEEDS HARDENING | Only AI surface with no deterministic output check |
| Dose changes | Hard-blocked before the LLM | GOOD | Deterministic pattern match |
| Clinician approval | Single non-auto-chained action | GOOD | Only path to patient visibility |
| Missing information | Tiered, never invented | GOOD | Tested |
| Old medications | Separated by `clinical_status`, preserved | GOOD | Verified against real supersession scenario |
| Multiple encounters | Modeled, nullable linkage | GOOD | Never used for inference |
| Prescribing template | — | NOT IMPLEMENTED | Proposal only |

---

## 19. Implemented vs. Planned Matrix

| Feature | Status | Evidence | Recommendation |
|---|---|---|---|
| Instruction creation | DONE | `create_instruction()` | Keep |
| Extraction | DONE | `run_extraction()` | Keep |
| Simplification | DONE | `run_generation()` | Keep |
| Canonical fact validation | DONE | `compare_facts()`, 36 tests | Keep — this is the product |
| Translation (Telugu/Hindi) | DONE | 26 tests | Keep |
| Clinician approval | DONE | `approve()` | Keep |
| WHY — documented | DONE | `resolve_why()` | Keep |
| General medication purpose | DONE | 19-entry dict | Fix — clinical review |
| LLM medication-purpose fallback | REMOVED | built, then deleted | Don't rebuild without retrieval grounding |
| Patient chat | DONE | `patient_chat/` | Fix — output-side check, or Phase 2 |
| Grounded chat | PARTIAL | prompt-enforced only | Fix |
| Emergency blocking | DONE | regex gate, tested | Keep |
| Treatment-change blocking | DONE | regex gate, tested | Keep |
| Conditions | DONE | `PatientCondition` | Keep |
| Encounters | DONE | `Encounter` + tests | Phase 2 for demo specifically |
| Medication lifecycle | DONE | `ClinicalStatus` | Same as above |
| Current medications | DONE | `get_care_plan()` split | Keep if encounters kept |
| Past medications | DONE | same | Keep if encounters kept |
| QR access | NOT BUILT | zero hits | Later |
| Audio | DONE | edge-tts | Keep |
| Teach-back (real verification) | NOT BUILT | only 3-button feedback exists | Later |
| Clinician escalation | PARTIAL | audit event only, no push | Later |
| Prescribing templates | NOT BUILT | proposal only | Later |
| FHIR/EHR | NOT BUILT | explicitly out of scope | Later |
| Audit logs | DONE | 24 event types | Keep |

---

## 20. Scope Recommendation

**Recommended product definition:** *SafeHaven Module 1 turns a clinician's own words into a validated, plain-language, translated, audible explanation a patient can trust — and refuses to guess anything the clinician didn't actually say.*

**Must keep for demo:**
- Full instruction → extract → simplify → validate → approve loop
- Live-blocking a genuinely broken translation or generation, on screen
- Three-tier WHY, shown with visible tier labeling
- Telugu/Hindi + audio
- Audit timeline

**Should fix before demo:**
- Get the 19 curated medication-purpose entries clinically reviewed, or caveat them on-screen
- Decide chat's fate explicitly rather than leave it half-hardened
- Add the one missing full end-to-end auto-chain test

**Move to Phase 2:**
- Encounters + medication lifecycle (real, but a second product axis)
- Prescribing-template assist (not built — don't start before the demo)
- Full teach-back verification loop
- QR / discharge-receipt access, FHIR integration

---

## 21. Demo Readiness

**Today, as-is (under 5 minutes):** create a Lisinopril instruction with a stated reason → watch it auto-analyze and auto-generate live → approve it → open the patient link → show WHY (documented tier), the Telugu translation, and audio. Then create a second instruction with a self-contradicting dose to show a real block, and a third, older medication marked "Stopped" to show it move out of Current Medications.

**Ideal demo after the smallest fixes:** same flow, plus opening chat to ask a grounded question and showing the fixed decline on an out-of-scope question — but only after the chat's grounding gap is either fixed or the chat step is deliberately left out of the demo path.

---

## 22. Smallest Fixes Before Demo

1. One clinical reviewer pass on `app/reference/medication_purpose.py`'s 19 entries — or add an explicit "unreviewed reference data" caveat to the disclaimer shown today.
2. Decide, explicitly, whether chat appears in the demo given §11's gap — if yes, add at minimum a deterministic keyword scan of the chat's own output for obvious dosing language, mirroring the existing input-side gate.
3. Nothing else blocks the demo — the core loop is solid and already tested at 322 passing tests.

---

*Prepared as a read-only inspection. No files were modified, no migrations run, no code written in producing this report.*

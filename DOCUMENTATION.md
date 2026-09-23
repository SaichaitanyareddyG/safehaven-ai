# SafeHaven AI — Complete Documentation

A hospital patient-safety platform in two parts: helping patients understand
their medications, and verifying every dose before it is given.

This document covers every feature, module by module, with the flows that
connect them. It describes what is actually built and working, and says
plainly what is not.

---

## Contents

1. [The core idea](#1-the-core-idea)
2. [Architecture](#2-architecture)
3. [Shared Core](#3-shared-core)
4. [Module 1 — Medication Understanding](#4-module-1--medication-understanding)
5. [Module 2 — Administration Verification](#5-module-2--administration-verification)
6. [End-to-end flows](#6-end-to-end-flows)
7. [Safety design rules](#7-safety-design-rules)
8. [Data model](#8-data-model)
9. [API reference](#9-api-reference)
10. [Security and privacy](#10-security-and-privacy)
11. [Testing](#11-testing)
12. [Running it](#12-running-it)
13. [What is deliberately not built](#13-what-is-deliberately-not-built)

---

## 1. The core idea

One sentence governs the whole system:

> **AI proposes. Deterministic code decides. A clinician approves.**

An LLM is used where language is genuinely hard — reading a clinician's free
text, rewriting it for a patient, translating it, transcribing dictation,
reading a medication label. It is never the thing that decides whether
something is safe. Every safety decision is plain, testable, deterministic
code comparing structured values.

Three consequences run through everything below:

- **Nothing is auto-approved on uncertainty.** Ambiguity produces a review
  state, never a pass.
- **Nothing is inferred about a patient.** If a clinician did not state it, the
  system does not claim it.
- **Every AI output is re-checked by code before a human sees it** — except
  dictation, which structurally cannot be (see §4.3), and where the design
  makes the clinician's own review unavoidable instead.

---

## 2. Architecture

```
  Clinician (browser)                         Patient (phone, no login)
          │                                             │
          │  JWT session                                │  tokenised care link
          ▼                                             ▼
  ┌───────────────────────────── FastAPI backend ─────────────────────────────┐
  │                                                                           │
  │   Module 1                Shared Core                Module 2             │
  │   instructions/           patients/                  medication_          │
  │   patient_access/         encounters/                  verification/      │
  │   patient_chat/           conditions/                reference/           │
  │   patient_feedback/       allergies/                                      │
  │                           auth/  audit/                                   │
  │                                                                           │
  │   validation/   ← deterministic safety layer, no LLM                      │
  │   ai/           ← provider abstraction, the ONLY place an SDK is imported  │
  └───────────────────────────────────────────────────────────────────────────┘
                                     │
                              PostgreSQL + Alembic
```

**Stack:** FastAPI, SQLAlchemy, PostgreSQL, Alembic · React, TypeScript, Vite,
Tailwind, shadcn/ui, TanStack Query · pytest, Playwright.

**Provider abstraction.** `app/ai/provider.py` defines an `LLMProvider`
protocol with six methods. Four implementations exist (OpenAI, Anthropic,
Ollama, mock). Business logic never imports an SDK, so swapping models or
vendors touches no validation or clinical logic. The mock is what the test
suite runs against — deterministic, offline, no billing.

---

## 3. Shared Core

### 3.1 Patients

Registration captures name, date of birth, room, preferred language, and
**why the patient has come in**. Each patient gets a generated code (`P1001`)
used as their wristband identifier.

Supplying the reason opens the patient's **first encounter in the same step** —
previously the field existed but nothing ever asked for it, so it was
effectively always empty.

Admission status is `ACTIVE` or `DISCHARGED`. Discharge revokes all care links
in the same transaction and blocks new instructions.

### 3.2 Encounters (visits)

A visit, so a diagnosis or order from one admission never silently merges with
an unrelated one. Carries the reason for visit, admission/discharge dates,
status, and — for surgical patients — the **planned procedure** and the time
from which the patient is **nil by mouth**. That last field is what Module 2
reads to hold oral medication before theatre (§5.4).

### 3.3 Conditions

Clinician-documented diagnoses, free text. Drives a curated patient-facing
explainer (§4.6).

**Permanently and deliberately: a documented condition is never used to infer
why a medication was prescribed.** An earlier version did this and it was
removed as a safety correction — a diagnosis sitting alongside a medication
that happens to treat it is an inference, not a documented fact.

### 3.4 Allergies

Allergen, optional reaction and severity. Checked automatically before every
dose (§5.4) and shown back to the patient (§4.7).

Matching is on the base drug name, case-insensitive. Entries shorter than four
characters must match exactly rather than as a substring — a stray one- or
two-letter entry previously blocked unrelated drugs (`"o"` blocked Metoprolol)
and presented a typo as an ALLERGY ALERT.

### 3.5 Authentication

Dev JWT provider behind an `AuthProvider` interface (Cognito-ready). bcrypt
password hashing, minimum 10 characters. Per-IP rate limiting on login and
registration — deliberately per-IP rather than per-account, because hospital
staff commonly share one NAT gateway. Failed logins are recorded.

### 3.6 Audit trail

Append-only. One writer (`record_event`), no update or delete anywhere, and a
test proving no PATCH/DELETE route exists.

Never stores PHI, raw prompts, provider responses, or model reasoning — it
records *that* something happened and to whom, not the clinical content.

All 42 event types have human-readable labels, categorised as info / approval /
safety-warning / patient-activity. A guard test fails the build if an event
type is added without a label — written after eight Module 2 events rendered as
raw enum strings, with blocked wrong-drug scans displaying as grey "info" dots
indistinguishable from a login.

---

## 4. Module 1 — Medication Understanding

Turns a clinician's order into something a patient can actually understand, in
their own language, without ever changing what it says.

### 4.1 Writing an instruction

Free text, exactly as written for the chart. Or dictated (§4.3).

### 4.2 Analysis, generation and validation

Automatic on creation:

1. **Extraction** — an LLM pulls structured facts (drug, dose, unit, route,
   frequency, timing, duration, warnings, reason). It is instructed never to
   invent a value it has no textual evidence for.
2. **Completeness check** — deterministic. A medication order missing a dose
   is not a medication order. Incomplete → `NEEDS_REVIEW` with a clarification
   request.
3. **Generation** — a second LLM call rewrites the instruction for a patient.
4. **Fact preservation** — the generated text is **re-extracted by an
   independent call** and diffed field-by-field against the original facts.
   Any difference → `NEEDS_REVIEW`. The model is never asked whether its own
   output is safe.
5. **Reading level** — a Flesch-Kincaid grade score (pure arithmetic, no LLM)
   shown to the clinician before approval. AMA/CDC guidance targets ~6th grade.
   Advisory, not a gate: a long drug name raises the score without making the
   sentence harder.
6. **Approval** — only a clinician can approve, and only when validation
   passed. Nothing reaches a patient otherwise.

**Status flow:** `DRAFT → PROCESSING → READY_FOR_APPROVAL → APPROVED`, with
`NEEDS_REVIEW` and `REJECTED` branches. Clarifications create a new immutable
version; nothing is ever edited in place.

**Clinical status** (medications only): `ACTIVE`, `STOPPED`, `COMPLETED`.

### 4.3 Voice dictation

A 🎤 button beside the textarea. The clinician speaks; the transcript arrives
as an **editable draft**.

**Why this is designed differently from everything else.** Every other AI
output has a deterministic validator behind it. A transcript cannot. It
*becomes* the instruction text — the source of truth every later check
validates *against*. A mis-heard "50 mg" as "15 mg" would be faithfully
extracted, faithfully confirmed as preserved, and faithfully compared at the
bedside. Every check passes and the system is confidently wrong.

So the clinician's review is made structurally unavoidable: the transcription
endpoint takes **no patient ID and creates nothing**. There is physically
nothing for a transcript to be written to. It becomes an order only when the
clinician submits it through the ordinary creation endpoint.

**Dictation safety scan.** Since no downstream check can catch a transcription
error, a deterministic scan runs on the transcript itself, using ISMP's
published error-prone dose designations — specifically those that are *speech*
confusions: trailing zeros (`5.0 mg` → 50), naked decimals (`.5 mg` → 5),
mcg/mg, `U` for units, `QD`/`QID`. Advisory flags, never blocking.

Provenance (`TYPED` / `DICTATED`) is recorded on every version.

### 4.4 Translation

11 languages: English, Spanish, Mandarin, Vietnamese, Tagalog, Arabic, Korean,
Russian, French, Hindi, Telugu.

Every translation goes through the **same fact-preservation check** as the
English original — a translation that drops a warning or changes a dose is
rejected. Arabic renders right-to-left.

### 4.5 Text to speech

Any instruction can be read aloud in the patient's language. An accessibility
aid, never a source of truth — the text remains canonical if synthesis fails.
A test verifies every language has a voice, and a second verifies each voice
name actually exists upstream.

### 4.6 The patient's view

A private tokenised link. No login, no app. Large type, plain language.

- **Their allergies**, with an explicit prompt to speak up if anything is
  wrong — the patient is the one person positioned to notice.
- **Current medications**, expandable.
- **Why they are taking it** — three tiers: the clinician's documented reason;
  or curated general reference information, clearly labelled and disclaimed;
  or nothing. Never a guess.
- **Condition explainers** — curated, human-written, never generated.
- **Medications they are no longer taking**, where a drug **stopped** by the
  team is visually distinct from a course **finished**: the stopped one is
  red-bordered and says *"Stopped by your care team — do not take this any
  more."* These need opposite responses from the patient, and previously
  rendered identically.
- **Language switcher**, all 11.
- **Ask a question** (§4.8).

### 4.7 Comprehension and teach-back

Rather than a "yes I understand" button — which verifies nothing — the patient
is asked to explain the instruction back in their own words, the **teach-back
method** (AHRQ's most effective measured health-literacy technique). A
deterministic check looks for the drug, timing and reason in their answer.
Weak answers raise a clinician-facing flag; they are never told they are wrong.

### 4.8 Patient chat

Grounded strictly in the patient's own approved care plan plus curated
reference facts, with optional live web search restricted to four trusted
medical domains (MedlinePlus, Mayo Clinic, CDC, NIH).

Two **deterministic** gates run before any model call:
- **Emergency language** → immediate fixed response directing them to
  emergency care, flagged to clinicians.
- **Treatment-change requests** → redirected to their care team, never
  answered.

Off-topic questions get a fixed decline. Stopped and completed medications are
excluded from the chat's context.

---

## 5. Module 2 — Administration Verification

Bedside barcode verification (BCMA). **No LLM is in the decision path** — every
result is deterministic code comparing the scan against the patient's live
orders.

### 5.1 Step 1 — Identify the patient

Scan a wristband QR or type the patient code.

### 5.2 Step 2 — Confirm identity

Name and date of birth shown, and the nurse must **actively confirm** before
the medication step unlocks. Joint Commission requires two identifiers; a
single code lookup is one. A "No — wrong patient" option returns to step 1.
Discharged patients show a red badge here, before anything is scanned.

### 5.3 Step 3 — Identify the medication

Scan the barcode, or — if it won't scan — **photograph the label**. An LLM
reads the label and returns an **unconfirmed candidate** the nurse must review
and correct before it enters the engine. Image-identified results are
permanently labelled as such, everywhere they appear.

### 5.4 The checks

All deterministic, all against live data:

| Check | What it does |
|---|---|
| **Patient** | Wristband resolves to this patient |
| **Admission** | Patient is still admitted — a discharged patient is blocked |
| **Allergy** | Product cross-referenced against documented allergies → **blocks** |
| **Nil by mouth** | Held before a procedure — **route-aware**: blocks oral, permits injected |
| **Order status** | An ACTIVE order exists; a stopped one is named explicitly |
| **Dose** | Exact value and unit match |
| **Formulation** | Salt form / release type — only ambiguous when the drug is genuinely stocked in more than one form |
| **Route** | Matches the order |
| **Time** | Within the window, against the **hospital's** wall clock, not UTC |
| **Interactions** | Against the patient's other active medications — severe blocks, moderate warns |

**Results:** `VERIFIED` · `WARNING` (acknowledge to proceed) ·
`REVIEW_REQUIRED` · `BLOCKED`.

### 5.5 Confirming administration

Before anything is recorded, the engine **revalidates against a fresh read** —
the order may have been stopped or changed since the scan. It also checks for a
duplicate administration within a recency window, and takes a row lock so two
concurrent confirmations cannot both succeed.

Additional gates:
- **High-alert medications** (ISMP list — anticoagulants, insulin, opioids)
  require an **independent second clinician to authenticate** with their own
  credentials. Not a name picked from a list; not the same person twice.
- **As-needed (PRN) doses** require a documented indication ("pain 7/10"). A
  scheduled dose is justified by its schedule; a PRN dose is not.

### 5.6 Doses that are not given

A dose can be recorded as **refused, held, patient unavailable, vomited, or
other**, with a note. This is documentation of care, not an error path —
without it a dose that did not happen was invisible, and an abandoned scan was
indistinguishable from a refusal.

A blocked scan can still be documented as held: *"the scan was blocked, so I
held the dose and called the doctor"* belongs on the record.

Each verification resolves exactly once — given or not given, never both.

### 5.7 The administration record (MAR)

A per-patient record showing every bedside scan: what was given, when, by
whom, the PRN indication, whether it was independently co-signed, and whether
it came from a photo rather than a barcode.

**Blocked attempts appear alongside given doses deliberately** — a wrong drug
caught at this bedside is part of the patient's medication story.

---

## 6. End-to-end flows

### 6.1 Order → patient

```
Clinician writes or dictates an order
   └→ AI extracts structured facts
        └→ completeness check (deterministic)      ── incomplete → NEEDS_REVIEW
             └→ AI generates patient-friendly text
                  └→ independent re-extraction + field-by-field diff
                       └→ any difference → NEEDS_REVIEW
                       └→ match → READY_FOR_APPROVAL
                            └→ clinician approves
                                 └→ translation (+ its own fact check)
                                      └→ visible on the patient's care link
```

### 6.2 Bedside administration

```
Scan wristband → confirm name + DOB → scan medication (or photograph label)
   └→ deterministic checks (§5.4)
        ├→ BLOCKED          → document as held / refused, or rescan
        ├→ REVIEW_REQUIRED  → clinician review
        ├→ WARNING          → acknowledge → confirm
        └→ VERIFIED         → confirm
                              ├→ revalidate against fresh order state
                              ├→ duplicate check
                              ├→ high-alert? second clinician authenticates
                              ├→ PRN? indication required
                              └→ recorded on the MAR + audit trail
```

### 6.3 How the modules connect

Module 2 has **no order model of its own**. It reads the `CareInstruction`
rows Module 1 produced — so an order stopped in Module 1 is blocked at the
bedside immediately, with no synchronisation step. The encounter's nil-by-mouth
state, the allergy list and the admission status are all Shared Core, read by
both.

---

## 7. Safety design rules

Rules the codebase holds to, each learned from a specific problem:

1. **AI proposes, code decides, a clinician approves.**
2. **Never infer a medication's purpose from a diagnosis** — even when only one
   diagnosis exists.
3. **Never auto-approve on uncertainty** — ambiguity is a review state.
4. **Never fabricate on failure** — a failed provider call produces an error,
   not a guess.
5. **Re-validate at the moment of action**, not at the moment of checking.
6. **An alert that fires on correct work is a safety problem**, because it
   teaches people to click through. Several fixes exist purely to stop
   false alarms.
7. **Disclose the weaker path** — image identification is labelled as such
   permanently.
8. **Situational state is part of safety** — discharged, nil by mouth. Orders
   alone are not enough.

---

## 8. Data model

| Table | Purpose |
|---|---|
| `users` | Clinician accounts |
| `patients` | Demographics, code, language, admission status |
| `encounters` | Visits; reason, procedure, nil-by-mouth |
| `patient_conditions` | Documented diagnoses |
| `patient_allergies` | Documented allergies |
| `care_instructions` | Orders — status, clinical status |
| `instruction_versions` | Immutable text versions; source, capture method |
| `structured_extractions` | Extracted + normalized facts |
| `patient_outputs` | Patient-friendly text, validation result, reading level |
| `patient_output_translations` | Per-language text + its own validation |
| `patient_care_access_tokens` | Hashed care links, expiry, revocation |
| `patient_chat_messages` | Chat transcript |
| `patient_comprehension_feedback` | Teach-back and comprehension |
| `administration_events` | Every bedside scan, outcome, co-sign, not-given |
| `audit_events` | Append-only trail |

Schema changes go through Alembic migrations only.

---

## 9. API reference

**Auth** — `POST /auth/register` · `POST /auth/login` · `GET /auth/me`

**Patients** — `POST /patients` · `GET /patients` · `GET /patients/{id}` ·
`GET /patients/by-code/{code}` · `PATCH /patients/{id}`

**Encounters** — `POST /patients/{id}/encounters` ·
`GET /patients/{id}/encounters` · `PATCH /encounters/{id}`

**Conditions / allergies** — `POST|GET|DELETE /patients/{id}/conditions` ·
`POST|GET|DELETE /patients/{id}/allergies`

**Instructions** — `POST /patients/{id}/instructions` ·
`GET /patients/{id}/instructions` · `GET /instructions/{id}` ·
`POST /instructions/{id}/analyze` · `/generate` · `/approve` · `/reject` ·
`/clarify` · `/translations` · `PATCH /instructions/{id}/clinical-status` ·
`POST /instructions/transcribe`

**Care links** — `POST /patients/{id}/care-access-tokens` ·
`GET /patients/{id}/care-access-tokens` ·
`POST /care-access-tokens/{id}/revoke`

**Patient-facing (token, no login)** — `GET /care-plan` ·
`POST /care-plan/audio` · `POST /care-plan/feedback` ·
`POST /care-plan/teach-back` · `GET|POST /care-plan/chat`

**Module 2** — `POST /medication-verification/verify` · `/verify-confirmed` ·
`/identify-from-image` · `/administer` · `/not-given` ·
`GET /patients/{id}/administrations` · `GET /medication-products/{barcode}`

**Audit** — `GET /patients/{id}/audit`

---

## 10. Security and privacy

- bcrypt passwords; JWT sessions; the app **refuses to start** on a placeholder
  JWT secret.
- Per-IP rate limiting on auth endpoints; failed logins audited.
- Care links: 256-bit tokens, **stored only as hashes**, expiring, revocable,
  auto-revoked on discharge. "Expired", "revoked" and "never existed" are
  indistinguishable to a caller.
- CORS restricted to explicit methods and headers.
- Database TLS configurable; encryption at rest is a hosting concern by design.
- Audit metadata never carries PHI, prompts, or model output.
- Raw LLM prompts/responses are not persisted.

**Open compliance item:** sending real patient data to a standard OpenAI or
Anthropic API key is not HIPAA-eligible without a BAA. Fine for synthetic data;
must be addressed before real PHI. Dictated audio is a larger PHI surface than
typed text — people say things aloud they would never type — so audio is
transcribed and immediately discarded, never stored.

---

## 11. Testing

Backend: pytest, against a real PostgreSQL database with real Alembic
migrations, so schema drift is caught. The suite forces the mock AI provider
and a fixed timezone regardless of local configuration — after a run against
the live API once turned a 95-second suite into a 20-minute billed hang.

Notable guard tests, each written after a real failure:
- every audit event type has a frontend label;
- every language has a TTS voice, and each voice exists upstream;
- timing tests declare their timezone rather than inheriting it.

Frontend: TypeScript strict typecheck, plus Playwright scripts driving a real
browser against the real backend — including camera and microphone paths using
Chromium's fake devices fed real synthesized speech.

---

## 12. Running it

```bash
# Database
cd backend && docker compose up -d

# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set JWT_SECRET_KEY, OPENAI_API_KEY, HOSPITAL_TIMEZONE
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend
cd ../frontend && npm install && npm run dev
```

`LLM_PROVIDER=mock` runs fully offline. `HOSPITAL_TIMEZONE` must match where
the nurses actually are — left at UTC in a non-UTC hospital, every correctly
timed morning dose is reported as late.

**Demo assets:** `demo-assets/` holds the recorded walkthrough, medication
barcodes, a wristband QR, a label photo, and the dictation audio.

---

## 13. What is deliberately not built

Named honestly, because a partial version of several of these would create
false confidence.

| Not built | Why |
|---|---|
| **FHIR / HL7 interoperability** | The right long-term answer for talking to a real EHR, but a partial layer that isn't spec-compliant is worse than none |
| **Medication reconciliation across transitions** | A materially larger feature; Joint Commission expects it in a full system |
| **NDC / GS1 barcodes** | Barcodes are prototype strings; real unit-dose packaging uses coded formats |
| **Role system** | One `clinician` role. High-alert co-sign works anyway — it needs a different *person*, not a different title |
| **Nurse badge scan at the bedside** | Session auth stands in for the badge leg of the three-way scan |
| **Drug interaction database** | A small curated table, not First Databank or Lexicomp |
| **"Due now" worklist** | The nurse must know what to give; the system verifies rather than prompts |
| **Cross-patient alert queue** | Signals are visible on each patient, not aggregated. The single biggest remaining usability gap |
| **Escalation from BLOCKED** | Rescan or document as held; no pharmacist referral workflow |
| **Live / real-time updates** | Views are fetched, not pushed |
| **Module 3 — wearables, falls, mobility** | Scoped from the start, never begun |

---

*Everything described above is implemented and covered by automated tests
unless explicitly listed in §13.*

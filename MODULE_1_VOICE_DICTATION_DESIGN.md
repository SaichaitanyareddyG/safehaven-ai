# Design: Clinician Voice Dictation for Care Instructions

**Status:** ✅ **approved and built as designed** (2026-09-15). All four decisions in §13 were
answered "build it all as designed": OpenAI transcription, `capture_method` as a separate column,
the ISMP dictation-safety checker in scope, English first. Build notes at the end of this document.
**Scope:** Module 1, instruction entry only. Shared Core and Module 2 unchanged.

---

## 1. Why this one, and why now

Two things point here:

- **Your explicit ask**, which nothing built so far has addressed: *"make sure efforts for doctor as
  well."* Everything delivered this session (allergy checks, two-identifier confirmation,
  teach-back, readability scoring, condition explainers, high-alert co-sign, drug interactions)
  reduces patient risk or helps the patient. None of it reduces a clinician's workload — it mostly
  adds steps for them.
- **The market research** already done (see `MARKET_ANALYSIS_AND_VISUAL_EXPLAINER_DECISION.md`):
  AI ambient scribes are the dominant 2026 clinician-efficiency trend — 60+ vendors, measured
  savings of roughly 2× EHR time and 3× documentation time for heavy users, and early burnout
  reductions at Mass General Brigham. Every source also carries the same caveat: errors,
  omissions, and hallucinations mean **diligent clinician review is required**.

Today a clinician types the full clinical instruction into a textarea. That typed text becomes
`InstructionVersion.raw_text`, which the entire pipeline treats as ground truth.

---

## 2. Scope: this is *dictation*, not *ambient scribing*

Worth being precise, because the market term is broader than what fits here.

| | Ambient scribing (what vendors sell) | Dictation (what this designs) |
|---|---|---|
| Input | Passive recording of a whole patient encounter | Clinician deliberately dictates one instruction |
| Output | A full structured clinical note | One care-instruction text |
| Model work | Summarize + infer + structure a conversation | Transcribe speech to text |
| Risk surface | Very large — the model decides what mattered | Much smaller — the model only transcribes |

Ambient scribing would mean the model **choosing what to include** from a conversation. That is a
fundamentally different (and far riskier) product than transcribing what a clinician deliberately
said, and it doesn't fit this app's single-instruction data model at all. **Explicitly out of
scope.** If it's ever wanted, it's a separate module, not an extension of this.

---

## 3. The core safety problem (the part that shapes everything else)

This codebase's whole architecture is *"AI proposes, deterministic validation decides."* Generated
patient text is re-extracted and diffed field-by-field (`fact_preservation.py`). Translations are
checked the same way. Medication scans are compared against structured order facts. Every AI output
has something deterministic behind it.

**Voice dictation breaks that pattern's assumptions — not by weakening a check, but by sitting
upstream of all of them.**

The transcript becomes `InstructionVersion.raw_text`. That is the *source of truth* every
downstream validator compares against. So if the transcript says `15 mg` when the clinician said
`50 mg`:

- extraction faithfully extracts `15 mg`
- fact-preservation faithfully confirms the patient-friendly text preserved `15 mg`
- Module 2 faithfully blocks a scanned 50 mg product as a dose mismatch — **against the wrong order**
- every check passes, and the whole system is confidently, consistently wrong

**No downstream validation can catch a transcription error, by construction.** The validators
verify *fidelity to the source*, and the corrupted value *is* the source.

### What follows from that

1. **A transcript may never be auto-submitted.** It lands in the same textarea the clinician
   already uses, as an editable draft. The clinician submits it exactly as if they'd typed it.
   There is no "dictate and it files itself" path, ever.
2. **The clinician is the validation layer here** — not code. That is an honest statement of where
   the safety boundary sits, and it matches how every scribe vendor actually operates.
3. **Provenance must be recorded**, so an audit can later distinguish dictated orders from typed
   ones. If a dictation-related error ever occurs, that distinction is the first thing anyone
   reviewing it will want.
4. **The UI must not imply verification.** No confidence percentages, no green checkmarks on a raw
   transcript. It's a draft, and should look like one.

---

## 4. Where transcription runs

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Browser Web Speech API** | Free, no backend, audio never leaves the device | Inconsistent across browsers, weak medical vocabulary, unreliable for Telugu/Hindi | ❌ — this project already rejected browser-native speech for exactly this reason (see `tts/service.py`'s docstring on `speechSynthesis`) |
| **B. Backend via provider API** (OpenAI `gpt-4o-transcribe` / `whisper-1`) | Consistent, strong medical vocabulary, multilingual, slots behind the existing `LLMProvider` protocol | Audio leaves the machine (PHI/BAA flag) | ✅ **Recommended** |
| **C. Local model** (faster-whisper) | No PHI leaves the machine | Heavy install, slow on CPU, a real ops burden for a prototype | Defer — but B keeps it swappable |

**Recommended: B**, mirroring precedent exactly. The OCR/vision path already sends images to
OpenAI; adding a sixth method to the `LLMProvider` protocol keeps this swappable to a local model
or a different vendor without touching business logic — the same way `openai_vision_model` was
added for the OCR path without disturbing anything else.

### PHI note that is *stronger* here than elsewhere

The existing BAA flag (standard API keys aren't HIPAA-eligible without a Business Associate
Agreement) already applies to every LLM call in this app. **It applies more forcefully to audio.**
A clinician dictating aloud will say things they'd never type into an order field — the patient's
name, room number, a colleague's remark, whatever is happening in the room. Typed input is
naturally scoped; speech is not. This doesn't block a prototype using synthetic data, but it
should be written down as a materially larger PHI surface than the text paths.

---

## 5. Audio is transcribed and discarded — never stored

Recommendation: **never persist the audio.** Transcribe it in-request, return the text, drop the
bytes.

Storing it would mean a new PHI surface with its own encryption, retention policy, access control,
and deletion story — real work, for little prototype value. This matches the existing
`STORE_RAW_LLM_DATA=false` posture and `identify_from_image()`, which already takes image bytes
and persists none of them.

Consequence to accept honestly: if a transcript is later disputed, there's no recording to compare
against. That is the right trade for a prototype, and it should be a deliberate decision rather
than an oversight.

---

## 6. Deterministic dictation-safety check (the part that's actually novel)

Since no *downstream* validator can catch a transcription error, the useful place to add value is
a check on the transcript itself — deterministic, no LLM, purely pattern-based.

ISMP publishes an official **Error-Prone Abbreviations, Symbols, and Dose Designations** list.
Several entries on it are *specifically* speech-confusion failures, which makes them exactly right
to flag on a dictated draft:

| Pattern | Why it's dangerous | Flag shown to clinician |
|---|---|---|
| Trailing zero (`5.0 mg`) | Decimal missed → 10× overdose (50 mg) | "Write 5 mg, not 5.0 mg" |
| Naked decimal (`.5 mg`) | Leading dot missed → 10× overdose (5 mg) | "Write 0.5 mg, not .5 mg" |
| `mcg` / `mg` both present or ambiguous | 1000× dosing error; sound-alike when spoken | "Confirm mcg vs mg" |
| `U` or `IU` for units | `U` misread as 0 or 4 | "Write 'units' in full" |
| `QD` / `QOD` / `QID` | Sound- and look-alike frequencies | "Write the frequency in words" |
| No numeric dose found in a drug-sounding instruction | Dictation may have dropped it entirely | "No dose detected — confirm" |

This is **advisory, never blocking** — same treatment as the readability score just built. It's a
"look at this line again" nudge on a draft the clinician is about to edit anyway, not a gate.

Value: it addresses the one failure mode the rest of the architecture structurally cannot, and it
does so with a deterministic rule set citing a real published standard — consistent with how every
other reference table in this codebase works.

---

## 7. Data model changes

Small, additive.

**`VersionSource` enum** — add `DICTATED`:
```python
class VersionSource(str, enum.Enum):
    ORIGINAL = "ORIGINAL"
    CLARIFICATION = "CLARIFICATION"
    DICTATED = "DICTATED"        # new
```

⚠️ **Migration gotcha, already hit twice in this project:** this is a *native* Postgres enum
(`native_enum=True`). Adding a value needs an explicit `ALTER TYPE instruction_version_source ADD
VALUE 'DICTATED'` — it will not be inferred, and `ALTER TYPE ... ADD VALUE` cannot run inside a
transaction block on older PG, so the migration needs `op.execute` with autocommit handling. This
is why the string-enum audit events (`AuditEventType`) needed no migration but this one does.

Open question worth deciding: is `DICTATED` a *source* (mutually exclusive with `ORIGINAL`) or a
*capture method* (orthogonal — a clarification could also be dictated)? Cleanest is the latter: a
separate nullable `capture_method` column rather than overloading `source`. **Recommendation:
separate column**, since `source` currently answers "which step of the workflow created this" and
conflating "how was it typed" into it loses information the moment someone dictates a
clarification.

**New audit event:** `INSTRUCTION_DICTATED` (plain string enum on `AuditEventType` — no migration,
same as every other audit event added). Records that dictation was used, never the transcript text
(same no-PHI-in-metadata rule as every other event).

---

## 8. API surface

One new endpoint, mirroring `identify-from-image`'s multipart pattern exactly:

```
POST /instructions/transcribe        (multipart: file)
  → { "text": "...", "warnings": [ {code, message, excerpt}, ... ] }
```

Deliberately **not** `POST /patients/{id}/instructions/from-audio`. Transcription creates nothing
— it returns a draft string and advisory warnings. Instruction creation stays exactly the endpoint
it is today, with the clinician's (possibly edited) text. That separation is what makes
"auto-submission is impossible" a structural property rather than a UI convention.

New `LLMProvider` protocol method:
```python
def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> RawTranscriptionResponse: ...
```
implemented across all four providers (openai / anthropic / ollama / mock), same as the other five.
The mock returns a canned transcript so the test suite stays offline.

---

## 9. UI flow

In `CreateInstructionDialog`, next to the existing textarea:

1. **🎤 Dictate** button → browser `MediaRecorder` captures audio (mic permission prompt).
2. **Recording…** state with a stop button. No live transcript — avoids implying real-time
   verification.
3. On stop → upload → "Transcribing…" → transcript **inserted into the textarea, editable**,
   cursor placed at the end.
4. Any dictation-safety warnings shown beneath it, in the advisory amber style already used for
   the formulation-unspecified and readability cases.
5. The clinician edits and presses the same **Create instruction** button as always.

The transcript is never displayed anywhere it can't be edited, and the submit button is never
auto-pressed. If transcription fails, the textarea is untouched and typing still works — same
graceful-degradation posture as the TTS service ("audio is an aid, the text remains canonical").

---

## 10. Failure modes

| Failure | Handling |
|---|---|
| Mic permission denied | Dictate button shows a one-line explanation; typing unaffected |
| Browser lacks `MediaRecorder` | Button hidden entirely; typing unaffected |
| Provider/API error or timeout | "Couldn't transcribe — please type it" ; textarea untouched |
| Empty/silent audio | Returns empty text + an explicit "nothing detected" message, never a fabricated transcript |
| Transcript is wrong | **Clinician edits it.** This is the designed path, not an edge case |
| Very long recording | Cap at ~2 minutes client-side (an instruction is a sentence or two, not a consult) |

---

## 11. Test plan

- **Unit:** the dictation-safety checker — one test per ISMP pattern (trailing zero, naked decimal,
  mcg/mg, `U`, `QD`, missing dose), plus clean text producing no warnings.
- **Integration:** `/instructions/transcribe` returns text + warnings via the mock provider;
  auth required; oversized/empty file rejected; provider failure degrades cleanly.
- **Provenance:** an instruction created from a dictated draft records `capture_method=DICTATED`
  and an `INSTRUCTION_DICTATED` audit event; a typed one records neither.
- **Live (Playwright):** the established camera-fake pattern has a microphone equivalent
  (`--use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<file.wav>`), so the real
  browser flow is verifiable end-to-end the same way the QR-scanning path was.

---

## 12. Explicitly out of scope

- Ambient scribing / conversation summarization (see §2)
- Storing or replaying audio (see §5)
- Real-time streaming transcription (batch on stop is sufficient and simpler)
- Dictation on the patient-facing side (patients already have chat; different problem)
- Voice-driven navigation or commands ("open patient 3") — a different feature entirely

---

## 13. Decisions I'd like confirmed before building

1. **Provider choice** — OpenAI transcription (recommended), or hold for a local/offline model
   given the larger audio PHI surface?
2. **`capture_method` as a separate column** (recommended) vs. overloading `VersionSource`?
3. **Dictation-safety checker in scope for this pass** (recommended — it's the part that addresses
   the one gap nothing else can), or ship plain dictation first and add it after?
4. **English-only to start**, or dictation in Telugu/Hindi too? (The clinician-facing side of this
   app is English today; the model supports more, but every added language needs its own live
   check rather than an assumption.)

---

## Summary

Voice dictation is a genuine clinician-effort win and fits the existing architecture cleanly — one
new provider method, one new endpoint, one enum value, one advisory checker. The one thing that
makes it different from every other AI feature in this codebase is that **its output sits upstream
of every validator**, so the clinician's own review is the safety boundary and the design has to
make that structurally unavoidable rather than merely encouraged. Everything above follows from
that.

---

## Build notes (what actually shipped)

Built exactly as designed, no deviations.

**Backend**
- `RawTranscriptionResponse` + `transcribe_audio()` on the `LLMProvider` protocol, implemented
  across all four providers (OpenAI real; Anthropic/Ollama raise the same explicit
  not-implemented error the image method already uses; mock returns fixture transcripts).
- `openai_transcription_model` setting (`gpt-4o-transcribe`), separate from `openai_model` because
  transcription is a different API surface with non-overlapping model names.
- `app/validation/dictation_safety.py` — the ISMP checker, 6 patterns, pure regex, no LLM.
- `CaptureMethod` enum (TYPED/DICTATED) as its own nullable column on `InstructionVersion`,
  migration `06a3cd513143` — which needed the explicit `CREATE TYPE` + `create_type=False` fix,
  exactly as §7 predicted.
- `POST /instructions/transcribe` — takes no `patient_id` and creates nothing, so the
  "a transcript cannot become an order by itself" property is structural, not conventional.
- `AuditEventType.INSTRUCTION_DICTATED`, recorded with no transcript text in metadata.

**Frontend** — Dictate/Stop buttons on `CreateInstructionDialog`, `MediaRecorder` capture, 2-minute
cap, transcript *appended* to whatever is already in the textarea (a clinician may dictate an
addition to text they typed), a "read it back before creating" notice, and the amber warnings
panel. Submit is disabled while recording or transcribing. If anything fails, the textarea is left
untouched and typing works exactly as before.

**Verification**
- 419/419 backend tests (24 new: 14 unit on the ISMP checker, 10 integration on the endpoint and
  provenance), including explicit tests that transcription creates nothing and that a provider
  failure never fabricates a transcript.
- Live end-to-end in a real browser, using Chromium's fake audio device fed **real synthesized
  speech** (generated with the project's own edge-tts dependency, so this was genuine
  speech→text, not a stub): recorded, transcribed by the real OpenAI API to *"Take metoprolol
  succinate ER 25mg orally twice daily"*, confirmed the textarea stayed editable, confirmed the
  database had zero instructions at that point, then confirmed submitting recorded
  `INSTRUCTION_DICTATED`.
- Full existing regression (`frontend/verify_all_flows.mjs`) still passes with no console errors.

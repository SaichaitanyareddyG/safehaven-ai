# Market Analysis + "Visual Disease Explainer" Feature Decision

Written in response to: "analyze all products in market... many features we need... effort
[-friendly] for doctors as well... best friendly for patients as well... capable for report
image generation... what was disease how it infected where... in single multi picture... check
internet best way... analyze best method pickup implement." Below: what the market actually
looks like right now, what was found about the specific image-generation idea, and what was
built instead — with reasoning, not just an announcement.

---

## 1. Market landscape (real research, not assumption)

**Patient education / engagement platforms** — the closest category to Module 1:
- **GetWellNetwork** is the dominant player: 10M+ patients/year across 1,000+ hospitals, delivers
  condition-specific education via bedside TVs/tablets, tied to structured digital care plans.
- **Krames** / **WebMD Ignite** and **VisualDx** are the major *content* providers — curated,
  medically-reviewed libraries (VisualDx: ~47,000 images, ICD/SNOMED coded, 29% covering darker
  skin tones for equity). This is licensed, human-vetted content, not AI-generated per request.
- The market itself is large and growing fast: the healthcare education solution market is ~$11B
  in 2026, growing ~11%/year.
- A relevant warning surfaced directly in the research: "Point-of-care platforms offer
  technology-first solutions using AI-generated personalized videos... though these innovative
  delivery mechanisms often lack the depth of **medically reviewed editorial content**." This is
  exactly the trade-off this section is about.

**Doctor-facing / clinician-efficiency** — "effort-friendly for doctors":
- The dominant 2026 trend by far is **AI ambient scribes** — at least 60 vendors now in this
  space, capturing visit audio and drafting clinical notes automatically. Real, measured (not
  hypothetical) results: clinicians using scribes for ≥half their visits saved roughly double the
  EHR time and triple the documentation time of light users, and saw about one extra visit every
  2 weeks. Mass General Brigham reported early burnout reductions from a pilot.
- The caveat is consistent across every source: scribes still require **diligent clinician
  review** — errors, omissions, and occasional hallucinations in the generated notes are a known,
  unresolved issue, not a solved problem.
- **What this means for SafeHaven:** the current instruction-entry flow (clinician types free
  text → AI extracts structured facts) is already aligned with where the market is headed
  conceptually — but a real ambient-scribe-style voice input to that same pipeline would be the
  highest-leverage "less effort for doctors" feature, and it slots into the *existing*
  architecture without changing anything downstream (extraction/validation/generation stay
  exactly as they are — only the text capture step would change, from typed to
  transcribed-then-typed). **Flagging this as a strong candidate for a future step — not built in
  this pass**, since it's a genuinely separate feature (audio capture, a transcription provider,
  UI for reviewing/editing before submit) rather than a small addition.

---

## 2. The "disease explainer image" idea — researched, and deliberately NOT built as AI image generation

### What was asked
A single image (or multi-panel visual) per documented condition, showing what the disease is,
how it develops/is caused, and where in the body it affects — generated automatically.

### What the current research says about generating that with AI
Checked directly (2026, peer-reviewed, not older/stale sources):
- A study of AI-generated illustrations in published aesthetic-medicine literature found **all**
  identified AI-generated images had **gross anatomical inaccuracies** — including invented
  ("hallucinated") anatomical structures that don't exist.
- A broader comparative evaluation across current image models found accuracy "varying from
  medically indistinguishable to **biologically impossible**" once anatomical complexity rises
  past simple shapes (an aortic arch renders fine; something like a temporal-region muscle
  diagram or a specific disease's tissue-level effect often doesn't).
- Direct quote from the research that applies exactly here: "A hallucinated blood vessel or an
  incorrectly positioned nerve is not a stylistic choice — it is a critical failure that can
  mislead a... **misinform** a [patient]."
- 47% of the studies reviewed found clinical-fidelity problems ranging from hallucinated anatomy
  to "plausible but incorrect" depictions — the dangerous middle ground where an image looks
  legitimate but is wrong in a way neither a patient nor a fast clinician review would catch.

### Why this matters for THIS app specifically
SafeHaven's entire architecture rests on one non-negotiable rule, applied consistently everywhere
else in the codebase: **the AI proposes, a deterministic layer decides — nothing an LLM outputs
is ever shown to a patient without being checked against structured facts** (see
`fact_preservation.py`'s three-layer validation for generated text, `resolve_why()`'s "never
guess, never let an LLM fill a reference gap" rule for medication purpose, and this session's own
`_check_teach_back` for the patient's own explanation). Generated *text* is checkable this way —
every fact can be re-extracted and diffed field-by-field. **A generated image has no equivalent
deterministic check.** There is no `fact_preservation.py` for pixels. Shipping an AI-generated
anatomical image straight to a patient would be the one place in this app where an ungrounded
model output reaches a patient with zero validation — a direct contradiction of the project's own
standing safety principle, not just a stylistic risk.

### What was built instead (same safe pattern this app already uses twice)
`medication_purpose.py` (medication general-info) and `medication_products.py` (medication
verification catalog) already solve an identical problem — "we want AI-free, trustworthy general
reference content" — the same way: a small, **hand-curated, static table**, never generated live,
extended by replacing the table (not the code) when real licensed content is available.

Built `app/reference/condition_explainers.py` following that exact precedent: ~15 common
documented conditions (hypertension, type 2 diabetes, asthma, COPD, coronary artery disease,
heart failure, atrial fibrillation, hypothyroidism, chronic kidney disease, osteoarthritis,
depression, anxiety, GERD, etc.), each with three plain-language facts — **what it is**, **how it
develops**, **where it affects you** — matched to a clinician-documented `PatientCondition` by
exact name.

This is rendered on the patient care page as a genuine **multi-panel visual card** (three panels,
each with its own icon — a stethoscope, a trend icon, a location pin) — satisfying the "single
multi-picture" ask as a real visual, structured layout, without a single AI-generated pixel or
any hallucination risk. If a documented condition isn't in the curated table, it still shows by
name (never hidden) with a plain "ask your care team" note — never a guess, matching
`resolve_why()`'s standing rule.

**Built and verified this session:**
- `app/reference/condition_explainers.py` (new, ~15 conditions).
- `PatientCarePlanResponse.conditions: list[PatientConditionView]` (backend, `patient_access`
  module) — documented conditions were previously clinician-only and never reached the patient
  view at all; they do now, alongside their explainer when one exists.
- `ConditionExplainerCard` component on `PatientCarePage.tsx` — the three-panel visual layout.
- 3 new backend tests (condition with curated explainer, condition without one, empty list) — 380
  backend tests passing overall.
- Verified live via Playwright: documented "Hypertension" on a real patient, confirmed the
  three-panel card renders correctly on the actual patient care page with real content.

### If real AI-generated imagery is wanted later
Not ruled out forever — the honest path, if this is revisited, is the same one AI ambient scribes
use for clinical notes: generate a **draft**, require **explicit clinician review and approval**
before a patient ever sees it (never auto-shown), and even then, this research suggests treating
model-generated anatomical/medical imagery as meaningfully higher-risk than generated *text* given
current (2026) model capability — worth a dedicated safety pass of its own if pursued, not a
quick addition.

---

## Sources
- [2026 Hospital Patient Engagement Platforms: Evidence, Comparison & Guide](https://ouva.co/blog/patient-engagement-platform-guide-2026/)
- [Healthcare Education Solution Market Size, Growth & Share Analysis 2031](https://www.mordorintelligence.com/industry-reports/healthcare-education-solution)
- [A Inaccurate Anatomy: Prevalence of AI-Generated Illustration Errors in Peer-reviewed Aesthetic Medicine Publications](https://pubmed.ncbi.nlm.nih.gov/42040517/)
- [Anatomical Fidelity in Text-to-Image Generative AI: A Comparative Qualitative and Quantitative Evaluation](https://pubmed.ncbi.nlm.nih.gov/42400299/)
- [Bias, representation, and clinical fidelity in AI-generated images for medical education (npj Digital Medicine)](https://www.nature.com/articles/s41746-026-02608-3)
- [AI scribes modestly reduce clinician documentation time and EHR use](https://www.news-medical.net/news/20260401/AI-scribes-modestly-reduce-clinician-documentation-time-and-EHR-use.aspx)
- [Ambient artificial intelligence scribes: physician burnout and perspectives on usability and documentation burden (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11756571/)
- [VisualDx — what this medical librarian wishes more people knew about clinical informatics](https://www.visualdx.com/blog/what-this-medical-librarian-wishes-more-people-knew-about-clinical-informatics/)

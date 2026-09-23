# Planning: fitting SafeHaven into a real hospital flow

Written in response to five points raised on 2026-09-23. Grounded in what the
code actually does today — I checked each claim before writing it.

---

## 1. "Why did the patient come?" — the field exists, the flow never asks

**What I found.** `Encounter` already has `reason_for_visit` and
`encounter_type` (`app/encounters/models.py`), and there is already a UI panel
that captures a reason and an admission date
(`EncountersPanel.tsx`). So the concept is modelled.

**The actual gap is the flow, not the model.** Registering a patient creates
**no encounter at all** — `patients/service.py` never touches Encounter. So a
newly registered patient has no visit, no reason, and nothing prompts anyone
to add one. It sits in a separate optional panel further down the patient
page that a busy clinician has no reason to open. `encounter_type` isn't even
wired into that panel — it's in the model only.

**What this costs.** Every downstream feature that could use "why are they
here" has nothing to read. The patient's own care page can't say it. Module 2
can't reason about it. The condition explainer can't connect to it.

**Fix shape:** ask for the reason at registration, creating the opening
encounter in the same step. Small, and it turns an unused model into a real
one.

---

## 2. Surgery / admission type — and the Module 2 connection you're pointing at

This is the sharpest point raised, and it is genuinely missing.

There is no concept of a **planned procedure** anywhere: no surgery, no
scheduled date, no pre-operative state. `encounter_type` is free text and
unused.

**Why this matters for Module 2 specifically.** Before surgery a patient is
typically **nil by mouth (NPO)**, and certain drugs are **deliberately held**
— most notably anticoagulants. Warfarin is already in our catalogue and
already flagged high-alert. Today, if a patient is NPO awaiting surgery at
08:00:

- the order is still ACTIVE
- the dose, route, formulation and timing all still match
- Module 2 returns **VERIFIED**, and the nurse is told it is safe to give

That is exactly the same class of bug as the discharged-patient one fixed
yesterday: **the engine knows the patient's orders but nothing about the
patient's situation.** Discharge was one situational state; pre-op NPO is
another, and clinically a more dangerous one.

**So yes — Module 2 has to connect to the doctor's admission decision.** The
connection is: the encounter carries the patient's situational state (admitted
medical / admitted surgical / pre-op NPO from a time), and the verification
engine gains a situational check alongside the allergy and admission checks it
already has. The fix has a shape we have already proven twice.

**Design note worth deciding deliberately:** a held pre-op dose is *not* the
same as a wrong dose. BLOCKED may be right for NPO; but "held" is really a
third outcome that the system currently cannot express at all — which leads
directly to point 3.

---

## 3. "Verification done, but was the dose actually given?" — correct, and it's the biggest hole

You are right, and it is worse than it looks.

`AdministrationEvent` records `administered_at` and `administered_by`, but
**nothing ever reads them back**. There is no endpoint, no MAR, no history
view. After confirming a dose the nurse sees an ephemeral "Administration
confirmed" card that vanishes on refresh and doesn't even name the drug.

Consequences today:

- No one — next shift, supervisor, doctor — can see what was given, when, or
  by whom.
- There is **no way to record a dose that was not given**: refused, held,
  vomited, patient off the ward. Real nursing requires documenting this.
- Because of that, an abandoned verification and a refused dose are the *same
  row* in the database. Indistinguishable.

**This is the single most important missing piece in Module 2**, and it is
also the thing that makes point 2 expressible: "held pre-op" is one of the
not-given reasons.

Minimum useful version: an administration record per patient (what, when, who,
co-signer, PRN reason), plus a not-given outcome with a reason.

---

## 4. Alerts dashboard — you called it optional; I think it is not

Today every safety signal the system produces is **only visible if someone
opens that specific patient**:

- a patient failed teach-back
- a patient asked a question
- a blocked wrong-drug or allergy scan
- a generation that failed fact-preservation

Nobody is watching. The system is good at *catching* things and has nowhere to
*put* them. That is why I'd argue this isn't optional — an alert nobody sees
is close to an alert that didn't fire.

Medication alerts are the right first slice, as you suggested: blocked scans
and allergy/interaction blocks are high-signal and low-volume. The thing to
avoid is a feed that mixes them with routine events — that is how alert
fatigue starts, and we have already fixed one instance of it this week (the
grey "info" dot on blocked scans).

---

## 5. "Real-time hospital ecosystem" — an honest read

Worth separating what "real-time" can mean here:

**Realistic for this prototype**
- Live-updating clinician views (poll or websocket) so a second nurse sees a
  dose was just given.
- The alert queue above, updating without a refresh.
- Situational state (NPO, discharged, pre-op) reflected immediately in Module 2.

**Not realistic without a real hospital integration, and honest to say so**
- True interoperability with the hospital's ADT feed (admissions, discharges,
  transfers), pharmacy dispensing, or theatre scheduling. In a real deployment
  SafeHaven would *receive* admission and surgery data from those systems, not
  own it. That is the FHIR/HL7 work previously deferred — and it remains the
  right thing to defer, because a partial version creates false confidence.
- Barcodes matching real unit-dose packaging (NDC/GS1).

The useful framing: **build the internal ecosystem so it is correct on its own
terms, and keep every external boundary explicit** — encounter state, MAR,
alerts are all things SafeHaven can own honestly today, and each is designed
so a real ADT/pharmacy feed could later populate it instead of a human.

---

## 6. The demo video has no audio

Correct — it's silent, with on-screen caption cards only.

Fixable without re-shooting the concept: the narration text already exists as
those caption strings. Approach is to synthesize each caption with the same
edge-tts the app already uses for patients, hold each card for the length of
its narration, record the exact timestamp each card appears, then build a
matching audio track and mux it in. About one recording cycle of work.

---

## Suggested sequence

Ordered by patient-safety value, with the cheap enablers first:

1. **Reason for visit at registration** — small, unlocks everything downstream.
2. **Administration record + not-given outcomes** — the biggest Module 2 hole,
   and a prerequisite for expressing "held".
3. **Encounter situational state + the pre-op / NPO check in Module 2** — the
   connection raised in point 2; depends on 1 and 2.
4. **Medication alert queue** — once there are events worth routing.
5. **Live updates** — last; it is polish on top of the above, not a foundation.

Video audio is independent of all of it and can be done at any point.

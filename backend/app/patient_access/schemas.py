import enum
import uuid
from typing import Literal
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.instructions.models import InstructionType
from app.patients.models import Language


class CarePlanAudioRequest(BaseModel):
    """text is whatever the patient's browser is currently displaying (already
    an approved, validated, patient-facing string) — this endpoint only
    converts it to speech, it never sources or displays new content itself."""

    token: str
    text: str = Field(min_length=1, max_length=2000)
    language: Language


class CareAccessTokenCreate(BaseModel):
    """expires_in_hours lets a clinician request a shorter-lived link than the
    configured default (CARE_TOKEN_TTL_HOURS) — e.g. for a single home-visit
    window. It is capped at that same default in the service layer; there is no
    way to request a longer-lived or permanent token."""

    expires_in_hours: int | None = None


class CareAccessTokenCreateResponse(BaseModel):
    # The only time the raw token is ever available — never retrievable again,
    # never logged, never returned by any other endpoint.
    token: str
    expires_at: datetime


class CareAccessTokenStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CareAccessTokenSummary(BaseModel):
    """Never includes the raw token or its hash — only what a clinician needs to
    manage the link (when it was made, when it expires, whether it's still
    live)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    status: CareAccessTokenStatus


class CareAccessTokenListResponse(BaseModel):
    total: int
    results: list[CareAccessTokenSummary]


# ---------------------------------------------------------------------------
# Patient-facing — deliberately minimal. No provider/model metadata, no
# validation internals, no failed attempts, no clinician notes, no audit
# metadata. See patient_access/service.py's get_care_plan(). The one
# exception is `id` on PatientCareInstructionView: an opaque reference to
# content the patient can already see in full is not a meaningful exposure,
# and the comprehension-feedback endpoint (/care-plan/feedback) needs some
# way to say which instruction "did this help?" is answering.
# ---------------------------------------------------------------------------


class WhyTier(str, enum.Enum):
    DOCUMENTED = "DOCUMENTED"  # the clinician's own instruction stated the reason
    GENERAL = "GENERAL"  # no documented reason, but general reference info exists
    NONE = "NONE"  # neither — nothing shown, never a guess


class WhyExplanation(BaseModel):
    tier: WhyTier
    text: str
    # Only set for GENERAL — reminds the patient this isn't confirmed as
    # their specific reason. Never set for DOCUMENTED (no disclaimer needed
    # when it's the clinician's own stated reason) or NONE (no text at all).
    disclaimer: str | None = None


class PatientCareInstructionView(BaseModel):
    id: uuid.UUID
    instruction_type: InstructionType | None
    text_by_language: dict[str, str]
    approved_at: datetime
    # English-only for this prototype — see patient_access/service.py's
    # resolve_why() docstring for why this isn't run through the translation
    # pipeline (yet).
    why: WhyExplanation | None = None
    # Only set for a past medication, and only to distinguish the two very
    # different reasons one lands there. Without this the patient page could
    # not tell them apart: a drug STOPPED because it was harming the patient
    # rendered identically to a course they had simply finished, under the
    # same muted "Past Medications" heading. Those need opposite responses
    # from the patient — one is "do not take any more of this", the other is
    # "nothing to do".
    past_reason: Literal["STOPPED", "COMPLETED"] | None = None


class ConditionExplainerView(BaseModel):
    what_it_is: str
    how_it_develops: str
    where_it_affects: str


class PatientConditionView(BaseModel):
    """explainer is only set when the condition name matches the curated
    table (app/reference/condition_explainers.py) exactly — never a guess,
    same rule as WhyExplanation's GENERAL tier. A condition with no matching
    explainer still appears (by name only) rather than being hidden."""

    condition_name: str
    explainer: ConditionExplainerView | None = None


class PatientAllergyView(BaseModel):
    """The patient's own documented allergies, shown back to them.

    Patients are a real safety check in this loop, not just an audience: "I'm
    allergic to penicillin" is one of the most valuable things a patient can
    say at the bedside, and showing them the list is also the only practical
    way they can notice it is wrong or incomplete. reaction/severity are
    included when documented because "rash" and "anaphylaxis" are not the
    same thing to a patient deciding how urgently to speak up."""

    allergen: str
    reaction: str | None = None
    severity: str | None = None


class PatientCarePlanResponse(BaseModel):
    patient_first_name: str
    preferred_language: Language
    instructions: list[PatientCareInstructionView]
    # Medications whose CareInstruction.clinical_status is COMPLETED or
    # STOPPED — never deleted, just shown separately. Always empty for
    # patients with no completed/stopped medications; non-medication
    # instructions never appear here (see ClinicalStatus's docstring).
    past_medications: list[PatientCareInstructionView] = []
    conditions: list[PatientConditionView] = []
    allergies: list[PatientAllergyView] = []

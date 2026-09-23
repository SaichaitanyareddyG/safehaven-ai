"""Static, curated reference of known dangerous drug-drug interactions —
Module 2's third reference table alongside medication_purpose.py and
medication_products.py, built the same deliberate way: a small, hand-curated,
non-patient-specific table, not a live interaction-database integration (a
real production system would connect something like First Databank or
Lexicomp; this is a prototype-scale stand-in with the same "swap the table,
not the code that reads it" upgrade path).

Only covers well-established, textbook-level interactions — precision over
completeness, same philosophy as medication_purpose.py. Each entry captures
a SEVERITY ("SEVERE" or "MODERATE") because real drug interactions aren't
uniformly absolute contraindications: medication_verification/service.py's
_check_drug_interactions treats a SEVERE match as an absolute BLOCK (same
as a documented allergy) and a MODERATE match as a WARNING requiring
clinician acknowledgment, never silently ignored either way.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DrugInteraction:
    drug_a: str
    drug_b: str
    severity: str  # "SEVERE" | "MODERATE"
    description: str


# Matching is substring-based on lowercased free-text medication names (see
# find_interaction) — deliberately simple, same prototype-scale precedent as
# medication_purpose.py's exact-name lookup and _drug_family_matches'
# base-word matching elsewhere in this codebase.
DRUG_INTERACTIONS: list[DrugInteraction] = [
    DrugInteraction(
        "warfarin",
        "aspirin",
        "SEVERE",
        "Combining an anticoagulant with aspirin significantly increases bleeding risk.",
    ),
    DrugInteraction(
        "warfarin",
        "ibuprofen",
        "SEVERE",
        "NSAIDs combined with an anticoagulant significantly increase bleeding risk.",
    ),
    DrugInteraction(
        "warfarin",
        "naproxen",
        "SEVERE",
        "NSAIDs combined with an anticoagulant significantly increase bleeding risk.",
    ),
    DrugInteraction(
        "warfarin",
        "amiodarone",
        "MODERATE",
        "Amiodarone can significantly increase warfarin's blood-thinning effect — closer monitoring is advised.",
    ),
    DrugInteraction(
        "lisinopril",
        "spironolactone",
        "MODERATE",
        "Combining an ACE inhibitor with a potassium-sparing diuretic increases the risk of high potassium levels (hyperkalemia).",
    ),
    DrugInteraction(
        "lisinopril",
        "potassium",
        "MODERATE",
        "Combining an ACE inhibitor with potassium supplementation increases the risk of high potassium levels (hyperkalemia).",
    ),
    DrugInteraction(
        "metoprolol",
        "verapamil",
        "SEVERE",
        "Combining a beta-blocker with verapamil can cause dangerously slow heart rate or low blood pressure.",
    ),
    DrugInteraction(
        "metoprolol",
        "diltiazem",
        "SEVERE",
        "Combining a beta-blocker with diltiazem can cause dangerously slow heart rate or low blood pressure.",
    ),
    DrugInteraction(
        "metoprolol",
        "clonidine",
        "MODERATE",
        "Combining a beta-blocker with clonidine requires closer monitoring — abrupt clonidine "
        "withdrawal while on a beta-blocker can cause a dangerous rebound rise in blood pressure.",
    ),
    DrugInteraction(
        "sertraline",
        "tramadol",
        "SEVERE",
        "Combining an SSRI with tramadol increases the risk of serotonin syndrome.",
    ),
]


def find_interaction(medication_name_a: str | None, medication_name_b: str | None) -> DrugInteraction | None:
    if not medication_name_a or not medication_name_b:
        return None
    a = medication_name_a.strip().lower()
    b = medication_name_b.strip().lower()
    for interaction in DRUG_INTERACTIONS:
        if (interaction.drug_a in a and interaction.drug_b in b) or (interaction.drug_a in b and interaction.drug_b in a):
            return interaction
    return None

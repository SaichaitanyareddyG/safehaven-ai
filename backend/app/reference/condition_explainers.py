"""Static, curated patient-education explainer for common documented
conditions — shown on the patient care page next to a clinician-documented
condition (see app/conditions/models.py's PatientCondition), the same "why
this matters to you" role medication_purpose.py plays for medications.

Deliberately NOT AI-generated, and deliberately NOT an image. Real-world
research on AI-generated medical/anatomical illustrations (2026, peer
reviewed) found gross, sometimes "biologically impossible" inaccuracies in
generated anatomy once complexity rises past simple shapes — exactly the
kind of ungrounded model output this project's core principle ("AI proposes,
validation decides", and specifically resolve_why()'s "never guess, never
let an LLM fill a reference gap" rule) refuses to ship to a patient. There is
no deterministic way to validate that a generated image is anatomically
correct the way fact_preservation.py validates generated TEXT field-by-field.
So this follows the exact same safe pattern as medication_purpose.py instead:
a small, hand-curated, non-patient-specific table of plain-language facts,
rendered as a structured three-panel card (what it is / how it develops /
where it affects the body) by the frontend — see
ConditionExplainerCard.tsx — using icons, not a generated picture.

If a documented condition isn't in this table, no explainer is shown for it
— never a guess, and never an LLM asked to fill the gap. See
US_HOSPITAL_MARKET_STANDARDS_GAP_ANALYSIS.md's "visual disease explainer"
research note for the full evaluation of why this approach was chosen over
live AI image generation.

Deliberately small (a prototype covering ~15 common conditions), not a
substitute for a real, licensed patient-education content library (e.g.
Krames, VisualDx) — same "swap the table, not the code that reads it" plan
as medication_purpose.py.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConditionExplainer:
    what_it_is: str
    how_it_develops: str
    where_it_affects: str


# Keyed by lowercased condition name — exact match only, same as
# medication_purpose.py (no fuzzy/partial matching, to avoid attaching the
# wrong condition's explainer to a similarly-named one).
CONDITION_EXPLAINERS: dict[str, ConditionExplainer] = {
    "hypertension": ConditionExplainer(
        what_it_is="High blood pressure — the force of your blood against your artery walls is consistently too high.",
        how_it_develops="Often builds up gradually from a mix of factors like diet, weight, stress, genetics, and age — usually with no single cause.",
        where_it_affects="Your heart, arteries, kidneys, and eyes over time, since they all rely on steady, healthy blood flow.",
    ),
    "high blood pressure": ConditionExplainer(
        what_it_is="The force of your blood against your artery walls is consistently too high.",
        how_it_develops="Often builds up gradually from a mix of factors like diet, weight, stress, genetics, and age — usually with no single cause.",
        where_it_affects="Your heart, arteries, kidneys, and eyes over time, since they all rely on steady, healthy blood flow.",
    ),
    "type 2 diabetes": ConditionExplainer(
        what_it_is="Your body has trouble using insulin properly, so blood sugar (glucose) builds up higher than it should.",
        how_it_develops="Develops gradually, usually linked to a mix of genetics, weight, and activity level, as the body's cells become less responsive to insulin.",
        where_it_affects="Blood vessels and nerves throughout the body — especially the eyes, kidneys, feet, and heart — if blood sugar stays high over time.",
    ),
    "diabetes": ConditionExplainer(
        what_it_is="Your body has trouble regulating blood sugar (glucose), so it builds up higher than it should.",
        how_it_develops="Develops when the body doesn't make enough insulin, or doesn't use it well, for reasons that vary by type.",
        where_it_affects="Blood vessels and nerves throughout the body — especially the eyes, kidneys, feet, and heart — if blood sugar stays high over time.",
    ),
    "asthma": ConditionExplainer(
        what_it_is="A condition where your airways become inflamed and narrow, making it harder to breathe.",
        how_it_develops="Often starts in childhood or after repeated exposure to triggers like allergens, smoke, or respiratory infections.",
        where_it_affects="Your lungs and airways — flare-ups can be triggered by exercise, allergens, cold air, or illness.",
    ),
    "copd": ConditionExplainer(
        what_it_is="Chronic Obstructive Pulmonary Disease — long-term damage that makes it harder to breathe.",
        how_it_develops="Most often develops over years from long-term exposure to lung irritants, most commonly cigarette smoke.",
        where_it_affects="Your lungs — the airways and air sacs lose their normal elasticity, making airflow harder over time.",
    ),
    "coronary artery disease": ConditionExplainer(
        what_it_is="The arteries that supply blood to your heart become narrowed, usually by a buildup of fatty deposits.",
        how_it_develops="Builds up slowly over years from factors like cholesterol, blood pressure, smoking, and diabetes.",
        where_it_affects="The blood vessels feeding your heart muscle — reduced blood flow can cause chest pain or, if a vessel blocks fully, a heart attack.",
    ),
    "heart failure": ConditionExplainer(
        what_it_is="Your heart isn't pumping blood as efficiently as the body needs — not that it has stopped working.",
        how_it_develops="Usually develops after the heart muscle is weakened or stiffened by another condition, like long-term high blood pressure or a prior heart attack.",
        where_it_affects="Blood flow throughout the body — can cause fluid buildup in the lungs, legs, and abdomen as circulation slows.",
    ),
    "atrial fibrillation": ConditionExplainer(
        what_it_is="An irregular, often rapid heart rhythm that starts in the heart's upper chambers.",
        how_it_develops="Can develop from age-related changes to the heart's electrical system, or alongside other heart, thyroid, or lung conditions.",
        where_it_affects="Your heart's rhythm and, because blood can pool in an irregularly beating heart, raises stroke risk if untreated.",
    ),
    "hypothyroidism": ConditionExplainer(
        what_it_is="An underactive thyroid gland — it isn't making enough thyroid hormone for your body's needs.",
        how_it_develops="Most often caused by an autoimmune condition (the immune system affecting the thyroid) or prior thyroid treatment/surgery.",
        where_it_affects="Your whole body's metabolism — commonly causing fatigue, weight gain, and feeling cold, since thyroid hormone affects nearly every organ.",
    ),
    "chronic kidney disease": ConditionExplainer(
        what_it_is="Your kidneys have lost some ability to filter waste and extra fluid from your blood.",
        how_it_develops="Usually develops gradually over years, most often as a complication of long-term diabetes or high blood pressure.",
        where_it_affects="Your kidneys, and over time the balance of fluid, minerals, and waste products throughout your whole body.",
    ),
    "osteoarthritis": ConditionExplainer(
        what_it_is="The protective cartilage that cushions your joints gradually wears down.",
        how_it_develops="Develops slowly with age and joint use, and can be sped up by prior joint injury, weight, or genetics.",
        where_it_affects="Your joints — most commonly knees, hips, hands, and spine — causing pain and stiffness that's often worse with activity.",
    ),
    "depression": ConditionExplainer(
        what_it_is="A medical condition affecting mood, thoughts, and energy — not just ordinary sadness, and not something to simply push through.",
        how_it_develops="Can arise from a combination of brain chemistry, genetics, life circumstances, and other health conditions — often with no single trigger.",
        where_it_affects="Your mood, sleep, energy, and concentration, and can affect physical health too if left untreated.",
    ),
    "anxiety": ConditionExplainer(
        what_it_is="A condition where worry, fear, or nervousness becomes persistent and hard to control, beyond normal everyday stress.",
        how_it_develops="Can develop from a mix of genetics, brain chemistry, and life experiences, and sometimes runs in families.",
        where_it_affects="Your mind and body together — it can cause a racing heart, trouble sleeping, and difficulty concentrating, alongside the worry itself.",
    ),
    "gastroesophageal reflux disease": ConditionExplainer(
        what_it_is="Stomach acid regularly flows back up into your esophagus (the tube connecting your throat to your stomach), also called GERD.",
        how_it_develops="Often develops when the muscle that normally keeps stomach acid down weakens or relaxes too often.",
        where_it_affects="Your esophagus and throat — repeated acid exposure causes the burning sensation known as heartburn, and can irritate the lining over time.",
    ),
}


def lookup_condition_explainer(condition_name: str | None) -> ConditionExplainer | None:
    if not condition_name:
        return None
    return CONDITION_EXPLAINERS.get(condition_name.strip().lower())
